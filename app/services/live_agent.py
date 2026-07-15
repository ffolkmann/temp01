"""Élő operátor-átvétel — session-állapot + üzenet-napló szolgáltatás (m28).

A widget-oldal (app/api/chat.py) és az operátor-felület (app/api/operator.py)
KÖZÖS adat-rétege a chat_sessions + chat_messages táblákhoz.

Állapotgép:  bot -> requested -> operator -> closed.
- bot:        a bot válaszol (nincs vagy 'bot' állapotú session-sor).
- requested:  a látogató operátort kért; a bot elnémul (handoff_bot_silent),
              a sor bekerül az operátor-várólistába.
- operator:   egy operátor átvette (ATOMI claim); a bot NÉMA, az üzenetek a
              chat_messages-en át folynak, a widget /chat/poll-lal olvassa.
- closed:     az operátor lezárta.

A get_session (app/core/db) NEM commitál a kérés végén -> minden ÍRÓ primitív
maga commitál (a services/conversations.log_turn mintájára). Az olvasók nem.
A hívó felel a fail-safe-ért (a /chat SOHA nem törhet meg emiatt).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import ChatMessage, ChatSession, Message

# A látogatónak adott "várj, jön az operátor" válasz (handoff -> requested).
LIVE_AGENT_WAIT_REPLY = (
    "Egy pillanat, továbbítom egy munkatársunknak — kérlek, maradj a chaten, "
    "hamarosan válaszolunk."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Olvasók
# --------------------------------------------------------------------------- #
async def get_session_state(db: AsyncSession, client_id: str, session_id: str | None) -> str:
    """A session állapota; nincs sor -> 'bot'."""
    if not session_id:
        return "bot"
    state = (
        await db.execute(
            select(ChatSession.state).where(ChatSession.session_id == session_id)
        )
    ).scalar_one_or_none()
    return state or "bot"


def _msg_row(m: ChatMessage) -> dict:
    ts = m.created_at.isoformat() if getattr(m, "created_at", None) else None
    return {"id": m.id, "sender": m.sender, "text": m.text or "", "ts": ts}


async def poll_messages(
    db: AsyncSession,
    session_id: str | None,
    after: int = 0,
    senders: tuple[str, ...] | None = None,
) -> list[dict]:
    """`after` id fölötti üzenetek időrendben; opcionális sender-szűrő."""
    if not session_id:
        return []
    q = select(ChatMessage).where(
        ChatMessage.session_id == session_id, ChatMessage.id > int(after or 0)
    )
    if senders:
        q = q.where(ChatMessage.sender.in_(senders))
    q = q.order_by(ChatMessage.id.asc())
    rows = (await db.execute(q)).scalars().all()
    return [_msg_row(m) for m in rows]


async def list_queue(db: AsyncSession, client_id: str | None = None) -> list[dict]:
    """Operátor-várólista: requested + operator állapotú sessionök (utolsó user-előnézettel)."""
    q = select(ChatSession).where(ChatSession.state.in_(("requested", "operator")))
    if client_id:
        q = q.where(ChatSession.client_id == client_id)
    q = q.order_by(ChatSession.requested_at.asc().nulls_last())
    rows = (await db.execute(q)).scalars().all()
    out: list[dict] = []
    for s in rows:
        preview = (
            await db.execute(
                select(ChatMessage.text)
                .where(ChatMessage.session_id == s.session_id, ChatMessage.sender == "user")
                .order_by(ChatMessage.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out.append(
            {
                "session_id": s.session_id,
                "client_id": s.client_id,
                "state": s.state,
                "claimed_by": s.claimed_by,
                "requested_at": s.requested_at.isoformat() if s.requested_at else None,
                "last_user_at": s.last_user_at.isoformat() if s.last_user_at else None,
                "last_op_at": s.last_op_at.isoformat() if s.last_op_at else None,
                "preview": (preview or "")[:120],
            }
        )
    return out


async def get_conversation(
    db: AsyncSession, session_id: str, after: int = 0, client_id: str | None = None
) -> dict:
    """Operátor-nézet: teljes üzenetlista (minden sender) + állapot.

    m46: bot-only sessionnél (nincs live-agent előzmény: chat_sessions sor
    nincs vagy 'bot', és nincs chat_messages sor) a `messages` naplóból adunk
    szintetikus átiratot (id=0 sorok, log_fallback=True) — az élő-monitor
    nézethez. A poll-kurzort (after>0) nem zavarja.
    """
    s = (
        await db.execute(select(ChatSession).where(ChatSession.session_id == session_id))
    ).scalar_one_or_none()
    msgs = await poll_messages(db, session_id, after, senders=None)
    state = s.state if s else "bot"
    cid = (s.client_id if s else "") or (client_id or "")
    log_fallback = False
    if not msgs and int(after or 0) <= 0 and state == "bot" and cid:
        msgs = await transcript_rows(db, cid, session_id)
        log_fallback = bool(msgs)
    return {
        "state": state,
        "claimed_by": s.claimed_by if s else None,
        "client_id": cid,
        "messages": msgs,
        "log_fallback": log_fallback,
    }


async def resolve_client_id(db: AsyncSession, session_id: str) -> str | None:
    """m46: session -> client_id. Előbb chat_sessions, különben a `messages`
    napló (bot-only sessionnek nincs chat_sessions sora). Ismeretlen -> None."""
    if not session_id:
        return None
    cid = (
        await db.execute(
            select(ChatSession.client_id).where(ChatSession.session_id == session_id)
        )
    ).scalar_one_or_none()
    if cid:
        return str(cid)
    cid = (
        await db.execute(
            select(Message.client_id)
            .where(Message.session_id == session_id)
            .order_by(Message.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return str(cid) if cid else None


async def transcript_rows(
    db: AsyncSession, client_id: str, session_id: str, cap: int = 200
) -> list[dict]:
    """m46: a `messages` (turn-)napló -> chat_messages-kompatibilis sorok (id=0)."""
    rows = (
        await db.execute(
            select(Message.question, Message.answer, Message.created_at)
            .where(Message.client_id == client_id, Message.session_id == session_id)
            .order_by(Message.created_at, Message.id)
            .limit(int(cap))
        )
    ).all()
    out: list[dict] = []
    for q, a, ts in rows:
        iso = ts.isoformat() if ts else None
        if q:
            out.append({"id": 0, "sender": "user", "text": str(q), "ts": iso})
        if a:
            out.append({"id": 0, "sender": "bot", "text": str(a), "ts": iso})
    return out


async def list_live(
    db: AsyncSession, client_id: str | None = None, minutes: int = 30, limit: int = 50
) -> list[dict]:
    """m46/A: élő lista — aktív sessionök az utolsó `minutes` percből a
    `messages` naplóból (ott minden turn megvan; chat_sessions sor csak handoff
    után létezik), a chat_sessions állapotával kiegészítve (LEFT JOIN
    jelleg, Python-oldalon). Listanézet: metaadat + utolsó turn."""
    cutoff = _now() - timedelta(minutes=int(minutes or 30))
    conds = [Message.created_at >= cutoff, Message.session_id.is_not(None)]
    if client_id:
        conds.append(Message.client_id == client_id)
    agg = (
        await db.execute(
            select(
                Message.session_id,
                Message.client_id,
                func.count(Message.id),
                func.max(Message.created_at),
                func.max(Message.id),
            )
            .where(*conds)
            .group_by(Message.session_id, Message.client_id)
            .order_by(func.max(Message.created_at).desc())
            .limit(int(limit))
        )
    ).all()
    out: list[dict] = []
    for sid, cid, turns, last_ts, last_id in agg:
        last = (
            await db.execute(
                select(Message.question, Message.answer).where(Message.id == last_id)
            )
        ).first()
        out.append(
            {
                "session_id": sid,
                "client_id": cid,
                "turns": int(turns or 0),
                "last_ts": last_ts.isoformat() if last_ts else None,
                "last_question": str((last[0] if last else "") or "")[:120],
                "last_answer": str((last[1] if last else "") or "")[:160],
                "state": "bot",
                "claimed_by": None,
            }
        )
    if out:
        srows = (
            (
                await db.execute(
                    select(ChatSession).where(
                        ChatSession.session_id.in_([r["session_id"] for r in out])
                    )
                )
            )
            .scalars()
            .all()
        )
        smap = {s.session_id: s for s in srows}
        for r in out:
            srow = smap.get(r["session_id"])
            if srow is not None:
                r["state"] = srow.state or "bot"
                r["claimed_by"] = srow.claimed_by
    return out


# --------------------------------------------------------------------------- #
# Írók (maguk commitálnak)
# --------------------------------------------------------------------------- #
async def _ensure_row(db: AsyncSession, client_id: str, session_id: str) -> None:
    exists = (
        await db.execute(
            select(ChatSession.session_id).where(ChatSession.session_id == session_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(ChatSession(session_id=session_id, client_id=client_id, state="bot"))
        await db.flush()


async def add_message(
    db: AsyncSession, client_id: str, session_id: str, sender: str, text: str
) -> int:
    """Üzenet a chat_messages-be + session időbélyeg. Commitál. Vissza: üzenet-id."""
    m = ChatMessage(client_id=client_id, session_id=session_id, sender=sender, text=text)
    db.add(m)
    await db.flush()
    mid = m.id
    if sender == "user":
        await db.execute(
            update(ChatSession)
            .where(ChatSession.session_id == session_id)
            .values(last_user_at=_now())
        )
    elif sender == "operator":
        await db.execute(
            update(ChatSession)
            .where(ChatSession.session_id == session_id)
            .values(last_op_at=_now())
        )
    await db.commit()
    return mid


async def request_operator(db: AsyncSession, client_id: str, session_id: str) -> None:
    """Session -> requested (get-or-create). Commitál."""
    await _ensure_row(db, client_id, session_id)
    await db.execute(
        update(ChatSession)
        .where(ChatSession.session_id == session_id)
        .values(client_id=client_id, state="requested", requested_at=_now())
    )
    await db.commit()


async def claim_session(db: AsyncSession, session_id: str, operator: str) -> bool:
    """ATOMI átvétel: csak requested -> operator. Vissza: sikerült-e (0 sor = elvették)."""
    res = await db.execute(
        update(ChatSession)
        .where(ChatSession.session_id == session_id, ChatSession.state == "requested")
        .values(state="operator", claimed_by=operator, claimed_at=_now())
    )
    n = res.rowcount or 0
    await db.commit()
    return n > 0


async def takeover_session(
    db: AsyncSession, client_id: str, session_id: str, operator: str
) -> str:
    """m46/B: proaktív átvétel BÁRMELY sessionre. Vissza: 'ok' | 'conflict'.

    bot / nincs-sor / requested / closed -> operator (get-or-create + claim);
    MÁSIK operátor aktív ('operator') sessionje -> 'conflict' — a WHERE-guard
    atomi. Ugyanaz az operátor -> idempotens 'ok' (claimed_at frissül). Commitál."""
    await _ensure_row(db, client_id, session_id)
    res = await db.execute(
        update(ChatSession)
        .where(
            ChatSession.session_id == session_id,
            or_(ChatSession.state != "operator", ChatSession.claimed_by == operator),
        )
        .values(state="operator", claimed_by=operator, claimed_at=_now())
    )
    n = res.rowcount or 0
    await db.commit()
    return "ok" if n > 0 else "conflict"


async def operator_send(db: AsyncSession, session_id: str, operator: str, text: str) -> int | None:
    """Operátor-üzenet. Csak 'operator' állapotban; különben None. Commitál (add_message)."""
    row = (
        await db.execute(
            select(ChatSession.state, ChatSession.client_id).where(
                ChatSession.session_id == session_id
            )
        )
    ).first()
    if row is None or row[0] != "operator":
        return None
    return await add_message(db, row[1], session_id, "operator", text)


async def close_session(db: AsyncSession, session_id: str) -> None:
    """Session -> closed. Commitál."""
    await db.execute(
        update(ChatSession)
        .where(ChatSession.session_id == session_id)
        .values(state="closed", closed_at=_now())
    )
    await db.commit()

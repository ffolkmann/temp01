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

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import ChatMessage, ChatSession

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


async def get_conversation(db: AsyncSession, session_id: str, after: int = 0) -> dict:
    """Operátor-nézet: teljes üzenetlista (minden sender) + állapot."""
    s = (
        await db.execute(select(ChatSession).where(ChatSession.session_id == session_id))
    ).scalar_one_or_none()
    msgs = await poll_messages(db, session_id, after, senders=None)
    return {
        "state": s.state if s else "bot",
        "claimed_by": s.claimed_by if s else None,
        "client_id": s.client_id if s else "",
        "messages": msgs,
    }


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

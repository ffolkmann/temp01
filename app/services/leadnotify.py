# -*- coding: utf-8 -*-
"""m123: lead-ertesito - beszelgetesenkent EGY level, csendes idoszak utan.

Lelet (nagyonallatshop 2026-10-19, leads 485-487): a widget minden collect_lead valasz utan uj
urlapot tett ki, a latogato 3x kitoltotte, es mindegyik kitoltes AZONNAL kulon levelet inditott a
beszelgetes akkori (csonka) allapotaval - a lenyeg (rendelesszam, kert csere) csak a harmadikban
volt. 30 nap: 132 leadbol 13 session kapott >1 levelet.

Uj mukodes:
- a lead azonnal mentodik (leads.notified_at NULL), levelet NEM a keres kuld;
- ez a hatter-ciklus (POLL_S) kuldi, ha a session QUIET_S ideje csendes (utolso uzenet / lead),
  vagy az elso fuggo lead MAX_WAIT_S ota var: osszevont elerhetoseg + teljes atirat, EGY level;
- ha egy mar ertesitett sessionben uj lead jon, vagy a latogato ERDEMI uj uzenetet ir,
  'kiegeszites' level megy (szinten csend utan), a teljes frissitett atirattal;
- session nelkuli lead: a leads.py azonnal kuldi (regi ut).
A tiszta fuggvenyek (decide, merge_contacts, substantive) stdlib-only; a DB/mail reszek lazy importtal.
"""

import asyncio
import logging

QUIET_S = 300       # Feco dontese 2026-10-19: 5 perc csend utan menjen a level
MAX_WAIT_S = 1800   # folyamatosan iro latogatonal se varjon 30 percnel tovabb
POLL_S = 60

logger = logging.getLogger("cx.leadnotify")

# rendszer-teny a dinamikus promptba (chat.py m123), ha a sessionben mar van elerhetoseg
NOTE = (
    "\n\n# ELÉRHETŐSÉG MÁR MEGVAN (rendszer-tény, igaz)\n"
    "A látogató ebben a beszélgetésben már megadta az elérhetőségét (e-mail-címet és/vagy "
    "telefonszámot). A rendszer rögzítette, és a beszélgetés teljes szövegével együtt eljuttatja a "
    "bolt munkatársainak. Ne kérd újra az e-mail-címét vagy a telefonszámát, és a collect_lead "
    "legyen false. Ha a látogató további részletet ír (például rendelésszámot vagy azt, mit "
    "szeretne módosítani), köszönd meg, és mondd, hogy ezt is megkapják a kollégák. Pontos "
    "visszahívási időpontot ne ígérj."
)

SQL_GROUPS = """
SELECT g.client_id, g.session_id, g.pending, g.last_notified, g.last_lead_at,
       g.first_pending_at, g.last_lead_id,
       (SELECT max(m.created_at) FROM messages m
         WHERE m.client_id = g.client_id AND m.session_id = g.session_id) AS last_msg,
       now() AS now
FROM (
  SELECT client_id, session_id,
         bool_or(notified_at IS NULL) AS pending,
         max(notified_at) AS last_notified,
         max(created_at) AS last_lead_at,
         min(created_at) FILTER (WHERE notified_at IS NULL) AS first_pending_at,
         max(id) AS last_lead_id
  FROM leads
  WHERE session_id IS NOT NULL AND session_id <> ''
    AND created_at > now() - interval '2 days'
  GROUP BY client_id, session_id
) g
"""


def _secs(a, b):
    try:
        return (a - b).total_seconds()
    except Exception:  # noqa: BLE001
        return 0.0


def decide(r, now, quiet=QUIET_S, max_wait=MAX_WAIT_S):
    """r: dict-szeru sor (pending, last_notified, last_lead_at, first_pending_at, last_msg).
    Vissza: None | 'new' | 'supplement' | 'msgs' (uzenet-alapu kiegeszites-jelolt, a hivo
    ellenorzi, hogy erdemi-e az uj uzenet)."""
    acts = [t for t in (r.get("last_lead_at"), r.get("last_msg")) if t is not None]
    if not acts:
        return None
    last_act = max(acts)
    quiet_ok = _secs(now, last_act) >= quiet
    if r.get("pending"):
        fp = r.get("first_pending_at")
        waited = _secs(now, fp) if fp is not None else 0.0
        if quiet_ok or waited >= max_wait:
            return "supplement" if r.get("last_notified") is not None else "new"
        return None
    ln, lm = r.get("last_notified"), r.get("last_msg")
    if ln is not None and lm is not None and lm > ln and quiet_ok:
        return "msgs"
    return None


def substantive(questions, trivial=None) -> bool:
    """Van-e erdemi (nem udvariassagi / nem ures) latogatoi uzenet a listaban."""
    if trivial is None:
        try:
            from app.services.trivialq import is_trivial as trivial
        except Exception:  # noqa: BLE001
            trivial = None
    for q in questions or []:
        s = str(q or "").strip()
        if len(s) < 3:
            continue
        try:
            if trivial is not None and trivial(s):
                continue
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


def merge_contacts(leads):
    """leads: idorendi lista dict(name, email, phone, message, source). Mezonkent a LEGUTOLSO
    nem ures ertek. source = 'chat', ha minden lead a chatbol jott, kulonben None (urlap)."""
    out = {"name": None, "email": None, "phone": None, "message": None}
    for ld in leads or []:
        for k in out:
            v = str((ld or {}).get(k) or "").strip()
            if v:
                out[k] = v
    srcs = [str((ld or {}).get("source") or "") for ld in leads or []]
    out["source"] = "chat" if srcs and all(s == "chat" for s in srcs) else None
    return out


def _pairs_from_history(history):
    pairs = []
    for h in history or []:
        if not isinstance(h, dict):
            continue
        c = h.get("content")
        if c:
            pairs.append((c, None) if h.get("role") == "user" else (None, c))
    return pairs


async def _claim(session, r, kind) -> bool:
    from sqlalchemy import text
    if kind in ("new", "supplement") and r.get("pending"):
        res = await session.execute(text(
            "UPDATE leads SET notified_at = now() WHERE client_id = :c AND session_id = :s "
            "AND notified_at IS NULL RETURNING id"),
            {"c": r["client_id"], "s": r["session_id"]})
    else:
        res = await session.execute(text(
            "UPDATE leads SET notified_at = now() WHERE id = :i AND notified_at = :t RETURNING id"),
            {"i": r["last_lead_id"], "t": r["last_notified"]})
    ok = bool(res.fetchall())
    await session.commit()
    return ok


async def _send(session, client_id, session_id, kind) -> bool:
    from sqlalchemy import select
    from app.core.mailer import safe_reply_to, send_email
    from app.models.db_models import Lead, Tenant
    from app.services.conversations import get_transcript
    from app.services.leadmail import build_lead_email

    leads = (await session.execute(
        select(Lead).where(Lead.client_id == client_id, Lead.session_id == session_id)
        .order_by(Lead.id))).scalars().all()
    tenant = (await session.execute(
        select(Tenant).where(Tenant.client_id == client_id))).scalar_one_or_none()
    m = merge_contacts([{"name": l.name, "email": l.email, "phone": l.phone,
                         "message": l.message, "source": l.source} for l in leads])
    turns = await get_transcript(session, client_id, session_id)
    pairs = [(t.question, t.answer) for t in turns] if turns else (
        _pairs_from_history(leads[-1].history) if leads else [])
    lead_email = (tenant.lead_email if tenant else None) or ""
    bot_name = (tenant.bot_name if tenant else None) or "Bot"
    await session.commit()  # kapcsolat vissza a poolba a HTTP-kuldes elott

    reply_to = safe_reply_to(m["email"])
    subject, text, html_body = build_lead_email(
        client_id=client_id, name=m["name"], email=m["email"], phone=m["phone"],
        message=m["message"], source=m["source"], reply_to=reply_to, turns=pairs,
        bot_name=bot_name, supplement=(kind == "supplement"))
    ok = await send_email(lead_email, subject, text, reply_to=reply_to, html=html_body)
    logger.info("m123 lead-level: %s kuldve=%d leads=%d fordulo=%d client=%s",
                kind, 1 if ok else 0, len(leads), len(pairs), client_id)
    return ok


async def flush_once(session) -> int:
    """Egy kor: az esedekes sessionok levelei. Vissza: elkuldott levelek szama."""
    from sqlalchemy import text
    rows = [dict(x) for x in (await session.execute(text(SQL_GROUPS))).mappings().all()]
    await session.commit()
    sent = 0
    for r in rows:
        try:
            kind = decide(r, r["now"])
            if kind is None:
                continue
            if kind == "msgs":
                qs = (await session.execute(text(
                    "SELECT question FROM messages WHERE client_id = :c AND session_id = :s "
                    "AND created_at > :t"),
                    {"c": r["client_id"], "s": r["session_id"], "t": r["last_notified"]})
                ).scalars().all()
                await session.commit()
                if not substantive(qs):
                    continue
                kind = "supplement"
            if not await _claim(session, r, kind):
                continue
            if await _send(session, r["client_id"], r["session_id"], kind):
                sent += 1
        except Exception:  # noqa: BLE001 - egy session hibaja ne allitsa meg a tobbit
            logger.exception("m123 lead-level hiba client=%s", r.get("client_id"))
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
    return sent


async def _loop():
    from app.core.db import SessionLocal
    await asyncio.sleep(POLL_S)
    while True:
        try:
            async with SessionLocal() as s:
                await flush_once(s)
        except Exception:  # noqa: BLE001
            logger.exception("m123 lead-notify ciklus hiba")
        await asyncio.sleep(POLL_S)


_task = None


def start_loop():
    """Az app startupjabol hivando (futo event loop kell). Egyszer indul."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop())
        logger.info("m123 lead-notify ciklus elindult (csend=%ds, max=%ds)", QUIET_S, MAX_WAIT_S)
    return _task

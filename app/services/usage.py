"""Usage-accounting — a chat-oldali számláló (a /stats forrása).

Definíció (n8n-konzisztens):
  - message      = bejövő USER üzenet (minden hívásnál +1).
  - conversation = egyedi session/period (csak az adott hónapban ELŐSZÖR látott session_id +1).

A session-elsőség Redisszel: SADD seen:<client_id>:<period> <session_id> == 1 -> új session.
Period = aktuális hónap Europe/Budapest 'YYYY-MM'. Fail-safe: Redis/DB hiba nem töri a /chat-et.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Usage

logger = logging.getLogger("cx.usage")

BUDAPEST = ZoneInfo("Europe/Budapest")
_SEEN_TTL = 40 * 24 * 3600  # ~40 nap


def current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(BUDAPEST)).astimezone(BUDAPEST).strftime("%Y-%m")


async def _is_new_session(redis, client_id: str, period: str, session_id: str | None) -> bool:
    if not session_id or redis is None:
        return False
    try:
        key = f"seen:{client_id}:{period}"
        added = await redis.sadd(key, session_id)
        if added == 1:
            await redis.expire(key, _SEEN_TTL)
            return True
        return False
    except Exception:  # noqa: BLE001 — Redis hiba: ne számoljunk dupla conversationt, de menjen tovább
        logger.warning("usage: Redis hiba (%s) — conversation nem számolva", client_id)
        return False


async def record_usage(session: AsyncSession, redis, client_id: str, session_id: str | None) -> None:
    """messages += 1; conversations += 1 csak ha a session ebben a periódusban ELŐSZÖR fordul elő."""
    period = current_period()
    new_session = await _is_new_session(redis, client_id, period, session_id)
    try:
        stmt = pg_insert(Usage).values(
            client_id=client_id, period=period, messages=1,
            conversations=(1 if new_session else 0),
        )
        set_ = {"messages": Usage.__table__.c.messages + 1}
        if new_session:
            set_["conversations"] = Usage.__table__.c.conversations + 1
        stmt = stmt.on_conflict_do_update(
            index_elements=["client_id", "period"], set_=set_,
        )
        await session.execute(stmt)
        await session.commit()
    except Exception:  # noqa: BLE001 — a usage-könyvelés SOHA ne törje a /chat-et
        logger.exception("usage: UPSERT hiba (%s)", client_id)
        await session.rollback()

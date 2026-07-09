"""Operátor-jelenlét (m28+) — globális online/offline presence Redisben.

Az élő operátor-átvétel csak akkor aktiválódik, ha az operátor-pult ÉPP ONLINE:
az operator.html-ben be van kapcsolva az "Online" kapcsoló, és fut a heartbeat.
A pult globális (egy várólista minden tenantnak) -> a jelenlét is globális.

Presence = rövid TTL-ű Redis-kulcs (150s), amit a konzol ~25 mp-enként frissít. Ha a konzolt
bezárják vagy kikapcsolják a kapcsolót, a kulcs lejár / törlődik -> offline -> a
handoff a régi e-mailes útra esik vissza (ne várjon a vevő olyan operátorra, aki nincs ott).

Kulcs: cx:operator:online
Fail-safe: bármely Redis-hiba -> is_operator_online() False (inkább e-mail, mint elnyelt vevő).
"""

import logging

from app.core.redis import get_redis

logger = logging.getLogger("cx.operator_presence")

_KEY = "cx:operator:online"
_TTL_SECONDS = 150  # a kliens ~25 mp-enként frissít; háttér-tabon a böngésző ~60s-re throttlingolhat,
                    # ezért a TTL bőven efölött (150s), hogy a háttérbe tett konzol se essen le.


async def set_online(operator: str = "operator") -> None:
    """Online-jelzés + TTL-frissítés (heartbeat). Idempotens, fail-safe."""
    try:
        await get_redis().set(_KEY, operator or "operator", ex=_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — presence-hiba ne törjön semmit
        logger.warning("operator_presence: set_online sikertelen")


async def set_offline() -> None:
    """Azonnali offline (kapcsoló kivétele / konzol bezárása). Fail-safe."""
    try:
        await get_redis().delete(_KEY)
    except Exception:  # noqa: BLE001
        logger.warning("operator_presence: set_offline sikertelen")


async def is_operator_online() -> bool:
    """Van-e MOST online operátor. Fail-safe: bármely hiba -> False."""
    try:
        return bool(await get_redis().exists(_KEY))
    except Exception:  # noqa: BLE001
        return False


async def status() -> dict:
    """Állapot a konzolnak: {"online": bool, "ttl": int}. ttl = hátralévő mp (vagy 0)."""
    try:
        ttl = await get_redis().ttl(_KEY)  # -2: nincs kulcs, -1: nincs TTL, >=0: hátralévő mp
        online = isinstance(ttl, int) and ttl >= 0
        return {"online": online, "ttl": ttl if (isinstance(ttl, int) and ttl > 0) else 0}
    except Exception:  # noqa: BLE001
        return {"online": False, "ttl": 0}

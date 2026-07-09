"""Operátor-jelenlét (m28+, m30) — TENANTONKÉNTI online/offline presence Redisben.

Az élő operátor-átvétel csak akkor aktiválódik, ha az adott tenanthoz tartozó
operátor-pult ÉPP ONLINE: az operator.html-ben be van kapcsolva az "Online"
kapcsoló, és fut a heartbeat.

m30: a presence tenantonként külön kulcson megy. Korábban EGY globális kulcs volt
(`cx:operator:online`), így ha bárki online volt, MINDEN tenant látogatói élő
átvételt kaptak felkínálva — más webshop operátorára várva. Kulcsok:

  cx:operator:online:<client_id>   -> az adott tenant operátora online
  cx:operator:online:__all__       -> MASTER pult (ADMIN_PANEL_TOKEN) online

`is_operator_online(client_id)` a kettő VAGY-a: a master pult minden tenantra
számít (ő látja is mindegyik várólistát), a tenant-token viszont csak a sajátjára.

Presence = rövid TTL-ű Redis-kulcs (150s), amit a konzol ~25 mp-enként frissít. Ha a konzolt
bezárják vagy kikapcsolják a kapcsolót, a kulcs lejár / törlődik -> offline -> a
handoff a régi e-mailes útra esik vissza (ne várjon a vevő olyan operátorra, aki nincs ott).

Fail-safe: bármely Redis-hiba -> is_operator_online() False (inkább e-mail, mint elnyelt vevő).
"""

import logging

from app.core.redis import get_redis

logger = logging.getLogger("cx.operator_presence")

_PREFIX = "cx:operator:online"
_ALL = "__all__"  # master pult (minden tenant)
_TTL_SECONDS = 150  # a kliens ~25 mp-enként frissít; háttér-tabon a böngésző ~60s-re throttlingolhat,
                    # ezért a TTL bőven efölött (150s), hogy a háttérbe tett konzol se essen le.


def presence_key(client_id: str | None) -> str:
    """Redis-kulcs. `None` (master pult) -> a `__all__` kulcs. PURE."""
    cid = (client_id or "").strip().lower()
    return f"{_PREFIX}:{cid or _ALL}"


async def set_online(operator: str = "operator", client_id: str | None = None) -> None:
    """Online-jelzés + TTL-frissítés (heartbeat). Idempotens, fail-safe."""
    try:
        await get_redis().set(presence_key(client_id), operator or "operator", ex=_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — presence-hiba ne törjön semmit
        logger.warning("operator_presence: set_online sikertelen")


async def set_offline(client_id: str | None = None) -> None:
    """Azonnali offline (kapcsoló kivétele / konzol bezárása). Fail-safe."""
    try:
        await get_redis().delete(presence_key(client_id))
    except Exception:  # noqa: BLE001
        logger.warning("operator_presence: set_offline sikertelen")


async def is_operator_online(client_id: str) -> bool:
    """Van-e MOST online operátor EHHEZ a tenanthoz (sajat pult VAGY master pult).

    Fail-safe: bármely hiba -> False.
    """
    try:
        r = get_redis()
        if await r.exists(presence_key(client_id)):
            return True
        return bool(await r.exists(presence_key(None)))
    except Exception:  # noqa: BLE001
        return False


async def status(client_id: str | None = None) -> dict:
    """Állapot a konzolnak: {"online": bool, "ttl": int}. ttl = hátralévő mp (vagy 0).

    A SAJÁT pult kulcsát nézi (a master a `__all__`-t), nem a másikét.
    """
    try:
        ttl = await get_redis().ttl(presence_key(client_id))  # -2: nincs kulcs, -1: nincs TTL
        online = isinstance(ttl, int) and ttl >= 0
        return {"online": online, "ttl": ttl if (isinstance(ttl, int) and ttl > 0) else 0}
    except Exception:  # noqa: BLE001
        return {"online": False, "ttl": 0}

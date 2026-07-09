"""Rate limit — Redis INCR + TTL, fix ablak (sliding-window nélkül, ide elég).

Elsődleges célja a rendelés-státusz lekérdezés védelme: a Webdoc API-n a rendelés
`id` a rendelésszámból kiszámolható, és nincs szerver-oldali hívásszám-korlát, így
a vásárló oldali próbálkozásokat NEKÜNK kell korlátoznunk (a másodlagos titok az
irányítószám — kb. 3200 valós magyar érték).

Fail-open: ha a Redis nem elérhető, a hívás átmegy (a rendelés-lekérdezés ne
haljon meg egy cache-kiesés miatt). A támadó a Redist nem tudja leállítani, egy
lokális kiesés viszont valós üzemzavart okozna. A hibát logoljuk.
"""

from __future__ import annotations

import logging

from app.core.redis import get_redis

logger = logging.getLogger("cx.ratelimit")

# rendelés-lekérdezés: 5 SIKERTELEN próbálkozás / 15 perc / (tenant, session)
ORDER_LOOKUP_LIMIT = 5
ORDER_LOOKUP_WINDOW = 900


def order_lookup_key(client_id: str, session_id: str | None) -> str:
    sid = str(session_id or "anon").strip() or "anon"
    return f"cx:rl:order:{client_id}:{sid}"


async def is_blocked(key: str, limit: int) -> bool:
    """Elérte-e már a limitet. Redis-hiba -> False (fail-open)."""
    try:
        cur = await get_redis().get(key)
        return bool(cur) and int(cur) >= limit
    except Exception:  # noqa: BLE001
        logger.warning("rate_limit: is_blocked olvasas sikertelen (%s)", key)
        return False


async def register_failure(key: str, window: int) -> int:
    """Egy sikertelen próbálkozás könyvelése; a számláló aktuális értéke.

    Az ablak az ELSŐ hibánál indul (nem tolódik minden hibával), így a
    kizárás determinisztikusan lejár. Redis-hiba -> 0.
    """
    try:
        r = get_redis()
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, window)
        return int(n)
    except Exception:  # noqa: BLE001
        logger.warning("rate_limit: register_failure sikertelen (%s)", key)
        return 0


async def clear(key: str) -> None:
    """Sikeres azonosítás után nullázunk (a jóhiszemű vevőt ne büntessük)."""
    try:
        await get_redis().delete(key)
    except Exception:  # noqa: BLE001
        logger.warning("rate_limit: clear sikertelen (%s)", key)

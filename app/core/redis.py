"""Redis kliens (a stackben futó Redishez) — usage-accounting session-dedup.

Lusta singleton; decode_responses=True (str). A hívók fail-safe-ek: ha a Redis nem elérhető,
a usage-számlálás degradál (nem dob), nem töri a /chat-et.
"""

from redis import asyncio as aioredis

from app.core.settings import get_settings

_settings = get_settings()
_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(_settings.redis_url, decode_responses=True)
    return _redis

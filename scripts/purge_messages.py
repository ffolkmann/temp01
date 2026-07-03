"""messages retention purge — 30 napnál régebbi sorok törlése (m22).

Futtatás (nightly, a cx-sync.service ExecStartPost-jából, throwaway api-konténerben):
  docker compose -f docker-compose.prod.yml run --rm api python scripts/purge_messages.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.core.db import engine  # noqa: E402

RETENTION_DAYS = 30


async def main() -> None:
    async with engine.begin() as conn:
        res = await conn.execute(text(
            f"DELETE FROM messages WHERE created_at < now() - interval '{RETENTION_DAYS} days'"
        ))
        print(f"purge_messages: {res.rowcount} sor torolve (> {RETENTION_DAYS} nap)")


if __name__ == "__main__":
    asyncio.run(main())

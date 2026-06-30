"""Sync CLI — python -m app.sync --tenant <client_id> | --all  [--dry-run] [--pricestock]

A v2 kollekcióba (cx_chatbot_v2) ír; az élő cx_chatbot-ot NEM érinti. Az ütemezés (systemd timer
az n8n nightly + Fast Scheduler helyett) KÉSŐBB jön, a validálás után.

  --pricestock : csak ár/készlet payload-frissítés (Build PS / PS Delta / Set Payload, EMBED nélkül).
"""

import argparse
import asyncio
import json

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.db_models import Tenant
from app.sync.engine import pricestock_tenant, sync_tenant


async def _run(client_id: str | None, do_all: bool, dry_run: bool, pricestock: bool) -> None:
    async with SessionLocal() as session:
        stmt = select(Tenant).where(Tenant.active.is_(True))
        if not do_all:
            stmt = stmt.where(Tenant.client_id == client_id)
        tenants = (await session.execute(stmt)).scalars().all()

    if not tenants:
        print(json.dumps({"error": "nincs egyező aktív tenant"}, ensure_ascii=False))
        return

    runner = pricestock_tenant if pricestock else sync_tenant
    for t in tenants:
        res = await runner(t, dry_run=dry_run)
        print(json.dumps(res, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description="CodeXpress termék-szinkron (Fázis 3) -> cx_chatbot_v2")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tenant", help="egy tenant client_id-ja")
    g.add_argument("--all", action="store_true", help="minden aktív tenant")
    ap.add_argument("--dry-run", action="store_true", help="csak számol, nem ír Qdrantba")
    ap.add_argument("--pricestock", action="store_true",
                    help="csak ár/készlet payload-frissítés (embed nélkül)")
    args = ap.parse_args()
    asyncio.run(_run(args.tenant, args.all, args.dry_run, args.pricestock))


if __name__ == "__main__":
    main()

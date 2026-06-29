"""Dev seed — tenants.json / plans.json / coupons.json -> Postgres.

Futtatás a GÉPEDRŐL (host), a lokális Postgresre:
    DATABASE_URL=postgresql+asyncpg://cx:cx@localhost:5432/cx \
        python scripts/seed_dev.py

A séma (bool/number) forrása a seed/columns.json; a koerció a scripts/dt_common.py-ben
(közös a migrate_from_n8n.py-vel). A popup_config str-JSON -> jsonb. Az n8n
id/createdAt/updatedAt mezőket eldobjuk. Idempotens: minden táblát újratölt.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dt_common as dt  # noqa: E402  (scripts/ a sys.path-on: python scripts/seed_dev.py)

from app.models.db_models import Coupon, Plan, Tenant  # noqa: E402

SEED = ROOT / "seed"
DB_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://cx:cx@localhost:5432/cx")


async def main() -> None:
    engine = create_async_engine(DB_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    col_types = dt.schema_from_columns_json()
    tenants = json.loads((SEED / "tenants.json").read_text(encoding="utf-8"))
    plans = json.loads((SEED / "plans.json").read_text(encoding="utf-8"))
    coupons = json.loads((SEED / "coupons.json").read_text(encoding="utf-8"))

    tenant_keep = frozenset(Tenant.__table__.columns.keys())
    plan_keep = frozenset(Plan.__table__.columns.keys())
    coupon_keep = frozenset(Coupon.__table__.columns.keys())

    async with Session() as s:
        # idempotens újratöltés
        await s.execute(delete(Coupon))
        await s.execute(delete(Plan))
        await s.execute(delete(Tenant))
        await s.commit()

        for r in plans:
            s.add(Plan(**dt.clean_row(col_types, dt.TID_PLANS, r, keep=plan_keep)))
        for r in tenants:
            s.add(Tenant(**dt.clean_row(
                col_types, dt.TID_TENANTS, r, json_cols=dt.TENANT_JSON, keep=tenant_keep)))
        for r in coupons:
            s.add(Coupon(**dt.clean_row(col_types, dt.TID_COUPONS, r, keep=coupon_keep)))
        await s.commit()

    await engine.dispose()
    print(f"seeded: {len(plans)} plans, {len(tenants)} tenants, {len(coupons)} coupons")


if __name__ == "__main__":
    asyncio.run(main())

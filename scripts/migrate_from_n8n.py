"""Élő n8n SQLite DataTable-ök -> Postgres (read-only forrás).

Az n8n adatait (config/plans/coupons) a kód-alapú rendszer Postgresébe tölti.
A forrás n8n DB-t KÖZVETLENÜL, READ-ONLY nyitjuk (mode=ro + query_only) —
NINCS .backup másolat (a VPS /tmp RAM-disk kicsi, az n8n DB több GB lehet, megtelne).

GUARDRAIL (CLAUDE.md A.0 / 9.): az élő n8n prod sérthetetlen — ez a script CSAK
olvas az n8n-ből. Ír kizárólag a cél-Postgresbe.

Futtatás a VPS-en (root), az élő n8n DB-vel:
    DATABASE_URL=postgresql+asyncpg://cx:cx@postgres:5432/cx \
        python3 scripts/migrate_from_n8n.py

    # próba — semmit nem ír, csak kiírja hány sort töltene:
    python3 scripts/migrate_from_n8n.py --dry-run

Env:
    N8N_DB_PATH   default /var/lib/docker/volumes/n8n-cxxz_n8n_data/_data/database.sqlite
    DATABASE_URL  a cél Postgres (asyncpg)

A séma/koerció a scripts/dt_common.py-ben (közös a seed_dev.py-vel); a bool/number
típusokat az élő `data_table_column` táblából olvassuk. A popup_config str-JSON -> jsonb.
Idempotens: tenants/plans ON CONFLICT upsert; coupons (nincs természetes kulcs)
delete+insert egy tranzakcióban.
"""

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dt_common as dt  # noqa: E402  (scripts/ a sys.path-on)

from app.models.db_models import Coupon, Plan, Tenant  # noqa: E402

N8N_DB_PATH = os.getenv(
    "N8N_DB_PATH",
    "/var/lib/docker/volumes/n8n-cxxz_n8n_data/_data/database.sqlite",
)
DB_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://cx:cx@localhost:5432/cx")


# --------------------------------------------------------------------------- #
# Forrás: read-only SQLite olvasás
# --------------------------------------------------------------------------- #
def open_n8n_readonly(path: str) -> sqlite3.Connection:
    """Élő n8n DB megnyitása szigorúan olvasásra (nem másoljuk!)."""
    if not Path(path).exists():
        raise SystemExit(f"n8n DB nem található: {path} (állítsd be a N8N_DB_PATH-t)")
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    # belt-and-suspenders: a kapcsolat se írhasson, élő WAL DB-n türelmes lock
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def read_table(conn: sqlite3.Connection, table_id: str) -> list[dict]:
    """Egy data_table_user_<id> tábla összes sora dict-ként."""
    cur = conn.execute(f'SELECT * FROM "data_table_user_{table_id}"')
    return [dict(r) for r in cur.fetchall()]


def load_source(conn: sqlite3.Connection):
    """Típus-térkép az élő data_table_column-ból + a három tábla nyers sorai."""
    col_types = dt.schema_from_db(conn)
    return (
        col_types,
        read_table(conn, dt.TID_TENANTS),
        read_table(conn, dt.TID_PLANS),
        read_table(conn, dt.TID_COUPONS),
    )


# --------------------------------------------------------------------------- #
# Cél: Postgres upsert
# --------------------------------------------------------------------------- #
async def upsert_on_conflict(session: AsyncSession, model, rows: list[dict], pk: str) -> None:
    """Bulk insert ... ON CONFLICT (pk) DO UPDATE — minden nem-PK oszlopot frissít."""
    if not rows:
        return
    stmt = pg_insert(model).values(rows)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in model.__table__.columns
        if c.name != pk
    }
    stmt = stmt.on_conflict_do_update(index_elements=[pk], set_=update_cols)
    await session.execute(stmt)


async def replace_all(session: AsyncSession, model, rows: list[dict]) -> None:
    """delete + insert — természetes kulcs nélküli tábláknál (coupons) idempotens."""
    await session.execute(delete(model))
    if rows:
        await session.execute(pg_insert(model).values(rows))


# --------------------------------------------------------------------------- #
# Fő folyamat
# --------------------------------------------------------------------------- #
def coerce_all(col_types, tenants_raw, plans_raw, coupons_raw):
    tenant_keep = frozenset(Tenant.__table__.columns.keys())
    plan_keep = frozenset(Plan.__table__.columns.keys())
    coupon_keep = frozenset(Coupon.__table__.columns.keys())

    tenants = [
        dt.clean_row(col_types, dt.TID_TENANTS, r, json_cols=dt.TENANT_JSON, keep=tenant_keep)
        for r in tenants_raw
    ]
    plans = [dt.clean_row(col_types, dt.TID_PLANS, r, keep=plan_keep) for r in plans_raw]
    coupons = [dt.clean_row(col_types, dt.TID_COUPONS, r, keep=coupon_keep) for r in coupons_raw]
    return tenants, plans, coupons


async def main() -> None:
    ap = argparse.ArgumentParser(description="n8n DataTable -> Postgres migráció (read-only forrás)")
    ap.add_argument("--dry-run", action="store_true",
                    help="csak kiírja hány sort töltene; Postgreshez hozzá sem nyúl")
    args = ap.parse_args()

    conn = open_n8n_readonly(N8N_DB_PATH)
    try:
        col_types, tenants_raw, plans_raw, coupons_raw = load_source(conn)
    finally:
        conn.close()

    tenants, plans, coupons = coerce_all(col_types, tenants_raw, plans_raw, coupons_raw)

    if args.dry_run:
        print("DRY-RUN — semmit nem írok Postgresbe. Betöltendő sorok:")
        print(f"  tenants: {len(tenants)}")
        print(f"  plans:   {len(plans)}")
        print(f"  coupons: {len(coupons)}")
        print(f"forrás: {N8N_DB_PATH} (read-only)")
        return

    engine = create_async_engine(DB_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        await upsert_on_conflict(s, Plan, plans, pk="plan")
        await upsert_on_conflict(s, Tenant, tenants, pk="client_id")
        # coupons: nincs természetes kulcs (id autoincrement) -> teljes csere
        await replace_all(s, Coupon, coupons)
        await s.commit()
    await engine.dispose()

    print(f"migrated: {len(plans)} plans, {len(tenants)} tenants, {len(coupons)} coupons")
    print(f"forrás: {N8N_DB_PATH} (read-only) -> {DB_URL.rsplit('@', 1)[-1]}")


if __name__ == "__main__":
    asyncio.run(main())

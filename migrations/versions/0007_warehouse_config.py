"""tenants.warehouse_config — Shoprenter raktár-szemantika (m24)

Revision ID: 0007_warehouse_config
Revises: 0006_events
Create Date: 2026-07-05

Séma: {"own": "2", "external": "3", "own_delivery": "2 munkanap",
       "external_delivery": "4-5 munkanap"} — az own/external vesszővel
elválasztott raktár-sorszámok (1..4). A bot a készletet e szerint bontja
("saját raktáron / külső raktáron ... szállítás: ...") az élő lookupban
és a nightly sync termékszövegben.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_warehouse_config"
down_revision = "0006_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("warehouse_config", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "warehouse_config")

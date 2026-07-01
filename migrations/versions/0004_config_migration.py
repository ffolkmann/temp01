"""tenants.launcher_anim + tenants.use_fastapi (config-migráció, doc 12)

Revision ID: 0004_config_migration
Revises: 0003_stats_usage
Create Date: 2026-07-01

launcher_anim: a bubble-animáció (none/ring/float/glow/ring_float) — a config DataTable 28. oszlopa,
a widget contract elvárja, az admin állítja. use_fastapi: chat-routing flag (chat_api_base) —
PG-only (a DataTable-ben nincs), default true; a migrate_from_n8n nem írja felül.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_config_migration"
down_revision = "0003_stats_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("launcher_anim", sa.String(), nullable=True))
    op.add_column(
        "tenants",
        sa.Column("use_fastapi", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("tenants", "use_fastapi")
    op.drop_column("tenants", "launcher_anim")

"""fast_sync_minutes default 1440 (napi) + NULL-backfill

Revision ID: 0002_fast_sync_default
Revises: 0001_initial
Create Date: 2026-06-30

A pricestock (--pricestock) ütemezéséhez a fast_sync_minutes default 1440 perc (napi),
adminból állítható. A meglévő NULL-okat 1440-re töltjük (az explicit értékek — pl. 0=ki,
60=óránként — érintetlenek).
"""

from alembic import op

revision = "0002_fast_sync_default"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tenants", "fast_sync_minutes", server_default="1440")
    op.execute("UPDATE tenants SET fast_sync_minutes = 1440 WHERE fast_sync_minutes IS NULL")


def downgrade() -> None:
    op.alter_column("tenants", "fast_sync_minutes", server_default=None)

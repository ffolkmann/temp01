"""tenants.launcher_config — animalt chat-gomb (launcher) beallitasok (m26)

Revision ID: 0009_launcher_config
Revises: 0008_search_fallback
"""

from alembic import op

revision = "0009_launcher_config"
down_revision = "0008_search_fallback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS launcher_config JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS launcher_config")

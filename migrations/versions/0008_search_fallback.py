"""tenants.search_fallback + plans.search_fallback — webshop-kereso fallback (m25)

Revision ID: 0008_search_fallback
Revises: 0007_warehouse_config
Create Date: 2026-07-07

Kapcsolo (tenants) + csomag-kepesseg (plans, pro-tol). A chat gyenge RAG-score-nal
a bolt sajat frontend-keresojet kerdezi, es a talalatokat a prompt-kontextusba adja.
"""

from alembic import op

revision = "0008_search_fallback"
down_revision = "0007_warehouse_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS search_fallback boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS search_fallback boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS search_fallback")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS search_fallback")

"""initial schema — tenants/plans/usage/coupons/leads/unanswered/feedback/sync_jobs

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-28

A séma forrása az app.models.db_models.Base (CLAUDE.md B.rész 3+6). Az initial
migráció a metadata-ból hozza létre a táblákat, hogy ne csússzon szét a modellel.
"""

from alembic import op

from app.models.db_models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

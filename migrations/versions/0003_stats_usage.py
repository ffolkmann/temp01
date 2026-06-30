"""usage.messages + unanswered.score/reasons (stat-migráció)

Revision ID: 0003_stats_usage
Revises: 0002_fast_sync_default
Create Date: 2026-06-30

A /stats endpointhoz: usage.messages (user-üzenet számláló) + az unanswered score/reasons
(retrieval top score + okok: low_score/collect_lead/order_form). A usage unique(client_id,period)
már megvan (uq_usage_client_period) -> az ON CONFLICT erre megy.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_stats_usage"
down_revision = "0002_fast_sync_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usage", sa.Column("messages", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("unanswered", sa.Column("score", sa.Float(), nullable=True))
    op.add_column("unanswered", sa.Column("reasons", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("unanswered", "reasons")
    op.drop_column("unanswered", "score")
    op.drop_column("usage", "messages")

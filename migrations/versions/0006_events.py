"""events tábla — esemény-számlálók (m22)

Revision ID: 0006_events
Revises: 0005_messages
Create Date: 2026-07-03

Fajták: link_click / product_rec / order_lookup / handoff / configurator.
A /stats kártyák (Termékajánlás, Rendelés-státusz, Kattintott linkek, Élő segítség,
Konfigurátor) és a top-kattintott-linkek lista forrása.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_events"
down_revision = "0005_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("ix_events_client_kind", "events", ["client_id", "kind"])
    op.create_index("ix_events_created_at", "events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_index("ix_events_client_kind", table_name="events")
    op.drop_table("events")

"""messages tábla — beszélgetés-napló (m22)

Revision ID: 0005_messages
Revises: 0004_config_migration
Create Date: 2026-07-03

Minden /chat üzenet-turn (kérdés+válasz) session szerint. Forrása a stat.html
beszélgetés-visszanézőnek (/stats/conversation) és az e-mail átiratoknak.
Retention: 30 nap (scripts/purge_messages.py, nightly) — az ix_messages_created_at
a purge-höz, az ix_messages_client_session a lekérdezéshez.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_messages"
down_revision = "0004_config_migration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("ix_messages_client_session", "messages", ["client_id", "session_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_index("ix_messages_client_session", table_name="messages")
    op.drop_table("messages")

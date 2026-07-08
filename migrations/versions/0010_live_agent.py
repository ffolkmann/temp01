"""élő operátor-átvétel (live agent takeover) — chat_sessions + chat_messages + 4 tenant-oszlop (m28)

Revision ID: 0010_live_agent
Revises: 0009_launcher_config
Create Date: 2026-07-08

Idempotens (0008/0009 mintájára): IF NOT EXISTS mindenhol, hogy a 0007-en ragadt
alembic_version marker melletti drift is biztonságosan felzárkózzon.
- tenants: live_agent_enabled, handoff_bot_silent, operator_hours, operator_telegram_chat_id
- chat_sessions: session-állapotgép (bot/requested/operator/closed)
- chat_messages: sender-bontású üzenet-napló (user/bot/operator/system) az operátor-chatnek
"""

from alembic import op

revision = "0010_live_agent"
down_revision = "0009_launcher_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tenant-kapcsolók / beállítások ---
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS live_agent_enabled boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS handoff_bot_silent boolean NOT NULL DEFAULT true")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS operator_hours JSONB")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS operator_telegram_chat_id varchar")

    # --- session-állapotgép ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id   varchar PRIMARY KEY,
            client_id    varchar NOT NULL,
            state        varchar NOT NULL DEFAULT 'bot',
            claimed_by   varchar,
            requested_at timestamptz,
            claimed_at   timestamptz,
            closed_at    timestamptz,
            last_user_at timestamptz,
            last_op_at   timestamptz
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_sessions_client ON chat_sessions (client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_sessions_state ON chat_sessions (state)")

    # --- sender-bontású üzenet-napló ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id         bigserial PRIMARY KEY,
            client_id  varchar NOT NULL,
            session_id varchar,
            sender     varchar NOT NULL,
            text       text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_messages_conv ON chat_messages (client_id, session_id, id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_messages")
    op.execute("DROP TABLE IF EXISTS chat_sessions")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS operator_telegram_chat_id")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS operator_hours")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS handoff_bot_silent")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS live_agent_enabled")

"""m31: tenants.operator_bot_token — per-tenant Telegram bot.

Eddig MINDEN tenant értesítése a központi „CX notify (Telegram)" n8n-workflow
webhookján ment, vagyis ugyanazon a boton, amelyik egyben az „Anna" személyi
asszisztens is. Külső ügyfél ügyintézője így az én asszisztensem botjától kapta
volna a pinget.

Ha a tenantnak van saját bot tokenje, a backend KÖZVETLENÜL a Telegram Bot API-t
hívja (`https://api.telegram.org/bot<token>/sendMessage`), n8n nélkül. Ha nincs,
marad a mai központi út (visszafelé kompatibilis, semmit nem kell átállítani).

A token a BotFathertől jön (@BotFather -> /newbot). Az ügyintézőnek egyszer rá
kell nyomnia a /start-ra a saját botnál, különben a Telegram nem kézbesít.

Revision ID: 0013_operator_bot_token
Revises: 0012_operator_token
"""

from alembic import op

revision = "0013_operator_bot_token"
down_revision = "0012_operator_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS operator_bot_token VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS operator_bot_token")

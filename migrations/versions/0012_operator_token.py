"""m30: tenants.operator_token — per-tenant operátor-konzol token.

Eddig az /operator/* végpontok az ADMIN_PANEL_TOKEN-t fogadták el, vagyis az
operátor-konzol tokenje egyben az admin-panel tokenje volt, és a várólista
MINDEN tenant beszélgetését mutatta. Külső ügyfélnek (pl. Global-Tender)
átadva ez adatvédelmi incidens: látná a többi webshop vevőinek chatjeit, és
hozzáférne az admin-panelhez (benne a többi tenant API-kulcsaival).

Innentől:
  - ADMIN_PANEL_TOKEN  -> master hatókör (minden tenant), változatlan
  - tenants.operator_token -> CSAK az adott tenant sorai (queue + conversation +
    claim + send + close), és a presence is tenantonként külön kulcson megy.

A tokent a mentés generálja, ha a tenantnál az élő átvétel be van kapcsolva és
még nincs token (a stat_key mintájára). Egyediség: unique index.

Revision ID: 0012_operator_token
Revises: 0011_order_status_map
"""

from alembic import op

revision = "0012_operator_token"
down_revision = "0011_order_status_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS operator_token VARCHAR")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_operator_token "
        "ON tenants (operator_token) WHERE operator_token IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenants_operator_token")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS operator_token")

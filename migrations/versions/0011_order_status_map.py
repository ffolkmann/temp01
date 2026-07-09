"""m29: tenants.order_status_map — platform-kód -> magyar megnevezés szótár.

A Webdoc (WebDoc API v1.1) csak numerikus kódokat ad vissza a rendelés
státuszára, a szállítási és a fizetési módra. A megnevezéseket ebből a
JSONB-ből oldjuk fel; ami itt nincs, arra a kódbeli DEFAULT_STATUS_MAP ugrik be
(app/services/webdoc_status.py).

Alak:
  {
    "status":       {"1": "Rendelés megérkezett", ...},
    "shipping":     {"1": "Házhozszállítás", ...},
    "payment":      {"1": "Utánvét (készpénz)", ...},
    "payment_paid": {"0": "nincs fizetve", "1": "fizetve"}
  }

A mező szándékosan NEM webdoc-specifikus: bármely platform használhatja, ahol a
rendelés-API kódot ad név helyett.

Revision ID: 0011_order_status_map
Revises: 0010_live_agent
"""

from alembic import op

revision = "0011_order_status_map"
down_revision = "0010_live_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS order_status_map JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS order_status_map")

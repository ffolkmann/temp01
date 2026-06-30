"""Platform-adapterek: BULK fetch (platform_api) -> builder (byte-paritás) -> list[SourceProduct].

A fetch a platform_api bulk-lekérő függvényeit hívja; a text/payload-összeállítás a
builders.py-ben van (a reference/n8n-sync/ node-okkal byte-egyezve). Hibánál a fetch DOB ->
az engine skippeli a tenantot (NEM purge-öl).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services import platform_api as pa
from app.sync.builders import build_sellvio, build_shoprenter, build_unas, build_woo

if TYPE_CHECKING:
    from app.models.db_models import Tenant


def _creds(tenant):
    return (
        str(tenant.api_base or "").strip(),
        str(tenant.api_client_id or "").strip(),
        str(tenant.api_client_secret or "").strip(),
        str(tenant.public_url or "").strip(),
    )


async def fetch_sellvio(tenant: "Tenant"):
    base, cid, sec, _ = _creds(tenant)
    rows = await pa.sellvio_list_products(base, cid, sec)
    return build_sellvio(rows, tenant.client_id)


async def fetch_woo(tenant: "Tenant"):
    base, ck, cs, _ = _creds(tenant)
    rows = await pa.woo_list_products(base, ck, cs)
    return build_woo(rows, tenant.client_id)


async def fetch_shoprenter(tenant: "Tenant"):
    base, cid, sec, pub = _creds(tenant)
    items = await pa.shoprenter_list_products(base, cid, sec)
    return build_shoprenter(items, tenant.client_id, pub)


async def fetch_unas(tenant: "Tenant"):
    _, cid, sec, pub = _creds(tenant)
    api_key = sec or cid
    csv_text = await pa.unas_export_csv(api_key)
    return build_unas(csv_text, tenant.client_id, pub)


PLATFORM_FETCHERS = {
    "sellvio": fetch_sellvio,
    "woocommerce": fetch_woo,
    "shoprenter": fetch_shoprenter,
    "unas": fetch_unas,
}

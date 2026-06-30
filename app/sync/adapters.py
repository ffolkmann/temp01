"""Platform-adapterek: BULK raw termék -> normalizált SourceProduct.

A fetch (platform_api bulk-list) + a normalizálás (raw -> SourceProduct) van itt; a hash/text/
payload a models.py-ben, a delta az engine.py-ben. Tenant->platform a tenants.platform alapján.

FLAG (paritás): a mező-leképezés (különösen a `text`/szemantikus mezők) a Sync workflow "Build
Product Points" Code node-jaihoz igazítandó (VPS-től kérendő) — addig ésszerű best-effort.
Hibánál a fetch DOB -> az engine skippeli a tenantot (NEM purge-öl).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element

from app.services import platform_api as pa
from app.sync.models import SourceProduct, scalar_price

if TYPE_CHECKING:
    from app.models.db_models import Tenant

logger = logging.getLogger("cx.sync.adapt")


def _s(v) -> str:
    return "" if v is None else str(v)


# --- Sellvio ----------------------------------------------------------------
def _norm_sellvio(raw: dict) -> SourceProduct:
    return SourceProduct(
        sku=_s(raw.get("sku")),
        name=_s(raw.get("name")),
        url=_s(raw.get("url") or raw.get("link")),
        price=scalar_price(raw.get("price")),
        brand=_s(raw.get("brand") or raw.get("manufacturer")),
        category=_s(raw.get("category")),
        description=_s(raw.get("description") or raw.get("short_description")),
        available=raw.get("is_available_for_order"),
        platform_id_field="sellvio_id",
        platform_id_value=_s(raw.get("id")),
    )


async def fetch_sellvio(tenant: "Tenant") -> list[SourceProduct]:
    raws = await pa.sellvio_list_products(
        str(tenant.api_base or ""), str(tenant.api_client_id or ""), str(tenant.api_client_secret or "")
    )
    return [_norm_sellvio(r) for r in raws if r.get("sku")]


# --- WooCommerce ------------------------------------------------------------
def _norm_woo(raw: dict) -> SourceProduct:
    cats = raw.get("categories") or []
    category = ", ".join(c.get("name", "") for c in cats if isinstance(c, dict)) if isinstance(cats, list) else ""
    price = scalar_price(raw.get("price")) or scalar_price(raw.get("regular_price"))
    ss = str(raw.get("stock_status") or "").lower()
    return SourceProduct(
        sku=_s(raw.get("sku")),
        name=_s(raw.get("name")),
        url=_s(raw.get("permalink")),
        price=price,
        brand="",  # WC márka attribútumból jönne — best-effort kihagyva
        category=category,
        description=_s(raw.get("short_description") or raw.get("description")),
        stock=raw.get("stock_quantity") if isinstance(raw.get("stock_quantity"), int) else None,
        available=(ss in ("instock", "onbackorder")) if ss else None,
        platform_id_field="wc_id",
        platform_id_value=_s(raw.get("id")),
    )


async def fetch_woo(tenant: "Tenant") -> list[SourceProduct]:
    raws = await pa.woo_list_products(
        str(tenant.api_base or ""), str(tenant.api_client_id or ""), str(tenant.api_client_secret or "")
    )
    # WC sku üres lehet -> a wc_id az azonosító; sync-kulcs viszont a sku (deduplikál) -> wc_id fallback
    out: list[SourceProduct] = []
    for r in raws:
        p = _norm_woo(r)
        if not p.sku:
            p.sku = p.platform_id_value  # üres WC sku -> wc_id legyen a stabil kulcs
        if p.sku:
            out.append(p)
    return out


# --- Shoprenter (full=1, BARE; Product/Description/Extend nested) ------------
def _norm_shoprenter(raw: dict) -> SourceProduct:
    desc = raw.get("description") if isinstance(raw.get("description"), dict) else {}
    # a full=1 lokalizált Description-tömböt/objektumot adhat; best-effort name/leírás
    name = _s(raw.get("name") or (desc.get("name") if isinstance(desc, dict) else ""))
    url = _s(raw.get("url") or (desc.get("url") if isinstance(desc, dict) else ""))
    body = _s(desc.get("description") if isinstance(desc, dict) else "")
    stock1 = raw.get("stock1")
    return SourceProduct(
        sku=_s(raw.get("sku")),
        name=name,
        url=url,
        price=scalar_price(raw.get("price")),
        brand=_s(raw.get("manufacturer") or raw.get("brand")),
        description=body,
        stock=int(float(stock1)) if stock1 not in (None, "") and _isnum(stock1) else None,
        platform_id_field="",  # SR: nincs id a payloadban (csak sku)
        platform_id_value="",
    )


async def fetch_shoprenter(tenant: "Tenant") -> list[SourceProduct]:
    raws = await pa.shoprenter_list_products(
        str(tenant.api_base or ""), str(tenant.api_client_id or ""), str(tenant.api_client_secret or "")
    )
    return [_norm_shoprenter(r) for r in raws if r.get("sku")]


# --- Unas (getProductDB -> <Product> elemek) --------------------------------
def _x(el: Element, *names: str) -> str:
    from app.services.platform_api import xml_first_text
    return xml_first_text(el, *names)


def _unas_price(prod: Element) -> str:
    prices = prod.find(".//Prices")
    if prices is None:
        return ""
    chosen = normal = None
    for pr in prices.findall("Price"):
        if (pr.findtext("Actual") or "").strip() == "1":
            chosen = pr
            break
        if (pr.findtext("Type") or "").strip().lower() == "normal" and normal is None:
            normal = pr
    pr = chosen or normal
    if pr is None:
        return ""
    return (pr.findtext("Gross") or "").strip() or (pr.findtext("Net") or "").strip()


def _norm_unas(prod: Element) -> SourceProduct:
    qty = _x(prod, "Qty")
    return SourceProduct(
        sku=_x(prod, "Sku"),
        name=_x(prod, "Name"),
        url=_x(prod, "Url"),
        price=_unas_price(prod),
        brand=_x(prod, "Manufacturer", "Brand"),
        description=_x(prod, "Description"),
        stock=int(float(qty)) if qty and _isnum(qty) else None,
        platform_id_field="",  # Unas: nincs id a payloadban (csak sku)
        platform_id_value="",
    )


async def fetch_unas(tenant: "Tenant") -> list[SourceProduct]:
    api_key = str(tenant.api_client_secret or "").strip() or str(tenant.api_client_id or "").strip()
    prods = await pa.unas_list_products(api_key)
    return [_norm_unas(p) for p in prods if _x(p, "Sku")]


def _isnum(v) -> bool:
    try:
        float(str(v))
        return True
    except (TypeError, ValueError):
        return False


PLATFORM_FETCHERS = {
    "sellvio": fetch_sellvio,
    "woocommerce": fetch_woo,
    "shoprenter": fetch_shoprenter,
    "unas": fetch_unas,
}

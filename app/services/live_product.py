"""Élő ár/készlet (current-product real-time) — a prod chat-workflow 'Has Live API?'=true
current-product ár/készlet ágának portja (az utolsó kihagyott Fázis-3 ág).

Termékoldalon (page_url-horgony) a megnyitott termékre élő API-lekérés platform szerint
(Sellvio/Shoprenter/Unas/WooCommerce); az eredmény a prompt # ELO, FRISS AR, KESZLET
blokkjába kerül a synced (Qdrant) érték HELYETT.

Azonosító: a Qdrant product-payloadból a platform termék-id (teslashop seed: 'sellvio_id'),
fallback 'sku'. plan.live_api-gated (a hívó chat.py dönt).

FAIL-SAFE: bármely hiba/timeout/üres -> None; a hívó a synced adatlapot hagyja, a chat
SOHA nem törik. A price/stock MEZŐNEVEK per platform Fecó VPS-visszaigazolására várnak
(mint az order-statusnál) — a kinyerés ezért több jelölt-mezőt próbál, defenzíven.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import httpx

from app.services.platform_api import (
    UNAS_BASE,
    sellvio_token,
    shoprenter_resource_id,
    shoprenter_shop,
    shoprenter_token,
    unas_login,
    xml_first_text,
    xml_root,
)

if TYPE_CHECKING:
    from app.models.db_models import Tenant
    from app.services.current_product import CurrentProduct

logger = logging.getLogger("cx.live")


@dataclass
class LivePriceStock:
    price: str = ""              # nyers ár string (ahogy a platform adja) vagy ""
    available: bool | None = None
    qty: int | None = None
    name: str = ""

    def has_data(self) -> bool:
        return bool(self.price) or self.available is not None or self.qty is not None


# a Qdrant payload platform-id mezői (teslashop seed: sellvio_id + sku); sku a fallback
_ID_FIELDS = {
    "sellvio": ("sellvio_id",),
    "shoprenter": ("shoprenter_id",),
    "unas": ("unas_id",),
    "woocommerce": ("woo_id", "wc_id", "woocommerce_id", "id"),
}


def _product_id(payload: dict, platform: str) -> str:
    for k in _ID_FIELDS.get(platform, ()):
        v = payload.get(k)
        if v not in (None, ""):
            return str(v)
    return str(payload.get("sku") or "")


def _to_int(v) -> int | None:
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return None


def _scalar_price(v) -> str:
    """price -> string; dict esetén próbál gross/amount/value/price; különben ''."""
    if isinstance(v, dict):
        for k in ("gross", "amount", "value", "price"):
            inner = v.get(k)
            if isinstance(inner, (str, int, float)):
                return str(inner)
        return ""
    if isinstance(v, (str, int, float)):
        return str(v)
    return ""


def _avail_from(available, qty: int | None) -> bool | None:
    if isinstance(available, bool):
        return available
    if qty is not None:
        return qty > 0
    return None


# --- Sellvio: GET /api/v2/products/{id} -------------------------------------
async def _sellvio_live(tenant: "Tenant", pid: str) -> LivePriceStock | None:
    api_base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    secret = str(tenant.api_client_secret or "").strip()
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        token = await sellvio_token(client, api_base, cid, secret)
        if not token:
            return None
        resp = await client.get(
            f"{api_base}/api/v2/products/{pid}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
    o = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else body
    if not isinstance(o, dict):
        return None
    qty = _to_int(o.get("stock") if o.get("stock") is not None else o.get("quantity"))
    return LivePriceStock(
        price=_scalar_price(o.get("price")),
        available=_avail_from(o.get("available"), qty),
        qty=qty,
        name=str(o.get("name") or ""),
    )


# --- WooCommerce: GET /wp-json/wc/v3/products/{id} --------------------------
async def _woo_live(tenant: "Tenant", pid: str) -> LivePriceStock | None:
    base = str(tenant.api_base or "").strip().rstrip("/")
    ck = str(tenant.api_client_id or "").strip()
    cs = str(tenant.api_client_secret or "").strip()
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(
            f"{base}/wp-json/wc/v3/products/{pid}",
            auth=(ck, cs),
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        o = resp.json()
    if not isinstance(o, dict) or not o.get("id"):
        return None
    ss = str(o.get("stock_status") or "").lower()
    avail = (ss in ("instock", "onbackorder")) if ss else None
    return LivePriceStock(
        price=_scalar_price(o.get("price")),
        available=avail,
        qty=_to_int(o.get("stock_quantity")),
        name=str(o.get("name") or ""),
    )


# --- Shoprenter: GET {api_base}/products/{base64('product-product_id=<N>')} --
async def _shoprenter_live(tenant: "Tenant", pid: str) -> LivePriceStock | None:
    api_base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    secret = str(tenant.api_client_secret or "").strip()
    shop = shoprenter_shop(api_base)
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        token = await shoprenter_token(client, shop, cid, secret)
        if not token:
            return None
        resp = await client.get(
            f"{api_base}/products/{shoprenter_resource_id('product', pid)}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    o = data.get("product") if isinstance(data, dict) and isinstance(data.get("product"), dict) else data
    if not isinstance(o, dict):
        return None
    qty = _to_int(o.get("stock1") if o.get("stock1") is not None else o.get("quantity"))
    return LivePriceStock(
        price=_scalar_price(o.get("price")),
        available=_avail_from(o.get("available"), qty),
        qty=qty,
        name=str(o.get("name") or ""),
    )


# --- Unas: login -> POST /getProduct XML ------------------------------------
async def _unas_live(tenant: "Tenant", pid: str, sku: str) -> LivePriceStock | None:
    api_key = str(tenant.api_client_secret or "").strip() or str(tenant.api_client_id or "").strip()
    key = pid or sku
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        token = await unas_login(client, api_key)
        if not token:
            return None
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<Params><Sku>{escape(key)}</Sku></Params>"
        )
        resp = await client.post(
            f"{UNAS_BASE}/getProduct",
            content=body.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
        )
        resp.raise_for_status()
        root = xml_root(resp.text)
    if root is None:
        return None
    prod = root.find(".//Product")
    if prod is None:
        return None
    qty = _to_int(xml_first_text(prod, "Stock", "Quantity"))
    return LivePriceStock(
        price=xml_first_text(prod, "Price", "PriceGross", "Net"),
        available=_avail_from(None, qty),
        qty=qty,
        name=xml_first_text(prod, "Name"),
    )


_LIVE = {
    "sellvio": lambda t, pid, sku: _sellvio_live(t, pid or sku),
    "woocommerce": lambda t, pid, sku: _woo_live(t, pid or sku),
    "shoprenter": lambda t, pid, sku: _shoprenter_live(t, pid or sku),
    "unas": lambda t, pid, sku: _unas_live(t, pid, sku),
}


async def fetch_live_price_stock(tenant: "Tenant", current: "CurrentProduct") -> LivePriceStock | None:
    """A megnyitott termék élő ára/készlete a platform API-ról. FAIL-SAFE: None hibánál.

    A hívó (chat.py) gateli plan.live_api-val és csak termékoldalon hívja.
    """
    platform = str(tenant.platform or "").strip().lower()
    fn = _LIVE.get(platform)
    if fn is None:
        return None
    payload = getattr(current, "payload", None) or {}
    pid = _product_id(payload, platform)
    sku = str(payload.get("sku") or "")
    if not pid and not sku:
        logger.info("LIVE[%s] nincs termék-azonosító a payloadban — synced marad", tenant.client_id)
        return None
    try:
        live = await fn(tenant, pid, sku)
    except Exception:  # noqa: BLE001 — élő lekérés hibája SOHA ne törje a /chat-et
        logger.exception(
            "LIVE[%s] %s ár/készlet lekérés hiba (id=%s) — synced marad",
            tenant.client_id, platform, pid or sku,
        )
        return None
    if live is None or not live.has_data():
        return None
    logger.info("LIVE[%s] %s élő ár/készlet OK (id=%s)", tenant.client_id, platform, pid or sku)
    return live

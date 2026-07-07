"""Élő ár/készlet (current-product real-time) — a prod chat-workflow 'Has Live API?'=true
current-product ár/készlet ágának portja (az utolsó kihagyott Fázis-3 ág).

Termékoldalon (page_url-horgony) a megnyitott termékre élő API-lekérés platform szerint;
az eredmény a prompt # ELO, FRISS AR, KESZLET blokkjába kerül a synced (Qdrant) érték HELYETT.

Azonosító + kontraktusok VPS-en igazolva (valós Qdrant payload + válasz):
 - Sellvio:     payload sellvio_id -> GET /api/v2/products/{id}; data.price DICT
                ({netto_price,vat,brutto_price,discount}) -> brutto_price; készlet-DB NINCS,
                csak is_available_for_order (bool).
 - WooCommerce: payload wc_id (NEM woo_id; a sku üres lehet) -> GET /products/{wc_id};
                ár price/regular_price/sale_price, készlet stock_quantity + stock_status.
 - Shoprenter:  payload-ban NINCS id -> GET /products?sku=<sku>&full=1 (items[0]); készlet=stock1..stock4 összege
                (a quantity aggregátum megbízhatatlan), orderable(0/1). Az ÁR SYNCED marad (net/gross
                bizonytalan a SR-nél) -> csak a készlet megy élőben.
 - Unas:        payload-ban NINCS id -> getProduct <Sku>; ár Prices/Price[Actual=1]/Gross
                (fallback normal Price Gross), készlet Stocks/Stock/Qty.

plan.live_api-gated (a hívó chat.py dönt). FAIL-SAFE: bármely hiba/timeout/hiányzó mező ->
None; a hívó a synced adatlapot hagyja, a chat SOHA nem törik.
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
    note: str = ""  # m24: raktár-szemantika (saját/külső raktár, szállítási idő)

    def has_data(self) -> bool:
        return bool(self.price) or self.available is not None or self.qty is not None


# a Qdrant payload platform-id mezői (VPS-en igazolva); ahol nincs, a sku a kulcs
_ID_FIELDS = {
    "sellvio": ("sellvio_id",),
    "woocommerce": ("wc_id",),   # NEM woo_id; a WC sku üres lehet
    "shoprenter": (),            # nincs id -> sku (?sku= szűrő)
    "unas": (),                  # nincs id -> sku (getProduct <Sku>)
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
    """price -> string; dict esetén brutto_price/netto_price (Sellvio), majd gross/amount/value."""
    if isinstance(v, dict):
        for k in ("brutto_price", "netto_price", "gross", "amount", "value", "price"):
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


# --- Sellvio: GET /api/v2/products/{sellvio_id} -----------------------------
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
    # ár: data.price dict -> brutto_price (fallback netto_price). Készlet-DB nincs, csak elérhetőség.
    return LivePriceStock(
        price=_scalar_price(o.get("price")),
        available=_avail_from(o.get("is_available_for_order"), None),
        qty=None,
        name=str(o.get("name") or ""),
    )


# --- WooCommerce: GET /wp-json/wc/v3/products/{wc_id} -----------------------
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
    price = _scalar_price(o.get("price")) or _scalar_price(o.get("regular_price")) or _scalar_price(o.get("sale_price"))
    ss = str(o.get("stock_status") or "").lower()
    avail = (ss in ("instock", "onbackorder")) if ss else None
    return LivePriceStock(
        price=price,
        available=avail,
        qty=_to_int(o.get("stock_quantity")),
        name=str(o.get("name") or ""),
    )


# --- Shoprenter: GET /products?sku=<sku>&full=1 (csak készlet élőben) -------
async def _shoprenter_live(tenant: "Tenant", sku: str) -> LivePriceStock | None:
    if not sku:
        return None
    api_base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    secret = str(tenant.api_client_secret or "").strip()
    shop = shoprenter_shop(api_base)
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        token = await shoprenter_token(client, shop, cid, secret)
        if not token:
            return None
        resp = await client.get(
            f"{api_base}/products",
            params={"sku": sku, "full": "1"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items") if isinstance(data, dict) else None
    o = items[0] if isinstance(items, list) and items else None
    if not isinstance(o, dict):
        return None
    # m24: stock1..stock4 OSSZEGE (tobb-raktaras shopnal a keszlet nem feltetlen a
    # stock1-ben van - FO 12550-013: stock1=0, stock2=6; a quantity aggregatum megbizhatatlan)
    qty = None
    for k in ("stock1", "stock2", "stock3", "stock4"):
        v = _to_int(o.get(k))
        if v is not None:
            qty = (qty or 0) + v
    ordv = _to_int(o.get("orderable"))
    avail = (ordv > 0) if ordv is not None else (qty > 0 if qty is not None else None)
    # ár SYNCED marad (net/gross bizonytalan a SR-nél) -> price=""
    from app.sync.builders import sr_warehouse_note  # lazy: körimport-mentes
    _, note = sr_warehouse_note(o, getattr(tenant, "warehouse_config", None))
    return LivePriceStock(price="", available=avail, qty=qty, name=str(o.get("name") or ""), note=note)


# --- Unas: login -> getProduct <Sku> ----------------------------------------
def _unas_price(prod) -> str:
    """Prices/Price[Actual=1]/Gross (fallback normal típusú Price Gross), majd Net."""
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


def _unas_qty(prod) -> int | None:
    """Készlet a WarehouseId-NÉLKÜLI fej-<Stock>/<Qty>-ból (sorrend-független, multi-raktár).

    Fallback az első Qty bárhol (a korábbi, élesben igazolt viselkedés) — így sosem rosszabb.
    """
    stocks = prod.find(".//Stocks")
    if stocks is not None:
        for st in stocks.findall("Stock"):
            if st.find("WarehouseId") is None:          # fej-szintű aggregát készlet
                q = st.findtext("Qty")
                if q is not None and q.strip():
                    return _to_int(q)
    return _to_int(xml_first_text(prod, "Qty"))


_UNAS_WH_CACHE: dict[str, tuple[float, dict[str, tuple[str, str]]]] = {}
_UNAS_WH_TTL = 3600.0


async def _unas_warehouses(client, token: str, api_key: str) -> dict[str, tuple[str, str]]:
    """Aktiv Unas raktarak: {id: (public_name, info)} — 1 oras cache-sel."""
    import time as _t
    hit = _UNAS_WH_CACHE.get(api_key)
    if hit and _t.monotonic() - hit[0] < _UNAS_WH_TTL:
        return hit[1]
    out: dict[str, tuple[str, str]] = {}
    try:
        resp = await client.post(
            f"{UNAS_BASE}/getWarehouse",
            content='<?xml version="1.0" encoding="UTF-8"?><Params></Params>'.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
        )
        resp.raise_for_status()
        root = xml_root(resp.text)
        for wh in (root.findall(".//Warehouse") if root is not None else []):
            if (wh.findtext("Active") or "").strip().lower() != "yes":
                continue
            wid = (wh.findtext("Id") or "").strip()
            if not wid:
                continue
            name = (wh.findtext("PublicName") or "").strip() or (wh.findtext("Name") or "").strip()
            info = (wh.findtext("Info") or "").strip()
            out[wid] = (name or f"raktár {wid}", info)
    except Exception:  # noqa: BLE001 — a raktarlista hibaja ne torje a live-t
        out = {}
    _UNAS_WH_CACHE[api_key] = (_t.monotonic(), out)
    return out


def _unas_wh_note(prod, whmap: dict[str, tuple[str, str]], warehouse_config) -> str:
    """Raktarankenti keszlet-note a getProduct <Stocks>-bol.

    Csak IsActive=yes stock, csak aktiv (whmap-ban levo) raktar, csak Qty>0.
    A tenants.warehouse_config opcionalis felulirot ad: {wh_id: {"name":..,"delivery":..}} vagy {wh_id: "nev"}.
    """
    stocks = prod.find(".//Stocks")
    if stocks is None:
        return ""
    wc = warehouse_config if isinstance(warehouse_config, dict) else {}
    parts: list[str] = []
    for st in stocks.findall("Stock"):
        wid = (st.findtext("WarehouseId") or "").strip()
        if not wid:
            continue  # fej-keszlet — a qty mezoben mar szerepel
        if (st.findtext("IsActive") or "").strip().lower() == "no":
            continue
        if wid not in whmap:
            continue  # inaktiv/ismeretlen raktar
        q = _to_int(st.findtext("Qty"))
        if not q or q <= 0:
            continue
        name, info = whmap[wid]
        ov = wc.get(wid) or wc.get(str(wid))
        if isinstance(ov, dict):
            name = str(ov.get("name") or name)
            info = str(ov.get("delivery") or info)
        elif isinstance(ov, str) and ov.strip():
            name = ov.strip()
        seg = f"{name}: {q} db"
        if info and info.lower() not in name.lower():
            seg += f" ({info})"
        parts.append(seg)
    if not parts:
        return ""
    return "Raktáranként: " + "; ".join(parts) + ". A szállítási idő a raktártól függ."


async def _unas_live(tenant: "Tenant", sku: str) -> LivePriceStock | None:
    if not sku:
        return None
    api_key = str(tenant.api_client_secret or "").strip() or str(tenant.api_client_id or "").strip()
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        token = await unas_login(client, api_key)
        if not token:
            return None
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<Params><Sku>{escape(sku)}</Sku></Params>"
        )
        resp = await client.post(
            f"{UNAS_BASE}/getProduct",
            content=body.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
        )
        resp.raise_for_status()
        root = xml_root(resp.text)
        prod = root.find(".//Product") if root is not None else None
        _wh_note = ""
        if prod is not None:
            try:
                _whmap = await _unas_warehouses(client, token, api_key)
                _wh_note = _unas_wh_note(prod, _whmap, getattr(tenant, "warehouse_config", None))
            except Exception:  # noqa: BLE001 — raktar-note hibaja ne torje a live-t
                _wh_note = ""
    if root is None or prod is None:
        return None
    qty = _unas_qty(prod)                             # fej-<Stock>/Qty (sorrend-független)
    return LivePriceStock(
        price=_unas_price(prod),
        available=_avail_from(None, qty),
        qty=qty,
        name=xml_first_text(prod, "Name"),
        note=_wh_note,
    )


_LIVE = {
    "sellvio": lambda t, pid, sku: _sellvio_live(t, pid or sku),
    "woocommerce": lambda t, pid, sku: _woo_live(t, pid or sku),
    "shoprenter": lambda t, pid, sku: _shoprenter_live(t, sku),
    "unas": lambda t, pid, sku: _unas_live(t, sku),
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

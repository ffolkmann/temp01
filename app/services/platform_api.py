"""Platform API közös primitívek (auth/token, XML, e-mail-normalizálás).

Az order-status (order_status.py) ÉS az élő ár/készlet (live_product.py) ág is ezt
osztja — az auth EGY helyen él, hogy ne drifteljen szét. A platform-specifikus
lekérdező-logika a hívó modulokban marad.
"""

import base64
import logging
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("cx.platform")

UNAS_BASE = "https://api.unas.eu/shop"

# bulk-fetch biztonsági korlátok
_MAX_PAGES = 2000
_LIST_TIMEOUT = 60.0


def norm_email(s: str | None) -> str:
    return str(s or "").strip().lower()


# --- Sellvio ----------------------------------------------------------------
async def sellvio_token(
    client: httpx.AsyncClient, api_base: str, client_id: str, client_secret: str
) -> str:
    """OAuth client_credentials -> access_token (üres string, ha nincs)."""
    resp = await client.post(
        f"{api_base}/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    return str((resp.json() or {}).get("access_token") or "")


# --- Shoprenter (OAuth2; Basic deprecated -> 403) ---------------------------
def shoprenter_shop(api_base: str) -> str:
    """{shop}.api2.myshoprenter.hu/api/ -> shop"""
    host = urlsplit(api_base).hostname or ""
    return host.split(".")[0] if host else ""


def shoprenter_resource_id(entity: str, value: str) -> str:
    """A Shoprenter resource-id base64('<entity>-<entity>_id=<value>') sémát követ."""
    return base64.b64encode(f"{entity}-{entity}_id={value}".encode()).decode()


async def shoprenter_token(
    client: httpx.AsyncClient, shop: str, client_id: str, client_secret: str
) -> str:
    resp = await client.post(
        f"https://oauth.app.shoprenter.net/{shop}/app/token",
        json={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
    )
    resp.raise_for_status()
    return str((resp.json() or {}).get("access_token") or "")


# --- Unas (login -> token; XML) ---------------------------------------------
def xml_root(text: str) -> ET.Element | None:
    try:
        return ET.fromstring(text or "")
    except ET.ParseError:
        return None


def xml_first_text(el: ET.Element, *local_names: str) -> str:
    """Az első leszármazott elem szövege, aminek a (namespace nélküli) tagje illik."""
    wanted = {n.lower() for n in local_names}
    for sub in el.iter():
        if sub.tag.split("}")[-1].lower() in wanted and sub.text and sub.text.strip():
            return sub.text.strip()
    return ""


async def unas_login(client: httpx.AsyncClient, api_key: str) -> str:
    from xml.sax.saxutils import escape

    body = f'<?xml version="1.0" encoding="UTF-8"?>\n<Params><ApiKey>{escape(api_key)}</ApiKey></Params>'
    resp = await client.post(
        f"{UNAS_BASE}/login",
        content=body.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    resp.raise_for_status()
    root = xml_root(resp.text)
    return xml_first_text(root, "Token") if root is not None else ""


# --------------------------------------------------------------------------- #
# BULK termék-listák (sync) — összes termék / tenant, lapozva
# --------------------------------------------------------------------------- #
async def sellvio_list_products(api_base: str, client_id: str, client_secret: str) -> list[dict]:
    """Sellvio: GET /api/v2/products lapozva (resp data.{items,total}; OAuth2 Bearer)."""
    api_base = api_base.rstrip("/")
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=_LIST_TIMEOUT, follow_redirects=True) as client:
        token = await sellvio_token(client, api_base, client_id, client_secret)
        if not token:
            raise RuntimeError("Sellvio: nincs token")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        total = None
        for page in range(1, _MAX_PAGES + 1):
            r = await client.get(
                f"{api_base}/api/v2/products",
                params={"page": page, "per_page": 100},
                headers=headers,
            )
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            items = data.get("items") or []
            if total is None:
                total = data.get("total")
            out.extend(i for i in items if isinstance(i, dict))
            if not items or (total is not None and len(out) >= int(total)):
                break
    return out


async def shoprenter_list_products(api_base: str, client_id: str, client_secret: str) -> list[dict]:
    """Shoprenter: GET /products?full=1 lapozva pageCount alapján (api2 BARE objektum)."""
    api_base = api_base.rstrip("/")
    shop = shoprenter_shop(api_base)
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=_LIST_TIMEOUT, follow_redirects=True) as client:
        token = await shoprenter_token(client, shop, client_id, client_secret)
        if not token:
            raise RuntimeError("Shoprenter: nincs token")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        page_count = None
        for page in range(1, _MAX_PAGES + 1):
            r = await client.get(
                f"{api_base}/products",
                params={"full": "1", "page": page, "limit": 200},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json() or {}
            items = data.get("items") or []
            if page_count is None:
                page_count = data.get("pageCount") or data.get("pages")
            out.extend(i for i in items if isinstance(i, dict))
            if not items or (page_count is not None and page >= int(page_count)):
                break
    return out


async def woo_list_products(base: str, consumer_key: str, consumer_secret: str) -> list[dict]:
    """WooCommerce: GET /wp-json/wc/v3/products?per_page=100&page=N (Basic ck/cs)."""
    base = base.rstrip("/")
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=_LIST_TIMEOUT, follow_redirects=True) as client:
        for page in range(1, _MAX_PAGES + 1):
            r = await client.get(
                f"{base}/wp-json/wc/v3/products",
                params={"per_page": 100, "page": page},
                auth=(consumer_key, consumer_secret),
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            items = r.json()
            if not isinstance(items, list) or not items:
                break
            out.extend(i for i in items if isinstance(i, dict))
            if len(items) < 100:
                break
    return out


async def unas_list_products(api_key: str) -> list[ET.Element]:
    """Unas: getProductDB bulk export (login -> Bearer). NEM per-sku getProduct.

    A getProductDB jellemzően egy letölthető export-URL-t ad vissza (<Url>); ezt töltjük le és
    parse-oljuk a <Product> elemekre. FLAG: a pontos getProductDB válasz-formátum a Sync workflow
    JSON-ban van — VPS-en igazolandó. Hibánál a hívó (engine) skippel, NEM purge-öl.
    """
    async with httpx.AsyncClient(timeout=_LIST_TIMEOUT, follow_redirects=True) as client:
        token = await unas_login(client, api_key)
        if not token:
            raise RuntimeError("Unas: nincs token")
        body = '<?xml version="1.0" encoding="UTF-8"?>\n<Params><Format>xml</Format></Params>'
        r = await client.post(
            f"{UNAS_BASE}/getProductDB",
            content=body.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
        )
        r.raise_for_status()
        root = xml_root(r.text)
        if root is None:
            raise RuntimeError("Unas getProductDB: nem-XML válasz")
        # 1) export-URL ág (<Url>...</Url>) -> letöltés
        url = xml_first_text(root, "Url")
        if url:
            d = await client.get(url)
            d.raise_for_status()
            root = xml_root(d.text)
            if root is None:
                raise RuntimeError("Unas getProductDB export: nem-XML")
    return list(root.iter("Product"))

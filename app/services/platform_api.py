"""Platform API közös primitívek (auth/token, XML, e-mail-normalizálás).

Az order-status (order_status.py) ÉS az élő ár/készlet (live_product.py) ág is ezt
osztja — az auth EGY helyen él, hogy ne drifteljen szét. A platform-specifikus
lekérdező-logika a hívó modulokban marad.
"""

import asyncio
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

    body = f'<?xml version="1.0" encoding="UTF-8" ?>\n<Params><ApiKey>{escape(api_key)}</ApiKey></Params>'
    resp = await client.post(
        f"{UNAS_BASE}/login",
        content=body.encode("utf-8"),
        headers={"Content-Type": "text/xml"},
    )
    resp.raise_for_status()
    root = xml_root(resp.text)
    return xml_first_text(root, "Token") if root is not None else ""


# --------------------------------------------------------------------------- #
# BULK termék-listák (sync) — összes termék / tenant, lapozva
# --------------------------------------------------------------------------- #
async def sellvio_list_products(api_base: str, client_id: str, client_secret: str):
    """Streamelő async generátor: GET /api/v2/products lapozva, oldalanként YIELD (data.{items,last_page})."""
    api_base = api_base.rstrip("/")
    async with httpx.AsyncClient(timeout=_LIST_TIMEOUT, follow_redirects=True) as client:
        token = await sellvio_token(client, api_base, client_id, client_secret)
        if not token:
            raise RuntimeError("Sellvio: nincs token")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        page, last_page = 1, 1
        for _ in range(_MAX_PAGES):
            r = await client.get(
                f"{api_base}/api/v2/products",
                params={"page": page, "limit": 100, "locale": "hu"},
                headers=headers,
            )
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
            if items:
                yield items
            last_page = data.get("last_page") or page
            if data.get("next_page_url") is None or page >= int(last_page):
                break
            page += 1


def _sr_items(body) -> list[dict]:
    body = body or {}
    items = body.get("items") or (body.get("response") or {}).get("items") or []
    return [i for i in items if isinstance(i, dict)]


def _sr_json(r):
    """Tolerns JSON: üres törzs / nem application/json / parse-hiba -> None (nem dobunk)."""
    if not getattr(r, "content", b""):
        return None
    if "json" not in (r.headers.get("content-type", "") if hasattr(r, "headers") else "").lower():
        return None
    try:
        return r.json()
    except Exception:  # noqa: BLE001 — malformed JSON
        return None


async def shoprenter_list_products(
    api_base: str, client_id: str, client_secret: str, *, full: int = 1, concurrency: int = 4
):
    """Streamelő async generátor: GET /productExtend?full=<full> lapozva, oldalanként YIELD.

    - full=0 (könnyű) a pass-1 reláció-indexhez (id->name/url); full=1 (nehéz) csak a pass-2 build-hez.
    - Ha a válasz megadja a pageCount-ot: ABLAKONKÉNT párhuzamosan tölti a lapokat (concurrency;
      latency-kötött -> drámai gyorsulás), de a buffer korlátos (≤ concurrency lap) -> streaming-invariáns marad.
    - 429 rate-limit -> exponenciális backoff + retry. Guard: _MAX_PAGES/_LIST_TIMEOUT.
    - SR pipeline (dict-index, per-termék build, engine delta/purge) SORREND-FÜGGETLEN -> a párhuzam biztonságos.
    """
    api_base = api_base.rstrip("/")
    shop = shoprenter_shop(api_base)
    conc = max(1, int(concurrency or 1))
    async with httpx.AsyncClient(timeout=_LIST_TIMEOUT, follow_redirects=True) as client:
        token = await shoprenter_token(client, shop, client_id, client_secret)
        if not token:
            raise RuntimeError("Shoprenter: nincs token")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        async def fetch_page(page: int) -> dict:
            """Egy lap lekérése tolerns hibakezeléssel. SOHA nem dob: nem-JSON/429/5xx/hálózati hiba
            -> backoff + retry; tartós hiba (vagy tartós 4xx) -> {} (end-of-pages-ként üres lista)."""
            for attempt in range(4):
                try:
                    r = await client.get(
                        f"{api_base}/productExtend",
                        params={"full": full, "limit": 200, "page": page},
                        headers=headers,
                    )
                except httpx.HTTPError:                       # hálózati hiba -> backoff + retry
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if r.status_code >= 400:                      # tartós 4xx (nem 429) -> üres oldal
                    logger.warning("Shoprenter page %s HTTP %s -> üres oldal", page, r.status_code)
                    return {}
                data = _sr_json(r)
                if data is None:                              # nem-JSON / üres törzs -> backoff + retry
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                return data
            logger.warning("Shoprenter page %s tartósan nem-JSON/hibás -> end-of-pages (üres)", page)
            return {}

        body0 = await fetch_page(0)
        items0 = _sr_items(body0)
        if items0:
            yield items0
        page_count = body0.get("pageCount")

        if page_count is None:
            # ismeretlen lapszám -> szekvenciális (next flag alapján)
            page, has_next = 1, bool(body0.get("next"))
            while has_next and page < _MAX_PAGES:
                body = await fetch_page(page)
                items = _sr_items(body)
                if items:
                    yield items
                has_next = bool(body.get("next"))
                if not items:
                    break
                page += 1
            return

        # ismert lapszám -> ablakonként párhuzamos (bounded: ≤ conc lap egyszerre a memóriában)
        pages = list(range(1, min(int(page_count), _MAX_PAGES)))
        for i in range(0, len(pages), conc):
            window = pages[i:i + conc]
            for body in await asyncio.gather(*(fetch_page(p) for p in window)):
                items = _sr_items(body)
                if items:
                    yield items


async def woo_list_products(base: str, consumer_key: str, consumer_secret: str):
    """Streamelő async generátor: GET /wp-json/wc/v3/products?per_page=100&page=N (Basic ck/cs)."""
    base = base.rstrip("/")
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
            page_items = [i for i in items if isinstance(i, dict)]
            if page_items:
                yield page_items
            if len(items) < 100:
                break


_UNAS_PRODUCTDB_BODY = (
    '<?xml version="1.0" encoding="UTF-8" ?>\n'
    "<Params>"
    "<Format>csv2</Format>"        # csv2 adja a magyar fejléceket (Cikkszám/Termék Név/…), amire a normalizer épül
    "<Lang>hu</Lang>"
    "<GetName>1</GetName>"
    "<GetPrice>1</GetPrice>"
    "<GetStock>1</GetStock>"
    "<GetCategory>1</GetCategory>"
    "<GetDescriptionShort>1</GetDescriptionShort>"
    "<GetDescriptionLong>1</GetDescriptionLong>"
    "<GetURL>1</GetURL>"
    "<GetAttach>1</GetAttach>"
    "<GetParam>1</GetParam>"
    "</Params>"
)


async def unas_export_csv(api_key: str) -> str:
    """Unas: getProductDB csv2-export (login -> Bearer -> getProductDB -> <Url> -> CSV letöltés).

    A Format=csv2 adja a magyar fejléceket, amikre a builder normalizere épül (a 'csv' más
    oszlopkiosztású). Timeoutok: getProductDB 180s (lassú export-generálás), letöltés 120s.
    Hibánál a hívó (engine) skippel, NEM purge-öl.
    """
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        token = await unas_login(client, api_key)  # text/xml, CDATA-safe Token-parse
        if not token:
            raise RuntimeError("Unas: nincs token")
        r = await client.post(
            f"{UNAS_BASE}/getProductDB",
            content=_UNAS_PRODUCTDB_BODY.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/xml"},
            timeout=180.0,
        )
        r.raise_for_status()
        root = xml_root(r.text)
        url = xml_first_text(root, "Url") if root is not None else ""  # CDATA-safe (ElementTree .text)
        if not url:
            raise RuntimeError("Unas getProductDB: nincs <Url> a válaszban")
        d = await client.get(url, timeout=120.0)
        d.raise_for_status()
        return d.text

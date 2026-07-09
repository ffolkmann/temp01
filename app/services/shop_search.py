"""Webshop-kereso fallback (m25): gyenge RAG-score-nal a bolt sajat keresojet hivjuk.

Platform-adapterek:
- shoprenter: frontend ?route=product/list&keyword= — a talalati oldalon a TERMEK-linkek
  '?keyword=' query-t hordoznak -> normalize_url -> Qdrant find_by_url.
- unas: frontend /shop_search.php?search= — /termek/ prefixu linkek (nyersen a Qdranthoz).
- webdoc: frontend /termek-kereses?k= — '-p<szam>' vegu termek-linkek (nyersen).
- woocommerce: frontend /?s=&post_type=product — /termek/ /product/ vagy
  ?post_type=product&p= permalinkek (nyersen; a normalize a query-s es trailing-slash-es
  WP-permalinkeket elrontana).
- sellvio: REST v2 GET /api/v2/products/?query= (OAuth a tenant api-credjeivel) — az API
  kozvetlenul ad nevet + pretty_url slugot, Qdrant-hidratalas nem kell.

A frontend-agakban a Qdrant adja a friss nevet/adatlapot (type=product szuro);
a bolti kereso csak a RANGSORT adja.

A bolti kereso AND-eli a szavakat, ezert a nyers uzenet ("szeretnek venni egy ... kezdokent")
tipikusan 0 talalat — query-kaszkad: (1) stopszo-szurt + targyrag-vagott tartalomszavak,
(2) szuretlen tartalomszavak, (3) a 2 leghosszabb szo. Az elso nem-ures linklista nyer.
"""

import logging
import re
from urllib.parse import unquote

import httpx

from html import unescape as html_unescape

from app.core.qdrant import get_qdrant
from app.services.current_product import normalize_url
from app.services.platform_api import sellvio_token
from app.services.search_query import search_queries

logger = logging.getLogger("cx.shop_search")

# Szandekosan magasabb az unanswered THRESHOLD-nal (0.45): a "gyenge, de nem
# kritikus" savban is erdemes a bolti keresot megkerdezni.
SEARCH_FB_THRESHOLD = 0.55
_TIMEOUT = 10.0
_MAX_LINKS = 12
_LIMIT = 5

_SR_HREF_RE = re.compile(r'href="(https?://[^"]+\?[^"]*keyword=[^"]*)"')

_SUPPORTED = {"shoprenter", "unas", "webdoc", "woocommerce", "sellvio"}


def _frontend_request(platform: str, base: str, q: str) -> tuple[str, dict]:
    if platform == "shoprenter":
        return f"{base}/index.php", {"route": "product/list", "keyword": q}
    if platform == "unas":
        return f"{base}/shop_search.php", {"search": q}
    if platform == "webdoc":
        return f"{base}/termek-kereses", {"k": q}
    # woocommerce
    return f"{base}/", {"s": q, "post_type": "product"}


def _extract_links(platform: str, html: str, base: str) -> list[str]:
    """Termek-link jeloltek a talalati HTML-bol, a bolti rangsor sorrendjeben."""
    b = re.escape(base)
    if platform == "shoprenter":
        raw = _SR_HREF_RE.findall(html)
        links = [normalize_url(unquote(html_unescape(u))) for u in raw]
    elif platform == "unas":
        links = [html_unescape(u) for u in re.findall(rf'href="({b}/termek/[^"]+)"', html)]
    elif platform == "webdoc":
        links = [html_unescape(u) for u in re.findall(rf'href="({b}/[^"?]*-p\d+)"', html)]
    else:  # woocommerce
        raw = re.findall(
            rf'href="({b}/(?:termek|product)/[^"]+|{b}/\?post_type=product(?:&(?:amp;)?|&#038;)p=\d+)"',
            html,
        )
        links = [html_unescape(u) for u in raw]
    seen: set[str] = set()
    out: list[str] = []
    for u in links:
        if u and u != base and u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= _MAX_LINKS:
            break
    return out


async def _fetch_links(client: httpx.AsyncClient, platform: str, base: str, query: str) -> list[str]:
    url, params = _frontend_request(platform, base, query[:120])
    r = await client.get(url, params=params)
    if r.status_code != 200:
        return []
    return _extract_links(platform, r.text, base)


async def _sellvio_api_search(tenant, query: str, limit: int) -> list[dict]:
    """Sellvio REST v2 full-text kereses — kozvetlen nev + pretty_url."""
    base = str(getattr(tenant, "api_base", "") or "").rstrip("/")
    if not base:
        return []
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
        token = await sellvio_token(c, base, tenant.api_client_id, tenant.api_client_secret)
        if not token:
            return []
        r = await c.get(
            f"{base}/api/v2/products/",
            params={"query": query[:120], "limit": limit, "locale": "hu"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            return []
        d = r.json()
    data = d.get("data") if isinstance(d.get("data"), dict) else d
    items = (data or {}).get("items") or []
    pub = str(getattr(tenant, "public_url", "") or "").rstrip("/")
    out: list[dict] = []
    for p in items:
        if not isinstance(p, dict) or p.get("is_visible") is False:
            continue
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        slug = str(p.get("pretty_url") or "").strip()
        out.append({
            "name": name,
            "url": f"{pub}/hu/{slug}" if (pub and slug) else pub,
            "snippet": " ".join(str(p.get("lead_text") or "").split())[:200],
        })
        if len(out) >= limit:
            break
    return out


async def shop_front_search(tenant, query: str, limit: int = _LIMIT) -> list[dict]:
    """A bolt sajat keresoje -> [{name, url, snippet}] (max `limit`). Fail-safe: [] hibanal."""
    platform = (getattr(tenant, "platform", "") or "")
    if platform not in _SUPPORTED or not (query or "").strip():
        return []

    if platform == "sellvio":
        try:
            for q in search_queries(platform, query):
                out = await _sellvio_api_search(tenant, q, limit)
                if out:
                    return out
        except Exception:  # noqa: BLE001 — a fallback hibaja ne torje a chatet
            logger.exception("shop_search: sellvio hiba (%s)", getattr(tenant, "client_id", "?"))
        return []

    base = str(getattr(tenant, "public_url", "") or "").rstrip("/")
    if not base:
        return []
    links: list[str] = []
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CX-Chatbot/1.0)"},
        ) as client:
            for q in search_queries(platform, query):
                links = await _fetch_links(client, platform, base, q)
                if links:
                    break
    except Exception:  # noqa: BLE001 — a fallback hibaja ne torje a chatet
        logger.exception("shop_search: fetch hiba (%s)", base)
        return []
    if not links:
        return []

    qdrant = get_qdrant()
    out: list[dict] = []
    for u in links:
        try:
            point = await qdrant.find_by_url(tenant.client_id, u)
        except Exception:  # noqa: BLE001
            point = None
        p = (point or {}).get("payload", {}) or {}
        if p.get("type") != "product":
            continue
        out.append({
            "name": str(p.get("name") or "").strip() or u.rsplit("/", 1)[-1],
            "url": u,
            "snippet": " ".join(str(p.get("text") or "").split())[:200],
        })
        if len(out) >= limit:
            break
    return out

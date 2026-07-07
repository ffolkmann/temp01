"""Webshop-kereso fallback (m25): gyenge RAG-score-nal a bolt sajat keresojet hivjuk.

Shoprenter: GET {public_url}/index.php?route=product/list&keyword=<q> — a talalati
oldalon a TERMEK-linkek '?keyword=' query-t hordoznak, ezert a parzolas temafuggetlen:
keyword-es linkek -> normalize_url -> Qdrant find_by_url (friss nev/adatlap a sajat
adatbazisunkbol; a bolti kereso csak a RANGSORT adja).
"""

import logging
import re
from urllib.parse import unquote

import httpx

from app.core.qdrant import get_qdrant
from app.services.current_product import normalize_url

logger = logging.getLogger("cx.shop_search")

# Szandekosan magasabb az unanswered THRESHOLD-nal (0.45): a "gyenge, de nem
# kritikus" savban is erdemes a bolti keresot megkerdezni.
SEARCH_FB_THRESHOLD = 0.55
_TIMEOUT = 6.0
_MAX_LINKS = 12
_LIMIT = 5

_HREF_RE = re.compile(r'href="(https?://[^"]+\?[^"]*keyword=[^"]*)"')


async def shop_front_search(tenant, query: str, limit: int = _LIMIT) -> list[dict]:
    """A bolt frontend-keresoje -> [{name, url, snippet}] (max `limit`). Fail-safe: [] hibanal."""
    if (getattr(tenant, "platform", "") or "") != "shoprenter":
        return []
    base = str(getattr(tenant, "public_url", "") or "").rstrip("/")
    q = (query or "").strip()
    if not base or not q:
        return []
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CX-Chatbot/1.0)"},
        ) as client:
            r = await client.get(
                f"{base}/index.php",
                params={"route": "product/list", "keyword": q[:120]},
            )
            if r.status_code != 200:
                return []
            html = r.text
    except Exception:  # noqa: BLE001 — a fallback hibaja ne torje a chatet
        logger.exception("shop_search: fetch hiba (%s)", base)
        return []

    seen: set[str] = set()
    links: list[str] = []
    for m in _HREF_RE.finditer(html):
        u = normalize_url(unquote(m.group(1)))
        if u and u not in seen and u != base:
            seen.add(u)
            links.append(u)
        if len(links) >= _MAX_LINKS:
            break
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

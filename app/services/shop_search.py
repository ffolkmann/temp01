"""Webshop-kereso fallback (m25): gyenge RAG-score-nal a bolt sajat keresojet hivjuk.

Shoprenter: GET {public_url}/index.php?route=product/list&keyword=<q> — a talalati
oldalon a TERMEK-linkek '?keyword=' query-t hordoznak, ezert a parzolas temafuggetlen:
keyword-es linkek -> normalize_url -> Qdrant find_by_url (friss nev/adatlap a sajat
adatbazisunkbol; a bolti kereso csak a RANGSORT adja).

A bolti kereso AND-eli a szavakat, ezert a nyers uzenet ("szeretnek venni egy ... kezdokent")
tipikusan 0 talalat — query-kaszkad: (1) stopszo-szurt + targyrag-vagott tartalomszavak,
(2) szuretlen tartalomszavak, (3) a 2 leghosszabb szo. Az elso nem-ures linklista nyer.
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
_TIMEOUT = 10.0
_MAX_LINKS = 12
_LIMIT = 5

_HREF_RE = re.compile(r'href="(https?://[^"]+\?[^"]*keyword=[^"]*)"')

_STOPWORDS = {
    "a", "az", "egy", "es", "és", "de", "hogy", "ha", "el", "is", "mar", "már", "meg", "még",
    "szeretnek", "szeretnék", "szeretnem", "szeretném", "keresek", "kerdeznem", "kérdeznem",
    "venni", "vennék", "vennek", "vasarolni", "vásárolni", "erdekelne", "érdekelne", "erdekel", "érdekel",
    "ajanlasz", "ajánlasz", "ajanl", "ajánl", "ajanlani", "mit", "mi", "milyen", "melyik", "hol",
    "van", "vane", "van-e", "lenne", "kellene", "kene", "kéne", "kell", "tudsz", "tudnal", "tudnál",
    "kezdo", "kezdő", "kezdokent", "kezdőként", "kezdoknek", "kezdőknek", "vagyok", "vagyunk",
    "nekem", "nekunk", "nekünk", "hozzam", "hozzám", "valami", "valamit", "olcso", "olcsó",
    "jo", "jó", "legjobb", "szerintetek", "szerinted", "koszi", "köszi", "koszonom", "köszönöm",
}


def _stem(w: str) -> str:
    """Minimal magyar targyrag-vagas a bolti LIKE-kereso kedveert (botot -> bot, halot -> halo)."""
    if len(w) > 4:
        for suf in ("okat", "eket", "akat", "öket"):
            if w.endswith(suf):
                return w[: -len(suf)]
        for suf in ("ot", "et", "at", "öt"):
            if w.endswith(suf):
                return w[: -len(suf)]
        # mgh+t es msh+t targyrag is (hálót -> háló, halat mar fent);
        # dupla-t (szett, watt) NEM rag, marad
        if w.endswith("t") and not w.endswith("tt"):
            return w[:-1]
    return w


def _build_queries(message: str) -> list[str]:
    words = re.findall(r"[\w\-]+", (message or "").lower())
    content = [w for w in words if w not in _STOPWORDS and len(w) > 2 and not w.isdigit()]
    # szammal kezdodo tagok ("45-ös", "8-as") gyilkos AND-feltetelek a bolti keresoben
    # -> a fo query-kbol kihagyjuk, csak a szoveges torzs megy
    core = [w for w in content if not w[0].isdigit()]
    base = core or content
    out: list[str] = []
    if base:
        q1 = " ".join(_stem(w) for w in base[:4])
        out.append(q1)
        q2 = " ".join(base[:4])
        if q2 not in out:
            out.append(q2)
        if len(base) > 1:
            q3 = _stem(sorted(base, key=len, reverse=True)[0])
            if q3 and q3 not in out:
                out.append(q3)
    if not out:
        out.append((message or "").strip()[:120])
    return out[:3]


async def _fetch_links(client: httpx.AsyncClient, base: str, query: str) -> list[str]:
    r = await client.get(
        f"{base}/index.php",
        params={"route": "product/list", "keyword": query[:120]},
    )
    if r.status_code != 200:
        return []
    seen: set[str] = set()
    links: list[str] = []
    for m in _HREF_RE.finditer(r.text):
        u = normalize_url(unquote(m.group(1)))
        if u and u not in seen and u != base:
            seen.add(u)
            links.append(u)
        if len(links) >= _MAX_LINKS:
            break
    return links


async def shop_front_search(tenant, query: str, limit: int = _LIMIT) -> list[dict]:
    """A bolt frontend-keresoje -> [{name, url, snippet}] (max `limit`). Fail-safe: [] hibanal."""
    if (getattr(tenant, "platform", "") or "") != "shoprenter":
        return []
    base = str(getattr(tenant, "public_url", "") or "").rstrip("/")
    if not base or not (query or "").strip():
        return []
    links: list[str] = []
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CX-Chatbot/1.0)"},
        ) as client:
            for q in _build_queries(query):
                links = await _fetch_links(client, base, q)
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

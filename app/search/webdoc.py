"""CX SmartSearch — Webdoc ingest-mapper (S4).

A Webdoc-bolt napi JSON-exportja (tenants.api_base) MAR feed-alaku: a rekord
mezoi (id, sku, name, brand, category, price_gross, available, url, image_url,
parameters) pontosan azok, amiket az indexcore var — a pilot-indexer
(/root/cx_smartsearch_indexer.py) ugyanezt a feedet ette. Ezert itt NINCS
mezo-leképezes, csak: letoltes + higienia + prefix-szamitas.

Dontesek:
  - created_day NINCS a feedben -> nem is adunk: az indexcore.apply_days a
    first_seen registryvel adja az "Uj" badge 'd' mezojet (pilot-paritas,
    elso futasnal minden termek "regi" -> nincs hamis Uj).
  - orig_price sincs a feedben (a Webdoc-export nem ad akcios/athuzott arat)
    -> nincs akcio-badge, amig a feed nem bovul.
  - feed-url: tenants.api_base, a search_config 'feed_url' kulcsa felulirhatja.
  - prefixek: public_url / domain alapjan, a search_config 'url_prefix' es
    'img_prefix' kulcsa felulirhatja (a kep-prefix a Webdoc img-export utja).
  - id nelkuli vagy nem-dict rekord kiesik (az indexcore ures 'i'-t adna ra).
"""
from __future__ import annotations

import httpx

_TIMEOUT = 240.0
_IMG_SUFFIX = "services/img-export/"


# --------------------------------------------------------------------------- #
# tiszta (tesztelheto) segedek
# --------------------------------------------------------------------------- #
def feed_url(tenant, tcfg=None):
    """A letoltendo export-url (tcfg feed_url > tenants.api_base)."""
    cfg = tcfg if isinstance(tcfg, dict) else {}
    url = str(cfg.get("feed_url") or getattr(tenant, "api_base", "") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError("Webdoc: nincs feed-url (tenants.api_base vagy search_config.feed_url)")
    return url


def prefixes(tenant, tcfg=None):
    """(url_prefix, img_prefix) — a tcfg felulirja, kulonben public_url/domain."""
    cfg = tcfg if isinstance(tcfg, dict) else {}
    pub = str(getattr(tenant, "public_url", "") or "").strip().rstrip("/")
    if not pub:
        dom = str(getattr(tenant, "domain", "") or "").strip().strip("/")
        pub = ("https://" + dom) if dom else ""
    url_prefix = str(cfg.get("url_prefix") or ((pub + "/") if pub else ""))
    img_prefix = str(cfg.get("img_prefix") or ((url_prefix + _IMG_SUFFIX) if url_prefix else ""))
    return url_prefix, img_prefix


def clean_products(payload):
    """A feed termek-tombje -> ervenyes rekordok ({"products": [...]} vagy nyers lista)."""
    items = payload.get("products") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    out = []
    for p in items:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if pid is None or not str(pid).strip():
            continue
        out.append(p)
    return out


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
async def fetch(tenant, tcfg=None):
    """(products_feed_alaku, url_prefix, img_prefix) egy Webdoc tenantra."""
    url = feed_url(tenant, tcfg)
    url_prefix, img_prefix = prefixes(tenant, tcfg)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "cx-smartsearch/1.0",
                                           "Accept": "application/json"})
        r.raise_for_status()
        payload = r.json()
    return clean_products(payload), url_prefix, img_prefix

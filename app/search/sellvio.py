"""CX SmartSearch — Sellvio ingest-mapper (S1).

api/v2 (OAuth2 client-credentials) -> feed-alaku termek-dict lista az
indexcore-nak. Harom forras egy tokennel:
  - /api/v2/categories          -> id -> (nev, parent) fa (melyseg-valasztashoz)
  - /api/v2/product-parameters/ -> product_id -> [{"name","value"}] (facet-adat)
  - /api/v2/products            -> termek-mezok (locale=hu, lapozva)

Dontesek:
  - kategoria: a termek categories map-jebol a LEGMELYEBB (fa-melyseg szerint;
    dontetlennel a kisebb id) — a Sellvio a gyoker- es level-kategoriat is adja.
  - available = is_visible AND is_available_for_order.
  - url = pretty_url (a Sellvio ABSZOLUT url-t ad); kep = gallery is_main,
    kulonben az elso elem.
  - created_day a created_at-bol (unix-nap) -> valodi "Uj" badge, registry nelkul.
  - orig_price csak a 'prices' map old_price mezojebol (ha > brutto); a 'price'
    objektum discount mezojenek szemantikaja nem verifikalt, azt nem hasznaljuk.

Az auth a kozos app.services.platform_api.sellvio_token (egy helyen el);
fajl-betoltos fallback a fake-app-os tesztkornyezetek ellen (m79c minta).
"""
from __future__ import annotations

import datetime
import re

import httpx

try:
    from app.services.platform_api import sellvio_token
except Exception:  # fajl-betoltos tesztek / fake app-modulok a sys.modules-ben
    import importlib.util as _ilu
    import pathlib as _pl
    _pp = _pl.Path(__file__).resolve().parents[1] / "services" / "platform_api.py"
    _sp = _ilu.spec_from_file_location("platform_api_ss_fb", _pp)
    _pm = _ilu.module_from_spec(_sp)
    _sp.loader.exec_module(_pm)
    sellvio_token = _pm.sellvio_token

_MAX_PAGES = 2000
_TIMEOUT = 60.0


# --------------------------------------------------------------------------- #
# tiszta (tesztelheto) segedek
# --------------------------------------------------------------------------- #
def _num(v):
    """Szam-normalizalas: '58600.00'/58600.0 -> 58600; nem szam -> None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.strip())
        except (ValueError, AttributeError):
            return None
    else:
        return None
    return int(f) if f.is_integer() else f


def build_depth(tree):
    """tree: {id:int -> parent:int|None} -> depth(id) fuggveny (memo + ciklus-guard)."""
    memo = {}

    def depth(cid):
        if cid in memo:
            return memo[cid]
        d, cur, hops = 0, tree.get(cid), 0
        while cur is not None and hops < 20:
            d += 1
            cur = tree.get(cur)
            hops += 1
        memo[cid] = d
        return d
    return depth


def pick_category(cats_map, depth):
    """A termek categories map-jebol ({'1008': {'id':1008,'name':...}, ...}) a
    legmelyebb kategoria neve; dontetlennel a kisebb id. Ures -> ''."""
    if not isinstance(cats_map, dict) or not cats_map:
        return ""
    best = None  # (depth, -id, name) — max depth, azon belul MIN id
    for entry in cats_map.values():
        if not isinstance(entry, dict):
            continue
        cid = entry.get("id")
        name = entry.get("name")
        if not isinstance(cid, int) or not isinstance(name, str) or not name.strip():
            continue
        key = (depth(cid), -cid)
        if best is None or key > best[0]:
            best = (key, name.strip())
    return best[1] if best else ""


def pick_image(gallery):
    """gallery: [{'file':..., 'is_main':bool}, ...] -> is_main, kulonben az elso."""
    if not isinstance(gallery, list):
        return ""
    first = ""
    for g in gallery:
        if not isinstance(g, dict):
            continue
        f = g.get("file")
        if not isinstance(f, str) or not f:
            continue
        if g.get("is_main"):
            return f
        if not first:
            first = f
    return first


def extract_price(p):
    """(price_gross, orig_price) a 'price' objektumbol vagy a 'prices' map-bol."""
    pr = p.get("price")
    if isinstance(pr, dict):
        return _num(pr.get("brutto_price")), None
    prices = p.get("prices")
    if isinstance(prices, dict) and prices:
        entry = next((v for v in prices.values() if isinstance(v, dict)), None)
        if entry:
            brutto = _num(entry.get("brutto_price"))
            old = _num(entry.get("old_price"))
            orig = old if (brutto is not None and old is not None and old > brutto) else None
            return brutto, orig
    return None, None


def created_day(s):
    """'2026-04-20T13:57:31.000000Z' -> unix-nap (int); hibas/ures -> None."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return int(dt.timestamp() // 86400)
    except ValueError:
        return None


_ABS_HOST = re.compile(r"^(?:https?:)?//[^/]+/?", re.I)


def canon_url(value, root):
    """Abszolut URL sema+host reszet a bolt kanonikus gyokerere csereli.

    A Sellvio a pretty_url-t (es nehany kep-URL-t) a platform-aldomainnel adja vissza
    (pl. https://<bolt>.mysellvio.com/...), nem a bolt sajat domainjen. Egy bolt
    indexeben minden URL aze a bolte, ezert a hostot a public_url-bol szamolt gyokerre
    cserelyuk - kulonben az indexcore nem tudja levagni a prefixet, es a widget
    prefix + abszolut URL osszefuzesbol torott link lesz.
    """
    v = str(value or "")
    if not v or v.startswith(root):
        return v
    m = _ABS_HOST.match(v)
    return root + v[m.end():] if m else v


def map_product(p, pmap, depth):
    """Nyers Sellvio termek -> feed-alaku rekord (indexcore-bemenet)."""
    price, orig = extract_price(p)
    brand = p.get("brand")
    return {
        "id": p.get("id", ""),
        "sku": str(p.get("code") or ""),
        "name": str(p.get("name") or ""),
        "brand": str((brand or {}).get("name") or "") if isinstance(brand, dict) else "",
        "category": pick_category(p.get("categories"), depth),
        "price_gross": price,
        "orig_price": orig,
        "available": bool(p.get("is_visible")) and bool(p.get("is_available_for_order")),
        "url": str(p.get("pretty_url") or ""),
        "image_url": pick_image(p.get("gallery")),
        "parameters": pmap.get(p.get("id"), []),
        "created_day": created_day(p.get("created_at")),
    }


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
async def _pages(client, base, headers, path, limit):
    """Laravel-paginator lapozo: oldalankent yield-eli az items listat."""
    page, last_page = 1, 1
    for _ in range(_MAX_PAGES):
        r = await client.get(f"{base}{path}", params={"page": page, "limit": limit, "locale": "hu"},
                             headers=headers)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
        if items:
            yield items
        last_page = data.get("last_page") or page
        if data.get("next_page_url") is None or page >= int(last_page):
            break
        page += 1


async def fetch(tenant, tcfg=None):
    """(products_feed_alaku, url_prefix, img_prefix) egy Sellvio tenantra."""
    base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    sec = str(tenant.api_client_secret or "").strip()
    pub = (str(tenant.public_url or "").strip().rstrip("/") or base)
    url_prefix = pub + "/"
    img_prefix = url_prefix + "tenancy/assets/products/"

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        token = await sellvio_token(client, base, cid, sec)
        if not token:
            raise RuntimeError("Sellvio: nincs token")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        tree = {}
        async for page in _pages(client, base, headers, "/api/v2/categories", 200):
            for c in page:
                if isinstance(c.get("id"), int):
                    tree[c["id"]] = c.get("parent_id")
        depth = build_depth(tree)

        pmap: dict = {}
        async for page in _pages(client, base, headers, "/api/v2/product-parameters/", 500):
            for it in page:
                prod = it.get("product") or {}
                pid = prod.get("id")
                par = it.get("parameter") or {}
                name = par.get("name")
                if pid is None or not isinstance(name, str):
                    continue
                pmap.setdefault(pid, []).append({"name": name, "value": it.get("value")})

        products = []
        async for page in _pages(client, base, headers, "/api/v2/products", 100):
            for p in page:
                products.append(map_product(p, pmap, depth))

    for row in products:          # platform-aldomaines URL-ek a bolt sajat domainjere
        row["url"] = canon_url(row.get("url"), url_prefix)
        row["image_url"] = canon_url(row.get("image_url"), url_prefix)

    return products, url_prefix, img_prefix

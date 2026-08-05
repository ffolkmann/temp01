"""CX SmartSearch/Konfigurator — Shoprenter ingest-mapper (K1, copygo pilot).

api2 (OAuth2 Bearer) -> feed-alaku termek-dict lista az indexcore-nak.
Kategoria-SZURT ingest (a copygo-bolt 59k termekes, a nyomtato-kategoriak
~1520 termeke kell), a kf01/probe felderites szerint:

  1. GET /productCategoryRelations?full=1&categoryId=<b64('category-category_id=N')>
     -> product_id-k (a relacio id b64-dekodjabol)
  2. GET /productExtend/<b64('product-product_id=PID')>?full=1 -> minden EGYBEN:
     attr-ertekek, descriptions[0], productPrices, stock1-4, urlAliases,
     mainPicture, manufacturer

Kategoria-lista a tenant search_config.shoprenter.categories kulcsabol
(innerId = storefront URL-szam). Konfigurator-igenyek:
  - attr-nev merge (funkcio+funkciok, lapadagolotipus(a), memoria(nyomtato),
    sebesseg mono+monoiso) es ertek-kanonizalas (szinkezeles Mono/mono/Szines)
  - szam-parse plauzibilitas-kapuval (sebesseg 4..100 oldal/perc)
  - technologia kategoria-fallback (attr csak 56%)
  - halozat (LAN/WiFi) es duplex: attr + leiras-regex KOMBO -> derivalt parameter
  - printer-only szuro: van core-attr (funkcio/technologia) ES nincs kellek-attr
  - belso attr-ok (kefix_kat, a_beszallito) kihagyva; gyarto-normalizalas

Ar: productPrices default customerGroup, gross/grossSpecial (special < gross ->
akcios ar + athuzott eredeti). Lathatosag: status != "0" bekerul (a storefront a
status=2-t is mutatja, "Elfogyott" badge-dzsel); available = keszlet-osszeg > 0.
Az auth a kozos app.services.platform_api-bol; fajl-betoltos fallback a
fake-app-os tesztkornyezetek ellen (m79c minta).
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import re

import httpx

try:
    from app.services.platform_api import (
        shoprenter_resource_id,
        shoprenter_shop,
        shoprenter_token,
    )
except Exception:  # fajl-betoltos tesztek / fake app-modulok a sys.modules-ben
    import importlib.util as _ilu
    import pathlib as _pl
    _pp = _pl.Path(__file__).resolve().parents[1] / "services" / "platform_api.py"
    _sp = _ilu.spec_from_file_location("platform_api_sr_fb", _pp)
    _pm = _ilu.module_from_spec(_sp)
    _sp.loader.exec_module(_pm)
    shoprenter_resource_id = _pm.shoprenter_resource_id
    shoprenter_shop = _pm.shoprenter_shop
    shoprenter_token = _pm.shoprenter_token

_TIMEOUT = 60.0
_REL_LIMIT = 200
_MAX_REL_PAGES = 200
_SLEEP = 0.05  # a ~0.4s latencia mellett ez ~2.2 req/s (SR limit: 3/s)

INTERNAL_ATTRS = {"kefix_kat", "a_beszallito"}
SUPPLY_ATTRS = {"kellekanyagtipus", "kompatibilitas"}
CORE_ATTRS = {"funkcio", "funkciok", "nyomtatasitechnologia"}
PASS_ATTRS = ("garancia", "kijelzotipusa", "allapot")

# kategoria-innerId -> technologia-fallback (csak ahol a kategoria implikalja)
TECH_BY_CAT = {
    3423: "L\u00e9zer",
    3420: "Tintasugaras",
    3408: "M\u00e1trix",
    3477: "Thermo",
}

_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_DPI_RE = re.compile(r"\d{3,5}")
_WIFI_DESC_RE = re.compile(r"wi-?fi|wlan", re.I)
_LAN_DESC_CI_RE = re.compile(r"ethernet|h\u00e1l\u00f3zati|rj-?45", re.I)
_LAN_DESC_CS_RE = re.compile(r"\bLAN\b")
_DUPLEX_DESC_RE = re.compile(r"duplex|k\u00e9toldalas", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------- #
# tiszta (tesztelheto) segedek
# --------------------------------------------------------------------------- #
def _num(v):
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


def attr_values(item):
    """Egy productAttributeExtend elem kitoltott ertekei.

    Kitoltott alak (kf01-ben igazolva): "value": [{"value": "12 honap",
    "language": {...}}, ...]; tureskent az egyszeru str es a str-lista is megy.
    """
    out = []
    v = item.get("value")
    if isinstance(v, str) and v.strip():
        out.append(v.strip())
    elif isinstance(v, list):
        for d in v:
            if isinstance(d, dict):
                s = d.get("value")
                if isinstance(s, str) and s.strip():
                    out.append(s.strip())
            elif isinstance(d, str) and d.strip():
                out.append(d.strip())
    return out


def collect_attrs(p):
    """{attr_nev: [ertekek]} a productAttributeExtend kitoltott elemeibol."""
    raw = {}
    for it in (p.get("productAttributeExtend") or []):
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if name in INTERNAL_ATTRS:
            continue
        vals = attr_values(it)
        if vals:
            raw.setdefault(name, []).extend(vals)
    return raw


def parse_speed(vals):
    """oldal/perc ertekek -> int a 4..100 plauzibilitas-kapuval (max)."""
    best = None
    for v in vals:
        m = _NUM_RE.search(str(v))
        if not m:
            continue
        try:
            n = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 4 <= n <= 100:
            n = int(round(n))
            best = n if best is None else max(best, n)
    return best


def parse_dpi(vals):
    """'1200 x 600 dpi' / '4800*1200' -> a legnagyobb komponens (100..10000)."""
    best = None
    for v in vals:
        for m in _DPI_RE.finditer(str(v)):
            n = int(m.group(0))
            if 100 <= n <= 10000:
                best = n if best is None else max(best, n)
    return best


def parse_mb(vals):
    """'256 MB' / '3072' -> int MB (8..65536 kapu)."""
    best = None
    for v in vals:
        m = _NUM_RE.search(str(v))
        if not m:
            continue
        try:
            n = int(round(float(m.group(1).replace(",", "."))))
        except ValueError:
            continue
        if 8 <= n <= 65536:
            best = n if best is None else max(best, n)
    return best


def canon_funkcio(vals):
    j = " ".join(vals).lower()
    out = []
    for token, label in (("nyomtat", "Nyomtat\u00e1s"), ("m\u00e1sol", "M\u00e1sol\u00e1s"),
                         ("szkennel", "Szkennel\u00e9s"), ("scan", "Szkennel\u00e9s"),
                         ("fax", "Fax")):
        if token in j and label not in out:
            out.append(label)
    return out


def canon_szin(vals, has_color_speed=False):
    j = " ".join(vals).lower()
    if "sz\u00edn" in j or "color" in j:
        return "Sz\u00ednes"
    if "mono" in j or "fekete" in j:
        return "Mono"
    return "Sz\u00ednes" if has_color_speed else None


def canon_duplex(vals, desc_hit):
    """-> (duplex, duplex_szken). Az attr erteke a duplex HATOKORE
    ('Nyomtatas' / 'Nyomtatas, Szkenneles/Masolas' / 'Manualis')."""
    j = " ".join(vals).lower()
    if j:
        dupl = "Manu\u00e1lis" if "manu" in j else "Automata"
        dscan = ("szkennel" in j) or ("m\u00e1sol" in j)
        return dupl, dscan
    return ("Val\u00f3sz\u00edn\u0171" if desc_hit else None), False


def canon_adf(vals):
    j = " ".join(vals)
    ju = j.upper()
    for t in ("DSDF", "DADF", "RADF"):
        if t in ju:
            return t
    if "ADF" in ju:
        return "ADF"
    if "simatet" in j.lower():
        return "Simatet\u0151"
    return None


def canon_papir(vals):
    j = " ".join(vals).upper().replace(" ", "")
    if "A3+" in j:
        return "A3+"
    if "A3" in j:
        return "A3"
    if "A4" in j:
        return "A4"
    return None


def canon_tech(vals, cat_id):
    j = " ".join(vals).lower()
    if "l\u00e9zer" in j or "laser" in j:
        return "L\u00e9zer"
    if "tinta" in j or "ink" in j:
        return "Tintasugaras"
    if "m\u00e1trix" in j:
        return "M\u00e1trix"
    if "led" in j:
        return "LED"
    if "thermo" in j or "termo" in j or "h\u0151" in j:
        return "Thermo"
    return TECH_BY_CAT.get(cat_id)


def canon_halozat(raw, text):
    """LAN/WiFi lista az attr-okbol ES a leiras-szovegbol (kombo, handoff)."""
    vals = " ".join(v for a in ("wireless", "elsodlegescsatlakozok",
                                "wirelesscsatlakozok")
                    for v in raw.get(a, ())).lower()
    out = []
    if "wifi" in vals or "wi-fi" in vals or "wlan" in vals or _WIFI_DESC_RE.search(text):
        out.append("WiFi")
    if ("h\u00e1l\u00f3zat" in vals or "ethernet" in vals or "rj45" in vals
            or "rj-45" in vals or _LAN_DESC_CI_RE.search(text)
            or _LAN_DESC_CS_RE.search(text)):
        out.append("LAN")
    return out


def canon_brand(name, raw):
    b = str(name or "").strip()
    if not b:
        vals = raw.get("gyarto") or []
        b = str(vals[0] if vals else "").strip()
    low = b.lower()
    if low.startswith("hp"):
        return "HP"
    if low.startswith("eps"):
        return "Epson"
    if b.isupper() and len(b) > 3:
        return b.title()
    return b


def extract_price(p):
    """(price_gross, orig_price) a productPrices default-csoportjabol (HUF)."""
    prices = p.get("productPrices")
    if not isinstance(prices, list):
        return None, None
    entry = None
    for it in prices:
        if not isinstance(it, dict) or it.get("currencyCode") not in (None, "HUF"):
            continue
        if entry is None:
            entry = it
        if isinstance(it.get("customerGroup"), dict) and it["customerGroup"].get("default"):
            entry = it
            break
    if entry is None:
        return None, None
    gross = _num(entry.get("gross"))
    special = _num(entry.get("grossSpecial"))
    if special and special > 0 and (not gross or special < gross):
        orig = gross if (gross and gross > special) else None
        return special, orig
    return gross, None


def created_day(s):
    """'2019-09-12T13:15:21' -> unix-nap (int); hibas/ures -> None."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp() // 86400)
    except ValueError:
        return None


def desc_text(p):
    """Regex-flagekhez: nev + short + leiras (tag-strip) + parameters mezo."""
    pd = (p.get("productDescriptions") or [{}])
    pd = pd[0] if pd and isinstance(pd[0], dict) else {}
    parts = [str(pd.get("name") or ""), str(pd.get("shortDescription") or ""),
             _TAG_RE.sub(" ", str(pd.get("description") or "")),
             _TAG_RE.sub(" ", str(pd.get("parameters") or ""))]
    return " ".join(parts)


def map_product(p, cat_id, cat_name):
    """Nyers SR productExtend -> feed-alaku rekord; None = kiszurve.

    Printer-only szuro (handoff): van core-attr ES nincs kellek-attr.
    """
    if str(p.get("status") or "") == "0":
        return None
    raw = collect_attrs(p)
    names = set(raw)
    if names & SUPPLY_ATTRS:
        return None
    if not (names & CORE_ATTRS):
        return None

    pd = (p.get("productDescriptions") or [{}])
    pd = pd[0] if pd and isinstance(pd[0], dict) else {}
    text = desc_text(p)

    params = []

    def add(name, value):
        if value is None:
            return
        vals = value if isinstance(value, list) else [value]
        for v in vals:
            v = str(v).strip()
            if v:
                params.append({"name": name, "value": v})

    add("funkciok", canon_funkcio(raw.get("funkcio", []) + raw.get("funkciok", [])))
    add("technologia", canon_tech(raw.get("nyomtatasitechnologia", []), cat_id))
    color_speed = parse_speed(raw.get("nyomtatasisebessegszines", []))
    add("szinkezeles", canon_szin(raw.get("szinkezeles", []),
                                  has_color_speed=color_speed is not None))
    speed = parse_speed(raw.get("nyomtatasisebesmonoiso", []))
    if speed is None:
        speed = parse_speed(raw.get("nyomtatasisebessegmono", []))
    add("sebesseg_ppm", None if speed is None else str(speed))
    dupl, dscan = canon_duplex(raw.get("duplex", []),
                               bool(_DUPLEX_DESC_RE.search(text)))
    add("duplex", dupl)
    adf = canon_adf(raw.get("lapadagolotipus", []) + raw.get("lapadagolotipusa", []))
    add("lapadagolo", adf)
    if dscan or adf in ("DADF", "DSDF", "RADF"):
        add("duplex_szken", "Igen")
    add("papirmeret", canon_papir(raw.get("maximalispapirmeret", [])))
    add("halozat", canon_halozat(raw, text))
    dpi = parse_dpi(raw.get("maxnyomtatasifelbontas", []))
    add("felbontas_dpi", None if dpi is None else str(dpi))
    mb = parse_mb(raw.get("memoria", []) + raw.get("memorianyomtato", []))
    add("memoria_mb", None if mb is None else str(mb))
    for a in PASS_ATTRS:
        add(a, raw.get(a))

    price, orig = extract_price(p)
    stock = 0.0
    for i in (1, 2, 3, 4):
        stock += _num(p.get("stock%d" % i)) or 0
    ua = p.get("urlAliases") or []
    alias = ua[0].get("urlAlias") if ua and isinstance(ua[0], dict) else ""
    manuf = p.get("manufacturer")
    return {
        "id": p.get("innerId", ""),
        "sku": str(p.get("sku") or ""),
        "name": str(pd.get("name") or "").strip(),
        "brand": canon_brand((manuf or {}).get("name") if isinstance(manuf, dict) else "", raw),
        "category": cat_name,
        "price_gross": price,
        "orig_price": orig,
        "available": stock > 0,
        "url": str(alias or ""),
        "image_url": str(p.get("mainPicture") or ""),
        "parameters": params,
        "created_day": created_day(p.get("dateCreated")),
    }


def decode_rel_pid(rel_id_b64):
    """'productCategory-product_id=X&category_id=Y' b64-bol -> 'X' vagy None."""
    try:
        rid = base64.b64decode(str(rel_id_b64 or "")).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return None
    for part in rid.replace("productCategory-", "").split("&"):
        if part.startswith("product_id="):
            return part.split("=", 1)[1] or None
    return None


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
async def fetch(tenant, tcfg=None):
    """(products_feed_alaku, url_prefix, img_prefix) egy Shoprenter tenantra."""
    cfg = (tcfg or {}).get("shoprenter") or {}
    cats = [int(c) for c in (cfg.get("categories") or []) if str(c).strip()]
    if not cats:
        raise RuntimeError(
            "Shoprenter: nincs kategoria-lista (search_config.shoprenter.categories)")
    base = str(tenant.api_base or "").strip().rstrip("/")
    shop = shoprenter_shop(base)
    cid = str(tenant.api_client_id or "").strip()
    sec = str(tenant.api_client_secret or "").strip()
    pub = str(tenant.public_url or "").strip().rstrip("/")
    if not pub:
        raise RuntimeError("Shoprenter: nincs public_url")
    url_prefix = pub + "/"
    img_prefix = pub + "/"

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        token = await shoprenter_token(client, shop, cid, sec)
        if not token:
            raise RuntimeError("Shoprenter: nincs token")
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}

        async def req(path, params=None):
            """Tolerans GET: 429/5xx backoff, 401-re EGYSZERI re-auth (a 401 a
            copygo-n bizonyitottan tranziens is lehet)."""
            nonlocal token, headers
            reauthed = False
            for attempt in range(5):
                try:
                    r = await client.get(base + path, params=params, headers=headers)
                except httpx.HTTPError:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if r.status_code == 401 and not reauthed:
                    reauthed = True
                    token = await shoprenter_token(client, shop, cid, sec)
                    headers = {"Authorization": "Bearer " + token,
                               "Accept": "application/json"}
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            raise RuntimeError("Shoprenter: tartos hiba: %s" % path)

        # 1) kategoria-nevek
        cat_names = {}
        for c in cats:
            body = await req("/categoryExtend/%s" % shoprenter_resource_id("category", str(c)),
                             {"full": 1})
            cds = body.get("categoryDescriptions") or []
            nm = cds[0].get("name") if cds and isinstance(cds[0], dict) else ""
            cat_names[c] = str(nm or c)
            await asyncio.sleep(_SLEEP)

        # 2) relaciok kategoriankent -> pid-sorrend + pid->kategoria (elso nyer)
        pid_cat = {}
        order = []
        for c in cats:
            b64cat = base64.b64encode(("category-category_id=%d" % c).encode()).decode()
            for page in range(_MAX_REL_PAGES):
                body = await req("/productCategoryRelations",
                                 {"full": 1, "limit": _REL_LIMIT, "page": page,
                                  "categoryId": b64cat})
                items = body.get("items") or (body.get("response") or {}).get("items") or []
                got = 0
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    pid = decode_rel_pid(it.get("id"))
                    if pid:
                        got += 1
                        if pid not in pid_cat:
                            pid_cat[pid] = c
                            order.append(pid)
                await asyncio.sleep(_SLEEP)
                if not items or len(items) < _REL_LIMIT:
                    break

        # 3) termekenkent productExtend -> map_product (+ diag szamlalok)
        products = []
        diag = {c: [0, 0] for c in cats}  # cat -> [bekerult, kiszurt]
        for pid in order:
            c = pid_cat[pid]
            body = await req("/productExtend/%s" % shoprenter_resource_id("product", pid),
                             {"full": 1})
            rec = map_product(body, c, cat_names.get(c, str(c)))
            if rec is None:
                diag[c][1] += 1
            else:
                diag[c][0] += 1
                products.append(rec)
            await asyncio.sleep(_SLEEP)

        for c in cats:
            print("shoprenter-diag %s cat=%s(%s) kept=%d dropped=%d" % (
                tenant.client_id, c, cat_names.get(c, ""), diag[c][0], diag[c][1]))

    return products, url_prefix, img_prefix

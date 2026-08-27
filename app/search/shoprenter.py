"""CX SmartSearch/Konfigurator — Shoprenter ingest-mapper (K1 -> kfcat/1, generikus).

api2 (OAuth2 Bearer) -> feed-alaku termek-dict lista az indexcore-nak.

kfcat/1 (2026-08-27): a mapper GENERIKUS lett - a motorban nincs termek-tudas.
  - Forras: /productExtend?full=1&limit=200 KOLLEKCIO, lapozva, parhuzamosan
    (platform_api.shoprenter_list_products) - nem termekenkenti hivas.
  - search_config.shoprenter.categories: OPCIONALIS. Ures -> teljes katalogus.
  - MINDEN kitoltott attributum nyersen atmegy parameterkent (generic_params).
  - search_config.shoprenter.profiles[]: nevvel hivott kanonizalo profil,
    kategoriahoz kotve, pl. {"profile": "printer", "categories": [3420, ...],
    "require_any_attr": ["funkcio", "funkciok", "nyomtatasitechnologia"]}.
    A profil kanonizalt parameterei (technologia, sebesseg_ppm, papirmeret,
    halozat, duplex...) a nyers attributumok MELLE kerulnek. A require_any_attr
    a regi CORE/SUPPLY eldobo-heurisztika helyett: a termek csak akkor marad,
    ha legalabb egy felsorolt attributuma kitoltott (a hibas kellek-attributumu
    nyomtato - copygo WF-M5899, EM-C800 - igy bent marad, a funkcio nelkuli
    kellek kiesik).
  - search_config.shoprenter.skip_attrs: belso attr-nevek, amik nem mennek at
    (alap: kefix_kat, a_beszallito).
  - Keszlet-szures NEM itt: indexcore only_available (platform-fuggetlen).

Ar: productPrices default customerGroup, gross/grossSpecial (special < gross ->
akcios ar + athuzott eredeti). Lathatosag: status != "0" bekerul (a storefront a
status=2-t is mutatja, "Elfogyott" badge-dzsel); available = keszlet-osszeg > 0.
Kep: csak a /custom/<shop>/image/cache/w300h300wt1/<ut> alak ad kepet.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import re

import httpx

try:
    from app.services.platform_api import (
        shoprenter_list_products,
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
    shoprenter_list_products = _pm.shoprenter_list_products

_TIMEOUT = 60.0
_SLEEP = 0.05
_CONCURRENCY = 4        # kfcat/1: merve 4 lap / 13 s, 429 nelkul (SR limit 3 req/s)
_MAX_CAT_PAGES = 50     # categoryExtend 200/lap -> 10 000 kategoria
MAX_ATTR_VALUES = 8     # ennyi ertek megy at egy attributumbol (params.json meret)

INTERNAL_ATTRS = {"kefix_kat", "a_beszallito"}   # alap skip_attrs (configbol bovitheto)
# 'printer' profil: a copygo-n mert attr-nevek (kf01-kf18) - CSAK profillal aktiv
CORE_ATTRS = {"funkcio", "funkciok", "nyomtatasitechnologia"}  # printer alap require_any_attr
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


def collect_attrs(p, skip=INTERNAL_ATTRS):
    """{attr_nev: [ertekek]} a productAttributeExtend kitoltott elemeibol."""
    raw = {}
    for it in (p.get("productAttributeExtend") or []):
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if name in skip:
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


def profile_for(cat_ids, profiles):
    """(profil, a termek profilba eso kategoriai) - az elso illeszkedo profil."""
    for pr in profiles:
        pc = pr.get("cats") or set()
        hit = [c for c in cat_ids if c in pc]
        if hit:
            return pr, hit
    return None, []


def pick_category(cat_ids, wanted, profiles):
    """A termek 'c' mezoje: az elso kategoria a tenant listajabol (annak a
    sorrendjeben), kulonben a profil kategoriaja, kulonben az elso relacio."""
    if wanted:
        for c in wanted:
            if c in cat_ids:
                return c
    pr, hit = profile_for(cat_ids, profiles)
    if hit:
        return hit[0]
    return cat_ids[0] if cat_ids else None


def relation_cat_ids(p):
    """A productExtend inline productCategoryRelations -> [category_id (int)] a
    relacio-id b64-dekodjabol ('productCategory-product_id=X&category_id=Y')."""
    out = []
    for r in (p.get("productCategoryRelations") or []):
        if not isinstance(r, dict):
            continue
        try:
            rid = base64.b64decode(str(r.get("id") or "")).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        for part in rid.split("&"):
            if part.startswith("category_id="):
                try:
                    c = int(part.split("=", 1)[1])
                except ValueError:
                    continue
                if c not in out:
                    out.append(c)
    return out


def printer_params(raw, text, cat_ids):
    """A 'printer' profil kanonizalt parameterei (kf01-kf18 szabalyok, valtozatlan).
    cat_ids: a termek profilba eso kategoriai - a technologia-fallback barmelyikbol johet."""
    params = []
    cat_id = next((c for c in cat_ids if c in TECH_BY_CAT), (cat_ids[0] if cat_ids else None))

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
    return params


PROFILE_PARAMS = {"printer": printer_params}


def generic_params(raw, skip=(), max_vals=MAX_ATTR_VALUES):
    """kfcat/1: MINDEN kitoltott attributum nyersen, nev szerint (nincs termek-tudas)."""
    params = []
    for name in sorted(raw):
        if name in skip:
            continue
        for v in raw[name][:max_vals]:
            v = str(v).strip()
            if v:
                params.append({"name": name, "value": v})
    return params


def norm_profiles(cfg):
    """search_config.shoprenter.profiles -> [{name, cats:set, require:set}]."""
    out = []
    for pr in (cfg.get("profiles") or []):
        if not isinstance(pr, dict):
            continue
        name = str(pr.get("profile") or "").strip().lower()
        if name not in PROFILE_PARAMS:
            continue
        cats = set()
        for c in (pr.get("categories") or []):
            try:
                cats.add(int(c))
            except (TypeError, ValueError):
                pass
        req = {str(a).strip() for a in (pr.get("require_any_attr") or []) if str(a).strip()}
        if not req and "require_any_attr" not in pr and name == "printer":
            req = set(CORE_ATTRS)   # alap: nyomtato = van funkcio/technologia attr
        out.append({"name": name, "cats": cats, "require": req})
    return out


def map_product(p, wanted=(), profiles=(), cat_names=None, skip_attrs=INTERNAL_ATTRS):
    """Nyers SR productExtend -> feed-alaku rekord; None = kiszurve.

    kfcat/1 (generikus): status=0 kiesik; ha van `wanted` kategoria-lista, a
    termeknek abban kell lennie; a profilhoz tartozo termek a profil kanonizalt
    parametereit kapja ES a nyers attributumokat is; profil `require_any_attr`
    eseten a termek csak akkor marad, ha legalabb egy ilyen attributuma kitoltott
    (ez valtja a regi CORE/SUPPLY heurisztikat: a hibas kellek-attributumu
    nyomtato bent marad, a funkcio nelkuli kellek kiesik).
    """
    if str(p.get("status") or "") == "0":
        return None
    cat_ids = relation_cat_ids(p)
    wanted = [int(c) for c in wanted] if wanted else []
    if wanted and not any(c in cat_ids for c in wanted):
        return None
    raw = collect_attrs(p, skip=skip_attrs)
    pr, pr_cats = profile_for(cat_ids, profiles)
    if pr is not None and pr["require"] and not (set(raw) & pr["require"]):
        return None
    pd = (p.get("productDescriptions") or [{}])
    pd = pd[0] if pd and isinstance(pd[0], dict) else {}
    text = desc_text(p)
    params = []
    if pr is not None:
        params.extend(PROFILE_PARAMS[pr["name"]](raw, text, pr_cats))
    # a profil altal KANONIZALT nevek arnyekoljak a nyers attributumot (kulonben a
    # 'funkciok' facetbe a nyers 'Nyomtat, Masol, ...' osszevont ertek is bekerulne)
    owned = {d["name"] for d in params}
    params.extend(generic_params(raw, skip=set(skip_attrs) | owned))
    cat_id = pick_category(cat_ids, wanted, profiles)
    price, orig = extract_price(p)
    stock = 0.0
    for i in (1, 2, 3, 4):
        stock += _num(p.get("stock%d" % i)) or 0
    ua = p.get("urlAliases") or []
    alias = ua[0].get("urlAlias") if ua and isinstance(ua[0], dict) else ""
    manuf = p.get("manufacturer")
    names = cat_names or {}
    return {
        "id": p.get("innerId", ""),
        "sku": str(p.get("sku") or ""),
        "name": str(pd.get("name") or "").strip(),
        "brand": canon_brand((manuf or {}).get("name") if isinstance(manuf, dict) else "", raw),
        "category": str(names.get(cat_id) or (cat_id if cat_id is not None else "")),
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
async def fetch_category_names(base, headers, client):
    """/categoryExtend?full=1 KOLLEKCIO (200/lap) -> {category_id: nev}.
    (A /categories csak href-stubot ad; a per-kategoria hivas felesleges.)"""
    names = {}
    for page in range(_MAX_CAT_PAGES):
        for attempt in range(4):
            try:
                r = await client.get(base + "/categoryExtend",
                                     params={"full": 1, "limit": 200, "page": page},
                                     headers=headers)
                if r.status_code == 429 or r.status_code >= 500:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                body = r.json()
                break
            except httpx.HTTPError:
                await asyncio.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError("Shoprenter: categoryExtend tartos hiba (page %d)" % page)
        items = body.get("items") or (body.get("response") or {}).get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                cid = int(str(it.get("innerId") or "").strip())
            except ValueError:
                continue
            cds = it.get("categoryDescriptions") or []
            nm = cds[0].get("name") if cds and isinstance(cds[0], dict) else ""
            names[cid] = str(nm or cid).strip()
        await asyncio.sleep(_SLEEP)
        if not items or len(items) < 200:
            break
    return names


async def fetch(tenant, tcfg=None):
    """(products_feed_alaku, url_prefix, img_prefix) egy Shoprenter tenantra.

    kfcat/1: a termekek a /productExtend?full=1 KOLLEKCIOBOL jonnek, lapozva,
    4 parhuzamos lappal (platform_api.shoprenter_list_products - ugyanaz a
    primitiv, amit a chatbot-sync naponta futtat), NEM termekenkent.
    `categories` ures -> TELJES katalogus; adott -> szures a relaciokbol.
    Merve (copygo, 2026-08-27): 302 lap x 12 MB, 4 parhuzammal ~17 perc.
    """
    cfg = (tcfg or {}).get("shoprenter") or {}
    wanted = []
    for c in (cfg.get("categories") or []):
        try:
            wanted.append(int(c))
        except (TypeError, ValueError):
            pass
    profiles = norm_profiles(cfg)
    skip_attrs = set(INTERNAL_ATTRS)
    for a in (cfg.get("skip_attrs") or []):
        if str(a).strip():
            skip_attrs.add(str(a).strip())
    conc = int(cfg.get("concurrency") or _CONCURRENCY)
    base = str(tenant.api_base or "").strip().rstrip("/")
    shop = shoprenter_shop(base)
    cid = str(tenant.api_client_id or "").strip()
    sec = str(tenant.api_client_secret or "").strip()
    pub = str(tenant.public_url or "").strip().rstrip("/")
    if not pub:
        raise RuntimeError("Shoprenter: nincs public_url")
    url_prefix = pub + "/"
    img_prefix = pub + "/custom/" + shop + "/image/cache/w300h300wt1/"

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        token = await shoprenter_token(client, shop, cid, sec)
        if not token:
            raise RuntimeError("Shoprenter: nincs token")
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        cat_names = await fetch_category_names(base, headers, client)

    products = []
    seen = 0
    dropped = {"status0": 0, "not_in_cats": 0, "require": 0}
    async for page in shoprenter_list_products(base, cid, sec, full=1, concurrency=conc):
        for p in page:
            seen += 1
            rec = map_product(p, wanted, profiles, cat_names, skip_attrs)
            if rec is None:
                if str(p.get("status") or "") == "0":
                    dropped["status0"] += 1
                elif wanted and not any(c in relation_cat_ids(p) for c in wanted):
                    dropped["not_in_cats"] += 1
                else:
                    dropped["require"] += 1
                continue
            products.append(rec)
    print("shoprenter-diag %s seen=%d kept=%d dropped=%s cats=%s profiles=%s" % (
        tenant.client_id, seen, len(products), dropped,
        wanted or "ALL", [(pr["name"], len(pr["cats"])) for pr in profiles]))
    return products, url_prefix, img_prefix

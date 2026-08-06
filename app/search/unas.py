"""CX SmartSearch - Unas ingest-mapper (S7).

A Unas API erdemben mas, mint a Sellvio/Shoprenter REST: XML keres -> XML valasz,
es login utan Bearer token.

  1. POST {base}/login       body: <Params><ApiKey>..</ApiKey></Params>  -> <Token>
  2. POST {base}/getProduct  Authorization: Bearer <token>, body: <Params>...,
     lapozva (LimitNum/LimitStart), ContentType=full

MIERT getProduct es nem getProductDB: a getProductDB ASZINKRON - egy generalt
CSV-re mutato URL-t ad, ami 1 oraig el, es az oszlopai a kert flagektol fuggenek.
A getProduct XML-je NEVESITETT mezoket ad (Id/Sku/Name/Prices/Categories/Params/
Stocks), ami sokkal kevesbe torekeny. Napi index-buildhez a lapozas belefer a
limitbe (tobb-termekes hivas: PREMIUM 30 hivas/ora, azaz 500-as lappal 15e termek).

Mezo-lekepezes a hivatalos Adatszerkezet szerint
(https://unas.hu/tudastar/api/termekek-adatszerkezet):
  Id, Sku, Name, Url / SefUrl, Categories.Category[Type=base].Name,
  Prices.Price(.Actual) Gross, Images.Image[Type=base], Params.Param,
  Stocks.Status.Active/Empty + Stocks.Stock.Qty, CreateTime, NoList

KET DOLOG, AMI A UNASBAN NINCS, ES ezert heurisztika:
  - GYARTO: a Unasnak nincs dedikalt marka-mezoje, a boltok termek-parameterkent
    viszik ("Gyarto" / "Marka" / "Brand"). A BRAND_PARAMS listabol vesszuk, es
    a felhasznalt parametert kihagyjuk a facetekbol (kulonben duplan latszana).
  - KEP-UTVONAL: az Images.Image.SefUrl lehet abszolut URL vagy bolt-relativ ut;
    mindketto kezelve van (abszolutat valtozatlanul hagyunk - a widget s2-8 ota
    nem fuz ele prefixet).
"""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET

import httpx

DEFAULT_BASE = "https://api.unas.eu/shop"
_TIMEOUT = 120.0
_PAGE = 500
_MAX_PAGES = 200
_SLEEP = 0.4

# csak ezek a statuszok kerulnek az indexbe (0 = inaktiv: meg sem kerjuk le)
STATUS_LIVE = ("1", "2", "3")
# 1 = aktiv, 2 = aktiv+uj -> vasarolhato; 3 = aktiv, de NEM vasarolhato
STATUS_BUYABLE = ("1", "2")

BRAND_PARAMS = ("gyarto", "gyártó", "marka", "márka", "brand", "manufacturer")

# Export-/feed-technikai parameterek: a boltok ezeket is termek-parameterkent
# viszik, de vasarloi szempontnak ertelmetlenek (az EAN ráadásul termekenkent
# egyedi -> szaz erteku facet lenne). A lista boltonkent bovitheto a
# search_config.unas.skip_params kulcsbol.
SKIP_PARAM_EXACT = {"ean", "ean kod", "ean kód", "eankod", "vtsz", "cikkszam",
                    "cikkszám", "basketdisabled", "basket disabled"}
SKIP_PARAM_PREFIX = ("arukereso", "árukereső", "google", "facebook", "glami",
                     "emag", "pepita", "csomagolt ")
SKIP_PARAM_SUBSTR = ("disabled", "export", "feed")


def skip_param(name, extra=()):
    """Kiszurendo-e ez a parameter-nev (kis/nagybetu- es szokoz-turo)."""
    n = " ".join(str(name or "").split()).strip().lower()
    if not n or n in SKIP_PARAM_EXACT or n in extra:
        return True
    if n.startswith(SKIP_PARAM_PREFIX) or any(tok in n for tok in SKIP_PARAM_SUBSTR):
        return True
    # gepi azonosito-mezok (CONNESTIC_ID, productid, sku_kod...): egyetlen szo,
    # amiben alahuzas van vagy "id"-re vegzodik - vasarloi szempontnak sosem az
    return " " not in n and ("_" in n or n.endswith("id"))

_XML_HEAD = '<?xml version="1.0" encoding="UTF-8" ?>'


# --------------------------------------------------------------------------- #
# tiszta (fajlbol tesztelheto) segedek
# --------------------------------------------------------------------------- #
def _t(el, path=None):
    """Egy elem (vagy gyerek) szoveges tartalma, trimmelve; hianyzora ''."""
    node = el if path is None else (el.find(path) if el is not None else None)
    if node is None:
        return ""
    return " ".join((node.text or "").split())


def _num(value):
    """'12990' / '12990.5' -> int/float; ures vagy szemet -> None."""
    s = str(value or "").strip().replace(" ", "").replace("\u00a0", "")
    if not s:
        return None
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def login_body(api_key):
    """A login keres XML-je (a WebshopInfo-t nem kerjuk: nincs ra szuksegunk)."""
    return "%s<Params><ApiKey>%s</ApiKey></Params>" % (_XML_HEAD, _esc(api_key))


def product_body(start, num, lang="hu"):
    """getProduct keres: elo termekek, teljes adattartalom, lapozva.

    A LimitStart 0/1-alapusaga a doksibol nem egyertelmu, ezert a hivo oldalon
    id-re dedupolunk - igy mindket ertelmezes mellett helyes az eredmeny.
    """
    return (
        "%s<Params>"
        "<StatusBase>%s</StatusBase>"
        "<State>live</State>"
        "<ContentType>full</ContentType>"
        "<LimitNum>%d</LimitNum>"
        "<LimitStart>%d</LimitStart>"
        "<Lang>%s</Lang>"
        "</Params>" % (_XML_HEAD, ",".join(STATUS_LIVE), int(num), int(start), _esc(lang))
    )


def _esc(value):
    return (str(value or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def parse_token(xml_text):
    """A login valaszabol a Token; hianyzora RuntimeError (beszedes uzenettel)."""
    root = _root(xml_text)
    token = _t(root, ".//Token")
    if token:
        return token
    err = _t(root, ".//Error") or _t(root, ".//Message")
    raise RuntimeError("Unas login: nincs token%s" % (" (%s)" % err if err else ""))


def _root(xml_text):
    try:
        return ET.fromstring((xml_text or "").strip())
    except ET.ParseError as e:
        raise RuntimeError("Unas: ertelmezhetetlen XML valasz (%s)" % e) from e


def base_status(prod):
    """Statuses.Status[Type=base].Value; hianyzora ''."""
    for st in prod.findall("./Statuses/Status"):
        if _t(st, "Type") == "base":
            return _t(st, "Value")
    return ""


def price_of(prod):
    """(brutto ar, athuzott eredeti ar) a Prices blokkbol.

    Az `Actual` mezo jeloli, hogy a normal es az akcios ar kozul melyik ervenyes
    eppen. Ha az akcios ar az ervenyes, a normal ar lesz az athuzott eredeti.
    """
    normal = actual = None
    for pr in prod.findall("./Prices/Price"):
        gross = _num(_t(pr, "Gross"))
        if gross is None:
            continue
        ptype = _t(pr, "Type")
        if ptype == "normal":
            normal = gross
        if _t(pr, "Actual"):
            actual = (ptype, gross)
    if actual is None:
        return normal, None
    ptype, gross = actual
    if ptype != "normal" and normal is not None and normal > gross:
        return gross, normal
    return gross, None


def stock_of(prod):
    """(keszletkezeles aktiv?, ossz-mennyiseg, ures-is-vasarolhato?)."""
    active = _t(prod, "./Stocks/Status/Active") == "1"
    empty_ok = _t(prod, "./Stocks/Status/Empty") == "1"
    qty = 0.0
    for st in prod.findall("./Stocks/Stock"):
        qty += _num(_t(st, "Qty")) or 0
    return active, qty, empty_ok


def is_available(prod):
    """Vasarolhato-e MOST: statusz + (ha van keszletkezeles) keszlet."""
    if base_status(prod) not in STATUS_BUYABLE:
        return False
    active, qty, empty_ok = stock_of(prod)
    if active and not empty_ok:
        return qty > 0
    return True


def params_of(prod, skip_ids=(), skip_names=()):
    """Params.Param -> [{'name','value'}].

    Kiesik: az ures ertek, a markakent mar felhasznalt parameter (kulonben
    duplan latszana) es az export-/feed-technikai mezo (skip_param).
    """
    out = []
    for p in prod.findall("./Params/Param"):
        name = _t(p, "Name")
        value = _t(p, "Value")
        if not name or not value or _t(p, "Id") in skip_ids:
            continue
        if skip_param(name, skip_names):
            continue
        out.append({"name": name, "value": value})
    return out


def brand_of(prod):
    """(marka, a marka-parameter Id-ja) - a Unasban nincs dedikalt marka-mezo."""
    for p in prod.findall("./Params/Param"):
        if _t(p, "Name").strip().lower() in BRAND_PARAMS:
            value = _t(p, "Value")
            if value:
                return value, _t(p, "Id")
    return "", ""


def leaf_category(name):
    """'Otthon es kert |Kerti gepek| Lombszivo' -> 'Lombszivo'.

    A Unas a kategoria-nevben a TELJES utvonalat adja (a pipe-ok korul a szokoz
    nem konzisztens), a facethez viszont a legmelyebb szint kell - ugyanaz a
    szabaly, mint a Sellvio kategoria-fajanal.
    """
    parts = [" ".join(p.split()) for p in str(name or "").split("|")]
    parts = [p for p in parts if p]
    return parts[-1] if parts else ""


def category_of(prod):
    """Az ALAP kategoria LEGMELYEBB szintje (alt = masodlagos, csak fallback)."""
    first = ""
    for c in prod.findall("./Categories/Category"):
        name = leaf_category(_t(c, "Name"))
        if not name:
            continue
        if _t(c, "Type") == "base":
            return name
        first = first or name
    return first


def image_of(prod):
    """Az alapertelmezett termekkep utvonala (SefUrl > Filename)."""
    fallback = ""
    for im in prod.findall("./Images/Image"):
        path = _t(im, "SefUrl") or _t(im, "Filename")
        if not path:
            continue
        if _t(im, "Type") == "base":
            return path
        fallback = fallback or path
    return fallback or _t(prod, "./Images/DefaultFilename")


def created_day(prod):
    """CreateTime (unix ts) -> unix-nap; hianyzora None (az Uj-badge-hez)."""
    ts = _num(_t(prod, "CreateTime"))
    if ts is None or ts <= 0:
        return None
    return int(ts // 86400)


def map_product(prod, skip_names_extra=()):
    """Egy <Product> elem -> feed-alaku rekord; None = nem kerul az indexbe.

    Kiesik: az inaktiv termek es az, amit a bolt szandekosan elrejtett a
    listakbol/keresobol (NoList=1).
    """
    if base_status(prod) not in STATUS_LIVE:
        return None
    if _t(prod, "NoList") == "1":
        return None
    pid = _t(prod, "Id") or _t(prod, "Sku")
    name = _t(prod, "Name")
    if not pid or not name:
        return None
    brand, brand_id = brand_of(prod)
    price, orig = price_of(prod)
    skip_names = tuple(skip_names_extra or ())
    return {
        "id": pid,
        "sku": _t(prod, "Sku"),
        "name": name,
        "brand": brand,
        "category": category_of(prod),
        "price_gross": price,
        "orig_price": orig,
        "available": is_available(prod),
        "url": _t(prod, "Url") or _t(prod, "SefUrl"),
        "image_url": image_of(prod),
        "parameters": params_of(prod, skip_ids=(brand_id,) if brand_id else (),
                                skip_names=skip_names),
        "created_day": created_day(prod),
    }


def parse_products(xml_text, skip_names_extra=()):
    """getProduct valasz -> feed-alaku rekordok (a kiszurtek nelkul)."""
    root = _root(xml_text)
    err = _t(root, ".//Error")
    if err:
        raise RuntimeError("Unas getProduct: %s" % err)
    out = []
    for prod in root.findall(".//Product"):
        rec = map_product(prod, skip_names_extra)
        if rec is not None:
            out.append(rec)
    return out


def count_products(xml_text):
    """Hany <Product> jott vissza (a szures ELOTT) - a lapozas ezen all."""
    return len(_root(xml_text).findall(".//Product"))


def api_key(tenant, tcfg=None):
    """A Unas API kulcs: tcfg.unas.api_key > api_client_secret > api_client_id."""
    key = str(((tcfg or {}).get("unas") or {}).get("api_key") or "").strip()
    return key or str(getattr(tenant, "api_client_secret", "") or "").strip() \
        or str(getattr(tenant, "api_client_id", "") or "").strip()


def prefixes(tenant, tcfg=None):
    """(url_prefix, img_prefix) - mindketto a bolt sajat domainjere mutat."""
    cfg = (tcfg or {}).get("unas") or {}
    pub = str(cfg.get("url_prefix") or getattr(tenant, "public_url", "") or "").strip()
    if not pub:
        dom = str(getattr(tenant, "domain", "") or "").strip()
        if dom:
            pub = "https://" + dom.split(",")[0].strip().lstrip("/")
    if not pub:
        raise RuntimeError("Unas: nincs public_url/domain a tenanton")
    pub = pub.rstrip("/") + "/"
    return pub, str(cfg.get("img_prefix") or pub).rstrip("/") + "/"


def base_url(tenant):
    """A Unas API host.

    A tenants.api_base-ben tobb boltnal a SAJAT shop-domain van beirva (a
    smartzillanal emiatt a /login 302-t adott es ertelmezhetetlen valaszt) -
    ezert csak akkor fogadjuk el, ha tenyleg unas.eu API-host.
    """
    base = str(getattr(tenant, "api_base", "") or "").strip().rstrip("/")
    return base if "unas.eu" in base else DEFAULT_BASE


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
async def fetch(tenant, tcfg=None):
    """(products_feed_alaku, url_prefix, img_prefix) egy Unas tenantra."""
    key = api_key(tenant, tcfg)
    if not key:
        raise RuntimeError("Unas: nincs API kulcs (search_config.unas.api_key "
                           "vagy tenants.api_client_secret)")
    cfg = (tcfg or {}).get("unas") or {}
    lang = str(cfg.get("lang") or "hu").strip() or "hu"
    page = max(1, min(int(cfg.get("page_size") or _PAGE), 1000))
    skip_extra = tuple(" ".join(str(x).split()).lower()
                       for x in (cfg.get("skip_params") or []) if str(x).strip())
    base = base_url(tenant)
    url_prefix, img_prefix = prefixes(tenant, tcfg)

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        r = await client.post(base + "/login", content=login_body(key).encode("utf-8"),
                              headers={"Content-Type": "application/xml"})
        r.raise_for_status()
        token = parse_token(r.text)
        headers = {"Authorization": "Bearer " + token,
                   "Content-Type": "application/xml"}

        products, seen, start = [], set(), 0
        for _ in range(_MAX_PAGES):
            body = product_body(start, page, lang).encode("utf-8")
            for attempt in range(4):
                resp = await client.post(base + "/getProduct", content=body, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                break
            else:
                raise RuntimeError("Unas: tartos hiba a getProduct-on (start=%d)" % start)

            got = count_products(resp.text)
            fresh = 0
            for rec in parse_products(resp.text, skip_extra):
                if rec["id"] in seen:
                    continue
                seen.add(rec["id"])
                products.append(rec)
                fresh += 1
            if got == 0 or (fresh == 0 and got < page):
                break
            start += got
            if got < page:
                break
            await asyncio.sleep(_SLEEP)

    print("unas-diag %s: %d termek (%d lap-kore)" % (
        getattr(tenant, "client_id", "?"), len(products), start // page + 1))
    return products, url_prefix, img_prefix

"""kf/16: kapcsolat-teszt (search_probe) — a bekapcsolás-varázsló 1. lépéséhez.

MIÉRT: a varázsló 1. lépése eddig csak azt látta, hogy az API-mezők ki vannak-e
TÖLTVE — azt nem, hogy a kulcs MŰKÖDIK-e. Az csak az index-buildnél derült ki,
percekkel később, hibás manifesttel. Új partner bekapcsolásánál ez volt a
leglassabb visszacsatolás.

KÖNNYŰ PRÓBA: token-kérés + EGY lapnyi termék. A platform-kliensek `fetch()`-ét
TILOS hívni — az a teljes katalógust húzza le (Shoprenteren ~7 perc, 22e termék).

A modul stdlib-only és fájl-betöltéssel tesztelhető (kf/9 + kf/13 minta): a
HTTP-klienst a hívó adja be (`client`), így a tesztek fake klienssel futnak, és
nincs httpx-függőség modul szinten. A `probe()` SOHA nem dob kivételt.

Visszatérés (a hívó még client_id-t tesz rá):
    {ok, platform, shop, product_count, sample, error, detail, warn, ms}
  product_count = a katalógus TÉNYLEGES darabszáma, ha az API megadja; különben
  None — a próba nem számolja végig, mert az már nem lenne könnyű.
  sample        = ahány terméket a próba ténylegesen visszakapott (0 vagy 1).
"""
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

PLATFORMS = ("shoprenter", "sellvio", "unas", "webdoc")
PLATFORM_LIST = "Shoprenter, Sellvio, Unas, Webdoc"

UNAS_BASE = "https://api.unas.eu/shop"
SR_TOKEN_URL = "https://oauth.app.shoprenter.net/%s/app/token"

TIMEOUT = 20.0              # ajánlás a hívó httpx-kliensére
FEED_PREFIX_BYTES = 65536   # webdoc: ennyit olvasunk a feedből, nem többet

# platformonként MELY tenant-mezők kellenek
REQUIRED = {
    "shoprenter": ("api_base", "api_client_id", "api_client_secret", "public_url"),
    "sellvio": ("api_base", "api_client_id", "api_client_secret"),
    "unas": ("api_client_secret",),
    "webdoc": ("api_base",),
}
LABEL = {
    "api_base": "API cím",
    "api_client_id": "client id",
    "api_client_secret": "client secret / API-kulcs",
    "public_url": "bolt URL (public_url)",
}

_UNAS_ONE = ('<?xml version="1.0" encoding="UTF-8" ?><Params>'
             "<StatusBase>1,2,3</StatusBase><State>live</State>"
             "<ContentType>full</ContentType><LimitNum>1</LimitNum>"
             "<LimitStart>0</LimitStart><Lang>hu</Lang></Params>")


# --------------------------------------------------------------------------- #
# tiszta (fájlból tesztelhető) segédek
# --------------------------------------------------------------------------- #
def _s(tenant, name):
    return str(getattr(tenant, name, "") or "").strip()


def _int(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _esc(v):
    return str(v or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short(e):
    return ("%s: %s" % (type(e).__name__, e))[:120]


def platform_of(tenant):
    return _s(tenant, "platform").lower()


def supported(platform):
    return str(platform or "").strip().lower() in PLATFORMS


def shop_of(api_base):
    """{bolt}.api2.myshoprenter.hu/api -> bolt (a platform_api tükre)."""
    host = urlsplit(str(api_base or "")).hostname or ""
    return host.split(".")[0] if host else ""


def unas_base(api_base):
    """A Unas API host. Több boltnál a saját shop-domain van az api_base-ben."""
    b = str(api_base or "").strip().rstrip("/")
    return b if "unas.eu" in b else UNAS_BASE


def sr_categories(cfg):
    """search_config.shoprenter.categories -> int lista (hibás elem kiesik)."""
    sr = cfg.get("shoprenter") if isinstance(cfg, dict) else None
    sr = sr if isinstance(sr, dict) else {}
    out = []
    for c in (sr.get("categories") or []):
        n = _int(str(c).strip() or None)
        if n is not None:
            out.append(n)
    return out


def creds(tenant, tcfg=None):
    """A próbához szükséges, normalizált mezők egy dictben."""
    cfg = tcfg if isinstance(tcfg, dict) else {}
    unas_cfg = cfg.get("unas") if isinstance(cfg.get("unas"), dict) else {}
    base = _s(tenant, "api_base").rstrip("/")
    pub = _s(tenant, "public_url").rstrip("/")
    if not pub:
        dom = _s(tenant, "domain").split(",")[0].strip().strip("/")
        pub = ("https://" + dom) if dom else ""
    return {
        "api_base": base,
        "api_client_id": _s(tenant, "api_client_id"),
        "api_client_secret": _s(tenant, "api_client_secret"),
        "public_url": pub,
        "shop": shop_of(base),
        "unas_base": unas_base(base),
        # a unas.api_key() tükre: tcfg.unas.api_key > secret > client_id
        "unas_key": (str(unas_cfg.get("api_key") or "").strip()
                     or _s(tenant, "api_client_secret")
                     or _s(tenant, "api_client_id")),
        "feed_url": str(cfg.get("feed_url") or base or "").strip(),
        "sr_categories": sr_categories(cfg),
    }


def missing(platform, c):
    """Emberi címkék a hiányzó kötelező mezőkről."""
    out = []
    for f in REQUIRED.get(str(platform or "").lower(), ()):
        if platform == "unas" and f == "api_client_secret":
            if not c.get("unas_key"):
                out.append("API-kulcs")
            continue
        if not c.get(f):
            out.append(LABEL.get(f, f))
    return out


# --- válasz-értelmezők -------------------------------------------------------
def sellvio_shape(body):
    """(product_count|None, sample) a Laravel-paginator válaszból."""
    data = body.get("data") if isinstance(body, dict) else None
    data = data if isinstance(data, dict) else {}
    items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
    return _int(data.get("total")), len(items)


_SR_COUNT_KEYS = ("count", "itemCount", "total", "itemsTotal")


def sr_shape(body, limit=None):
    """(product_count|None, sample) a Shoprenter lista-válaszból.

    kf/16a: a Shoprenter NEM ad darabszám-mezőt, viszont ad `pageCount`-ot, és
    limit=1 mellett az PONTOSAN a termékek száma. Mérve 2026-08-07-én mind a 4
    SR bolton (copygo 59740 = 2987*20, acpont 1335 = 67*20 = ceil(/200)*..,
    ecowindoor 140, horgaszoutlet 128685) — ezért csak limit=1-nél használjuk.
    """
    body = body if isinstance(body, dict) else {}
    inner = body.get("response") if isinstance(body.get("response"), dict) else {}
    items = [i for i in (body.get("items") or inner.get("items") or []) if isinstance(i, dict)]
    for src in (body, inner):
        for k in _SR_COUNT_KEYS:
            n = _int(src.get(k))
            if n is not None:
                return n, len(items)
    if limit == 1:
        for src in (body, inner):
            n = _int(src.get("pageCount"))
            if n is not None:
                return n, len(items)
    return None, len(items)


def _xml(text):
    try:
        return ET.fromstring(str(text or "").strip())
    except ET.ParseError:
        return None


def _xml_text(root, *names):
    wanted = {n.lower() for n in names}
    for sub in root.iter():
        if sub.tag.split("}")[-1].lower() in wanted and sub.text and sub.text.strip():
            return sub.text.strip()
    return ""


def unas_token(xml_text):
    root = _xml(xml_text)
    return _xml_text(root, "Token") if root is not None else ""


def unas_error(xml_text):
    root = _xml(xml_text)
    if root is None:
        return ""
    return _xml_text(root, "Error") or _xml_text(root, "Message")


def unas_sample(xml_text):
    root = _xml(xml_text)
    return len(root.findall(".//Product")) if root is not None else 0


def feed_looks_json(prefix):
    """A feed első bájtjai JSON-objektummal/tömbbel kezdődnek-e."""
    if isinstance(prefix, (bytes, bytearray)):
        prefix = bytes(prefix).decode("utf-8", "ignore")
    return str(prefix or "").lstrip("\ufeff \t\r\n")[:1] in ("{", "[")


def status_error(code):
    """HTTP státusz -> (gépi hibakód, emberi mondat). 2xx -> (None, "")."""
    c = _int(code) or 0
    if 200 <= c < 300:
        return None, ""
    if c in (401, 403):
        return "auth_failed", ("A webshop elutasította a hozzáférést (%d) — "
                               "a kulcs vagy a jogosultság nem jó." % c)
    if c == 404:
        return "http_error", "Nincs ilyen API-végpont (404) — nézd meg az API címet."
    if c == 429:
        return "http_error", "A webshop most korlátoz (429) — próbáld pár perc múlva."
    if c >= 500:
        return "http_error", "A webshop API hibát adott (%d) — most nem elérhető." % c
    return "http_error", "A webshop API-ja %d-t adott vissza." % c


def ok_detail(product_count, sample):
    if product_count is not None:
        return "Kapcsolat rendben — a webshop %d terméket jelez." % product_count
    if sample:
        return ("Kapcsolat rendben — a termék-lekérés is működik "
                "(%d minta-termék jött vissza)." % sample)
    return "Kapcsolat rendben — a hitelesítés sikerült."


def _res(platform, ok, error=None, detail="", shop="",
         product_count=None, sample=None, warn=""):
    return {"ok": bool(ok), "platform": str(platform or ""), "error": error or None,
            "detail": detail, "shop": shop or None,
            "product_count": product_count, "sample": sample, "warn": warn or None}


def _ok(platform, product_count, sample, shop=""):
    warn = ""
    if not product_count and not sample:
        warn = ("A hitelesítés sikerült, de a próba 0 terméket kapott — "
                "nézd meg a szűrőket vagy a kategória-listát.")
    return _res(platform, True, None, ok_detail(product_count, sample),
                shop=shop, product_count=product_count, sample=sample, warn=warn)


# --------------------------------------------------------------------------- #
# platform-próbák (a klienst a hívó adja)
# --------------------------------------------------------------------------- #
def _json(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001 — nem-JSON válasz
        return None


async def _probe_sellvio(client, c):
    base = c["api_base"]
    r = await client.post(base + "/oauth/token", data={
        "grant_type": "client_credentials",
        "client_id": c["api_client_id"],
        "client_secret": c["api_client_secret"]})
    err, msg = status_error(getattr(r, "status_code", 0))
    if err:
        return _res("sellvio", False, err, msg)
    token = str((_json(r) or {}).get("access_token") or "")
    if not token:
        return _res("sellvio", False, "auth_failed",
                    "A Sellvio nem adott hozzáférési kulcsot (access_token) — "
                    "nézd meg a client id / secret párost.")
    r2 = await client.get(base + "/api/v2/products",
                          params={"page": 1, "limit": 1, "locale": "hu"},
                          headers={"Authorization": "Bearer " + token,
                                   "Accept": "application/json"})
    err, msg = status_error(getattr(r2, "status_code", 0))
    if err:
        return _res("sellvio", False, err, msg)
    cnt, sample = sellvio_shape(_json(r2))
    return _ok("sellvio", cnt, sample)


async def _probe_shoprenter(client, c):
    shop = c["shop"]
    if not shop:
        return _res("shoprenter", False, "missing_fields",
                    "Az API címből nem olvasható ki a bolt azonosítója "
                    "(várt alak: <bolt>.api2.myshoprenter.hu/api).")
    r = await client.post(SR_TOKEN_URL % shop, json={
        "grant_type": "client_credentials",
        "client_id": c["api_client_id"],
        "client_secret": c["api_client_secret"]})
    err, msg = status_error(getattr(r, "status_code", 0))
    if err:
        return _res("shoprenter", False, err, msg, shop=shop)
    token = str((_json(r) or {}).get("access_token") or "")
    if not token:
        return _res("shoprenter", False, "auth_failed",
                    "A Shoprenter nem adott hozzáférési kulcsot — nézd meg a "
                    "client id / secret párost.", shop=shop)
    r2 = await client.get(c["api_base"] + "/productExtend",
                          params={"full": 0, "limit": 1, "page": 0},
                          headers={"Authorization": "Bearer " + token,
                                   "Accept": "application/json"})
    err, msg = status_error(getattr(r2, "status_code", 0))
    if err:
        return _res("shoprenter", False, err, msg, shop=shop)
    cnt, sample = sr_shape(_json(r2), limit=1)   # kf/16a: pageCount == termékszám
    out = _ok("shoprenter", cnt, sample, shop=shop)
    if cnt is not None:
        out["detail"] += (" Ez a teljes katalógus — az index csak a beállított "
                          "kategóriákra szűr.")
    if not c["sr_categories"]:
        # kf/6 tanulsága: kategória-lista nélkül a build "nincs kategoria-lista"-ra hasal el
        out["warn"] = ("A kapcsolat jó, de nincs kategória-lista "
                       "(search_config.shoprenter.categories) — enélkül az "
                       "index-build hibára fut.")
    return out


async def _probe_unas(client, c):
    base = c["unas_base"]
    body = ('<?xml version="1.0" encoding="UTF-8" ?>'
            "<Params><ApiKey>%s</ApiKey></Params>" % _esc(c["unas_key"]))
    r = await client.post(base + "/login", content=body.encode("utf-8"),
                          headers={"Content-Type": "application/xml"})
    err, msg = status_error(getattr(r, "status_code", 0))
    if err:
        return _res("unas", False, err, msg)
    text = getattr(r, "text", "") or ""
    token = unas_token(text)
    if not token:
        e = unas_error(text)
        return _res("unas", False, "auth_failed",
                    "A Unas nem adott tokent%s — nézd meg az API-kulcsot."
                    % ((" (%s)" % e) if e else ""))
    r2 = await client.post(base + "/getProduct", content=_UNAS_ONE.encode("utf-8"),
                           headers={"Authorization": "Bearer " + token,
                                    "Content-Type": "application/xml"})
    err, msg = status_error(getattr(r2, "status_code", 0))
    if err:
        return _res("unas", False, err, msg)
    t2 = getattr(r2, "text", "") or ""
    e2 = unas_error(t2)
    if e2:
        return _res("unas", False, "bad_response", "A Unas hibát adott: %s" % e2)
    return _ok("unas", None, unas_sample(t2))


async def _feed_prefix(client, url, limit=FEED_PREFIX_BYTES):
    """(státusz, első <limit> bájt) — a feedet SZÁNDÉKOSAN nem töltjük le egészben."""
    async with client.stream("GET", url, headers={
            "Accept": "application/json",
            "User-Agent": "cx-konfprobe/1.0"}) as resp:
        status = getattr(resp, "status_code", 0)
        buf = b""
        if 200 <= (_int(status) or 0) < 300:
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) >= limit:
                    break
        return status, buf[:limit]


async def _probe_webdoc(client, c):
    url = c["feed_url"]
    if not url.lower().startswith(("http://", "https://")):
        return _res("webdoc", False, "missing_fields",
                    "A feed címe nem http(s) URL (tenants.api_base vagy "
                    "search_config.feed_url).")
    status, prefix = await _feed_prefix(client, url)
    err, msg = status_error(status)
    if err:
        return _res("webdoc", False, err, msg)
    if not feed_looks_json(prefix):
        return _res("webdoc", False, "bad_response",
                    "A feed elérhető, de nem JSON-nal kezdődik — rossz cím, vagy "
                    "beléptető oldal jön vissza.")
    return _res("webdoc", True, None,
                "Kapcsolat rendben — a termék-feed elérhető és JSON. A darabszám "
                "csak a teljes letöltésből derülne ki, azt a próba nem tölti le.")


_PROBES = {
    "sellvio": _probe_sellvio,
    "shoprenter": _probe_shoprenter,
    "unas": _probe_unas,
    "webdoc": _probe_webdoc,
}


async def probe(tenant, tcfg=None, client=None):
    """Könnyű kapcsolat-teszt egy tenantra. SOHA nem dob kivételt."""
    t0 = time.monotonic()
    platform = platform_of(tenant)
    if not platform or platform == "egyeb":
        return _stamp(_res(platform, False, "no_platform",
                           "Nincs kiválasztva platform a partneren — enélkül nem "
                           "tudunk termékindexet építeni."), t0)
    if not supported(platform):
        return _stamp(_res(platform, False, "unsupported",
                           "A(z) %s platformhoz nincs index-építő (támogatott: %s)."
                           % (platform, PLATFORM_LIST)), t0)
    c = creds(tenant, tcfg)
    miss = missing(platform, c)
    if miss:
        return _stamp(_res(platform, False, "missing_fields",
                           "Hiányzik: %s." % ", ".join(miss), shop=c["shop"]), t0)
    if client is None:
        return _stamp(_res(platform, False, "no_client",
                           "Nincs HTTP-kliens a próbához."), t0)
    try:
        out = await _PROBES[platform](client, c)
    except Exception as e:  # noqa: BLE001 — a próba sosem dobhat az adminra
        out = _res(platform, False, "network",
                   "Nem sikerült elérni a webshop API-ját (%s)." % _short(e))
    return _stamp(out, t0)


def _stamp(out, t0):
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out

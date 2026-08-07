"""kf/16: a kapcsolat-teszt (search_probe) tesztjei.

A modul stdlib-only, ezért az app-csomag betöltése nélkül teszteljük (a suite
más tesztjei fake `app.services`-t hagyhatnak a sys.modules-ben) — kf/9 + kf/13
minta. A HTTP-klienst a probe() kívülről kapja, így fake klienssel fut.
"""
import importlib.util
import json
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konfprobe.py"
_spec = importlib.util.spec_from_file_location("konfprobe_under_test", _P)
kp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kp)


# --------------------------------------------------------------------------- #
# fake tenant / fake HTTP-kliens
# --------------------------------------------------------------------------- #
class T:
    def __init__(self, **kw):
        self.platform = kw.get("platform", "")
        self.api_base = kw.get("api_base", "")
        self.api_client_id = kw.get("api_client_id", "")
        self.api_client_secret = kw.get("api_client_secret", "")
        self.public_url = kw.get("public_url", "")
        self.domain = kw.get("domain", "")


class R:
    """Fake válasz: status + JSON payload vagy nyers szöveg."""

    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else (
            json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("nem JSON")
        return self._payload


class _StreamCM:
    def __init__(self, resp):
        self._r = resp

    async def __aenter__(self):
        return self._r

    async def __aexit__(self, *a):
        return False


class S:
    """Fake stream-válasz (webdoc feed)."""

    def __init__(self, status=200, body=b""):
        self.status_code = status
        self._body = body
        self.read_bytes = 0

    async def aiter_bytes(self):
        for i in range(0, len(self._body), 8):
            chunk = self._body[i:i + 8]
            self.read_bytes += len(chunk)
            yield chunk


class C:
    """Fake httpx-kliens: URL-részlet -> válasz. Rögzíti a hívásokat."""

    def __init__(self, posts=None, gets=None, stream=None, raise_on=""):
        self.posts = posts or {}
        self.gets = gets or {}
        self.stream_resp = stream
        self.raise_on = raise_on
        self.calls = []

    def _pick(self, table, url):
        for k, v in table.items():
            if k in url:
                return v
        raise AssertionError("váratlan URL a próbában: %s" % url)

    async def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if self.raise_on and self.raise_on in url:
            raise RuntimeError("halozati hiba")
        return self._pick(self.posts, url)

    async def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if self.raise_on and self.raise_on in url:
            raise RuntimeError("halozati hiba")
        return self._pick(self.gets, url)

    def stream(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.raise_on and self.raise_on in url:
            raise RuntimeError("halozati hiba")
        return _StreamCM(self.stream_resp)

    def params(self, needle):
        for _m, url, kw in self.calls:
            if needle in url:
                return kw.get("params") or {}
        return {}


SR = T(platform="shoprenter", api_base="https://copygo.api2.myshoprenter.hu/api",
       api_client_id="cid", api_client_secret="sec", public_url="https://copygo.hu")
SV = T(platform="sellvio", api_base="https://teslashop.hu",
       api_client_id="cid", api_client_secret="sec")
UN = T(platform="unas", api_base="https://api.unas.eu/shop", api_client_secret="kulcs")
WD = T(platform="webdoc", api_base="https://notebookstore.hu/feed.json",
       public_url="https://notebookstore.hu")


# --------------------------------------------------------------------------- #
# tiszta segédek
# --------------------------------------------------------------------------- #
def test_platform_es_tamogatottsag():
    assert kp.platform_of(T(platform=" ShopRenter ")) == "shoprenter"
    assert kp.platform_of(T()) == ""
    assert kp.supported("unas") and kp.supported("WEBDOC")
    assert not kp.supported("woocommerce")
    assert not kp.supported("")


def test_shop_of():
    assert kp.shop_of("https://copygo.api2.myshoprenter.hu/api") == "copygo"
    assert kp.shop_of("https://copygo.api.myshoprenter.hu") == "copygo"
    assert kp.shop_of("") == ""
    assert kp.shop_of("nem-url") == ""


def test_unas_base_csak_unas_hostot_fogad_el():
    assert kp.unas_base("https://api.unas.eu/shop/") == "https://api.unas.eu/shop"
    # a smartzilla-eset: sajat shop-domain az api_base-ben -> a hivatalos hostra esunk vissza
    assert kp.unas_base("https://smartzilla.hu") == kp.UNAS_BASE
    assert kp.unas_base("") == kp.UNAS_BASE


def test_sr_categories():
    cfg = {"shoprenter": {"categories": [3408, "3420", "", None, "xx"]}}
    assert kp.sr_categories(cfg) == [3408, 3420]
    assert kp.sr_categories({}) == []
    assert kp.sr_categories(None) == []
    assert kp.sr_categories({"shoprenter": "nem-dict"}) == []


def test_creds_public_url_domainbol():
    c = kp.creds(T(platform="shoprenter", api_base="https://x.api2.myshoprenter.hu/api/",
                   domain="copygo.hu, www.copygo.hu"))
    assert c["api_base"].endswith("/api")          # a zaro / levagva
    assert c["public_url"] == "https://copygo.hu"  # domain-fallback, elso elem
    assert c["shop"] == "x"


def test_creds_unas_kulcs_sorrend():
    # tcfg.unas.api_key nyer
    c = kp.creds(T(platform="unas", api_client_secret="sec", api_client_id="cid"),
                 {"unas": {"api_key": "cfgkey"}})
    assert c["unas_key"] == "cfgkey"
    # kulonben a secret, vegul a client_id
    assert kp.creds(T(api_client_secret="sec", api_client_id="cid"))["unas_key"] == "sec"
    assert kp.creds(T(api_client_id="cid"))["unas_key"] == "cid"


def test_missing_platformonkent():
    assert kp.missing("sellvio", kp.creds(SV)) == []
    assert kp.missing("sellvio", kp.creds(T(platform="sellvio"))) == [
        "API cím", "client id", "client secret / API-kulcs"]
    # a shoprenternek public_url is kell (a mapper enelkul dob)
    hi = kp.missing("shoprenter", kp.creds(T(platform="shoprenter", api_base="https://a.b/c",
                                             api_client_id="i", api_client_secret="s")))
    assert hi == ["bolt URL (public_url)"]
    # a unasnak CSAK kulcs kell (az api_base opcionalis)
    assert kp.missing("unas", kp.creds(T(platform="unas", api_client_secret="k"))) == []
    assert kp.missing("unas", kp.creds(T(platform="unas"))) == ["API-kulcs"]
    assert kp.missing("webdoc", kp.creds(WD)) == []


# --------------------------------------------------------------------------- #
# válasz-értelmezők
# --------------------------------------------------------------------------- #
def test_sellvio_shape():
    assert kp.sellvio_shape({"data": {"total": 5289, "items": [{"id": 1}]}}) == (5289, 1)
    assert kp.sellvio_shape({"data": {"items": [{"id": 1}]}}) == (None, 1)
    assert kp.sellvio_shape({"data": {"items": ["szemet"]}}) == (None, 0)
    assert kp.sellvio_shape(None) == (None, 0)
    assert kp.sellvio_shape({"data": "nem-dict"}) == (None, 0)


def test_sr_shape_pagecount_csak_limit1_nel():
    """kf/16a: limit=1-nél a pageCount PONTOSAN a termékszám (mérve 4 SR bolton)."""
    b = {"items": [{"id": 1}], "pageCount": 59740}
    assert kp.sr_shape(b, limit=1) == (59740, 1)
    assert kp.sr_shape(b) == (None, 1)              # limit nelkul NEM hasznaljuk
    assert kp.sr_shape(b, limit=200) == (None, 1)   # 200-as lapnal a pageCount NEM darabszam
    # ha megis van igazi szamlalo-mezo, AZ nyer
    assert kp.sr_shape({"count": 7, "items": [], "pageCount": 99}, limit=1) == (7, 0)


async def test_probe_shoprenter_pagecountbol_szamol():
    c = _sr_client(gets={"/productExtend": R(200, {"items": [{"id": 1}], "pageCount": 59740})})
    r = await kp.probe(SR, {"shoprenter": {"categories": [3408]}}, c)
    assert r["ok"] and r["product_count"] == 59740
    assert "59740" in r["detail"]
    assert "teljes katalógus" in r["detail"]        # nem tevesztheto ossze az index szamaval


def test_sr_shape():
    assert kp.sr_shape({"count": 652, "items": [{"id": 1}]}) == (652, 1)
    assert kp.sr_shape({"response": {"itemCount": 22, "items": [{"id": 1}]}}) == (22, 1)
    assert kp.sr_shape({"items": [{"id": 1}], "pageCount": 9}) == (None, 1)
    assert kp.sr_shape({}) == (None, 0)
    assert kp.sr_shape(None) == (None, 0)


def test_unas_xml_ertelmezok():
    assert kp.unas_token("<Params><Token>abc</Token></Params>") == "abc"
    assert kp.unas_token("<Params></Params>") == ""
    assert kp.unas_token("nem xml") == ""          # nem dob
    assert kp.unas_error("<Params><Error>Hibas ApiKey</Error></Params>") == "Hibas ApiKey"
    assert kp.unas_error("<Params><Message>uzenet</Message></Params>") == "uzenet"
    assert kp.unas_error("nem xml") == ""
    assert kp.unas_sample("<Products><Product><Id>1</Id></Product></Products>") == 1
    assert kp.unas_sample("<Products></Products>") == 0
    assert kp.unas_sample("nem xml") == 0


def test_feed_looks_json():
    assert kp.feed_looks_json(b'{"products": [')
    assert kp.feed_looks_json(b'\xef\xbb\xbf  [\n{')      # BOM + whitespace
    assert kp.feed_looks_json("  [1,2")
    assert not kp.feed_looks_json(b"<!DOCTYPE html>")
    assert not kp.feed_looks_json(b"")
    assert not kp.feed_looks_json(None)


def test_status_error_terkep():
    assert kp.status_error(200) == (None, "")
    assert kp.status_error(204)[0] is None
    assert kp.status_error(401)[0] == "auth_failed"
    assert kp.status_error(403)[0] == "auth_failed"
    assert kp.status_error(404)[0] == "http_error"
    assert kp.status_error(429)[0] == "http_error"
    assert kp.status_error(503)[0] == "http_error"
    assert kp.status_error(0)[0] == "http_error"
    assert kp.status_error(None)[0] == "http_error"


# --------------------------------------------------------------------------- #
# probe() — kapuk hálózat nélkül
# --------------------------------------------------------------------------- #
async def test_probe_nincs_platform():
    r = await kp.probe(T(), None, C())
    assert not r["ok"] and r["error"] == "no_platform"


async def test_probe_egyeb_platform_is_no_platform():
    r = await kp.probe(T(platform="egyeb"), None, C())
    assert r["error"] == "no_platform"


async def test_probe_nem_tamogatott_platform():
    r = await kp.probe(T(platform="woocommerce", api_base="https://a.b"), None, C())
    assert not r["ok"] and r["error"] == "unsupported"
    assert "index-építő" in r["detail"] and "Shoprenter" in r["detail"]


async def test_probe_hianyzo_mezo_nem_hiv_halozatot():
    c = C()
    r = await kp.probe(T(platform="sellvio", api_base="https://a.b"), None, c)
    assert r["error"] == "missing_fields"
    assert "client id" in r["detail"]
    assert c.calls == []          # egyetlen HTTP-hívás sem ment ki


async def test_probe_ms_mezo_mindig_van():
    r = await kp.probe(T(), None, C())
    assert isinstance(r["ms"], int) and r["ms"] >= 0


# --------------------------------------------------------------------------- #
# probe() — Sellvio
# --------------------------------------------------------------------------- #
def _sv_client(**kw):
    posts = kw.pop("posts", {"/oauth/token": R(200, {"access_token": "tok"})})
    gets = kw.pop("gets", {"/api/v2/products": R(200, {"data": {"total": 5289,
                                                                "items": [{"id": 1}]}})})
    return C(posts=posts, gets=gets, **kw)


async def test_probe_sellvio_ok():
    c = _sv_client()
    r = await kp.probe(SV, None, c)
    assert r["ok"] and r["error"] is None
    assert r["platform"] == "sellvio"
    assert r["product_count"] == 5289 and r["sample"] == 1
    assert r["warn"] is None
    assert "5289" in r["detail"]


async def test_probe_sellvio_CSAK_EGY_LAPOT_KER():
    """A próbának KÖNNYŰNEK kell lennie: egy termék, nem a teljes katalógus."""
    c = _sv_client()
    await kp.probe(SV, None, c)
    p = c.params("/api/v2/products")
    assert p.get("limit") == 1 and p.get("page") == 1
    assert len(c.calls) == 2       # token + egy lap, semmi tobb


async def test_probe_sellvio_rossz_kulcs():
    c = _sv_client(posts={"/oauth/token": R(401, {"error": "invalid_client"})})
    r = await kp.probe(SV, None, c)
    assert not r["ok"] and r["error"] == "auth_failed"
    assert len(c.calls) == 1       # a termek-lekeres el sem indult


async def test_probe_sellvio_ures_token():
    c = _sv_client(posts={"/oauth/token": R(200, {})})
    r = await kp.probe(SV, None, c)
    assert r["error"] == "auth_failed" and "access_token" in r["detail"]


async def test_probe_sellvio_nem_json_token_valasz():
    c = _sv_client(posts={"/oauth/token": R(200, None, text="<html>")})
    r = await kp.probe(SV, None, c)
    assert r["error"] == "auth_failed"      # nem dob, ertelmes hiba


async def test_probe_sellvio_termeklekeres_403():
    c = _sv_client(gets={"/api/v2/products": R(403, {})})
    r = await kp.probe(SV, None, c)
    assert not r["ok"] and r["error"] == "auth_failed"


async def test_probe_sellvio_nulla_termek_warn():
    c = _sv_client(gets={"/api/v2/products": R(200, {"data": {"items": []}})})
    r = await kp.probe(SV, None, c)
    assert r["ok"] and r["warn"] and "0 terméket" in r["warn"]


# --------------------------------------------------------------------------- #
# probe() — Shoprenter
# --------------------------------------------------------------------------- #
def _sr_client(**kw):
    posts = kw.pop("posts", {"oauth.app.shoprenter.net": R(200, {"access_token": "tok"})})
    gets = kw.pop("gets", {"/productExtend": R(200, {"count": 652, "items": [{"id": 1}]})})
    return C(posts=posts, gets=gets, **kw)


async def test_probe_shoprenter_ok_es_shop_kiolvasas():
    c = _sr_client()
    r = await kp.probe(SR, {"shoprenter": {"categories": [3408]}}, c)
    assert r["ok"] and r["shop"] == "copygo"
    assert r["product_count"] == 652 and r["sample"] == 1
    assert r["warn"] is None
    assert "copygo/app/token" in c.calls[0][1]


async def test_probe_shoprenter_CSAK_EGY_LAPOT_KER():
    c = _sr_client()
    await kp.probe(SR, {"shoprenter": {"categories": [3408]}}, c)
    p = c.params("/productExtend")
    assert p.get("limit") == 1 and p.get("full") == 0 and p.get("page") == 0
    assert len(c.calls) == 2


async def test_probe_shoprenter_kategoria_lista_nelkul_warn():
    """kf/6: kategória-lista nélkül az index-build elhasal — a próba szóljon."""
    r = await kp.probe(SR, {}, _sr_client())
    assert r["ok"] and r["warn"] and "kategória-lista" in r["warn"]
    r2 = await kp.probe(SR, {"shoprenter": {"categories": []}}, _sr_client())
    assert r2["warn"] and "kategória-lista" in r2["warn"]


async def test_probe_shoprenter_rossz_api_base():
    t = T(platform="shoprenter", api_base="nem-url", api_client_id="i",
          api_client_secret="s", public_url="https://x.hu")
    c = _sr_client()
    r = await kp.probe(t, {}, c)
    assert not r["ok"] and r["error"] == "missing_fields"
    assert c.calls == []


async def test_probe_shoprenter_lejart_kulcs():
    c = _sr_client(posts={"oauth.app.shoprenter.net": R(403, {})})
    r = await kp.probe(SR, {}, c)
    assert r["error"] == "auth_failed" and r["shop"] == "copygo"


async def test_probe_shoprenter_500():
    c = _sr_client(gets={"/productExtend": R(500, {})})
    r = await kp.probe(SR, {}, c)
    assert not r["ok"] and r["error"] == "http_error" and "500" in r["detail"]


# --------------------------------------------------------------------------- #
# probe() — Unas
# --------------------------------------------------------------------------- #
_UN_OK_LOGIN = "<Params><Token>tok</Token></Params>"
_UN_OK_PROD = "<Products><Product><Id>1</Id></Product></Products>"


def _un_client(login=_UN_OK_LOGIN, prod=_UN_OK_PROD, login_status=200, prod_status=200):
    return C(posts={"/login": R(login_status, None, text=login),
                    "/getProduct": R(prod_status, None, text=prod)})


async def test_probe_unas_ok():
    c = _un_client()
    r = await kp.probe(UN, None, c)
    assert r["ok"] and r["platform"] == "unas"
    assert r["product_count"] is None and r["sample"] == 1
    assert "minta-termék" in r["detail"]


async def test_probe_unas_egy_terméket_ker():
    c = _un_client()
    await kp.probe(UN, None, c)
    body = c.calls[1][2]["content"].decode("utf-8")
    assert "<LimitNum>1</LimitNum>" in body and "<LimitStart>0</LimitStart>" in body


async def test_probe_unas_rossz_kulcs():
    c = _un_client(login="<Params><Error>Hibas ApiKey</Error></Params>")
    r = await kp.probe(UN, None, c)
    assert not r["ok"] and r["error"] == "auth_failed"
    assert "Hibas ApiKey" in r["detail"]
    assert len(c.calls) == 1


async def test_probe_unas_getproduct_error_elem():
    c = _un_client(prod="<Params><Error>Nincs jogosultsag</Error></Params>")
    r = await kp.probe(UN, None, c)
    assert not r["ok"] and r["error"] == "bad_response"
    assert "Nincs jogosultsag" in r["detail"]


async def test_probe_unas_hibas_xml_nem_dob():
    c = _un_client(login="nem xml")
    r = await kp.probe(UN, None, c)
    assert not r["ok"] and r["error"] == "auth_failed"


async def test_probe_unas_sajat_shopdomain_a_hivatalos_hostra_esik():
    t = T(platform="unas", api_base="https://smartzilla.hu", api_client_secret="k")
    c = _un_client()
    await kp.probe(t, None, c)
    assert c.calls[0][1].startswith(kp.UNAS_BASE)


# --------------------------------------------------------------------------- #
# probe() — Webdoc
# --------------------------------------------------------------------------- #
async def test_probe_webdoc_ok():
    c = C(stream=S(200, b'{"products": [{"id": 1}]}'))
    r = await kp.probe(WD, None, c)
    assert r["ok"] and r["platform"] == "webdoc"
    assert r["product_count"] is None


async def test_probe_webdoc_nem_tolti_le_az_egeszet():
    """A feed nagy (13e termék) — a próba csak a prefixét olvassa."""
    big = b"[" + b'{"id":1},' * 50000
    s = S(200, big)
    c = C(stream=s)
    r = await kp.probe(WD, None, c)
    assert r["ok"]
    assert s.read_bytes <= kp.FEED_PREFIX_BYTES + 16
    assert s.read_bytes < len(big)


async def test_probe_webdoc_html_valasz():
    c = C(stream=S(200, b"<!DOCTYPE html><html>Bejelentkezes"))
    r = await kp.probe(WD, None, c)
    assert not r["ok"] and r["error"] == "bad_response"


async def test_probe_webdoc_404():
    c = C(stream=S(404, b""))
    r = await kp.probe(WD, None, c)
    assert not r["ok"] and r["error"] == "http_error" and "404" in r["detail"]


async def test_probe_webdoc_feed_url_a_search_configbol():
    c = C(stream=S(200, b"[]"))
    t = T(platform="webdoc", api_base="https://regi.hu/feed.json")
    await kp.probe(t, {"feed_url": "https://uj.hu/export.json"}, c)
    assert c.calls[0][1] == "https://uj.hu/export.json"


async def test_probe_webdoc_nem_http_url():
    c = C()
    t = T(platform="webdoc", api_base="ftp://valami")
    r = await kp.probe(t, None, c)
    assert r["error"] == "missing_fields" and c.calls == []


# --------------------------------------------------------------------------- #
# a próba SOHA nem dobhat az adminra
# --------------------------------------------------------------------------- #
async def test_probe_halozati_hiba_nem_dob():
    c = _sv_client(raise_on="/oauth/token")
    r = await kp.probe(SV, None, c)
    assert not r["ok"] and r["error"] == "network"
    assert "RuntimeError" in r["detail"]


async def test_probe_kliens_nelkul():
    r = await kp.probe(SV, None, None)
    assert not r["ok"] and r["error"] == "no_client"


async def test_probe_valasz_szerzodese():
    """A hívó (admin) minden ágon ugyanazokra a kulcsokra számít."""
    kell = {"ok", "platform", "error", "detail", "shop",
            "product_count", "sample", "warn", "ms"}
    for r in (await kp.probe(T(), None, C()),
              await kp.probe(SV, None, _sv_client()),
              await kp.probe(SR, {}, _sr_client()),
              await kp.probe(UN, None, _un_client()),
              await kp.probe(WD, None, C(stream=S(200, b"[]")))):
        assert kell <= set(r), r

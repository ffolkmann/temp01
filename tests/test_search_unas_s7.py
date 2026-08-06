"""S7 tesztek: Unas ingest-mapper (app/search/unas.py).

A modul csak stdlib + httpx, ezert egyszeru fajl-betoltessel megy. A fetch-hez a
httpx.AsyncClient-et cserelyuk ki egy fake-re (halozat nelkul).
"""

import asyncio
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("unas_s7", ROOT / "app" / "search" / "unas.py")
UN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UN)


# --------------------------------------------------------------------------- #
# XML-epito segedek
# --------------------------------------------------------------------------- #
def product_xml(pid="101", sku="ABC-1", name="Teszt termek", status="1", nolist="0",
                prices="<Prices><Price><Type>normal</Type><Gross>12990</Gross>"
                       "<Actual>1</Actual></Price></Prices>",
                cats='<Categories><Category><Type>base</Type><Id>7</Id>'
                     '<Name>Nyomtatok</Name></Category></Categories>',
                images='<Images><Image><Type>base</Type><SefUrl>kep/nyomtato.jpg</SefUrl>'
                       '</Image></Images>',
                params="<Params></Params>", stocks="", extra=""):
    return (
        "<Product>"
        "<Id>%s</Id><Sku>%s</Sku><Name>%s</Name>"
        "<Statuses><Status><Type>base</Type><Value>%s</Value></Status></Statuses>"
        "<NoList>%s</NoList>"
        "<Url>https://bolt.hu/termek/%s</Url><SefUrl>termek/%s</SefUrl>"
        "%s%s%s%s%s%s"
        "</Product>" % (pid, sku, name, status, nolist, sku, sku,
                        prices, cats, images, params, stocks, extra)
    )


def products_xml(*items):
    return '<?xml version="1.0" encoding="UTF-8" ?><Products>%s</Products>' % "".join(items)


def one(xml):
    """Egy <Product> elem a rekord-szintu segedfuggvenyekhez."""
    return UN._root(products_xml(xml)).find(".//Product")


class _Tenant:
    def __init__(self, **kw):
        self.client_id = kw.get("client_id", "unasshop")
        self.api_base = kw.get("api_base", "")
        self.api_client_id = kw.get("api_client_id", "")
        self.api_client_secret = kw.get("api_client_secret", "")
        self.public_url = kw.get("public_url", "https://bolt.hu")
        self.domain = kw.get("domain", "bolt.hu")


# --------------------------------------------------------------------------- #
# keres-osszeallitas
# --------------------------------------------------------------------------- #
def test_login_es_getproduct_keres_alakja():
    body = UN.login_body("kulcs&123")
    assert "<ApiKey>kulcs&amp;123</ApiKey>" in body     # XML-escape
    assert body.startswith('<?xml version="1.0" encoding="UTF-8" ?>')

    q = UN.product_body(500, 250, "hu")
    for frag in ("<StatusBase>1,2,3</StatusBase>", "<State>live</State>",
                 "<ContentType>full</ContentType>", "<LimitNum>250</LimitNum>",
                 "<LimitStart>500</LimitStart>", "<Lang>hu</Lang>"):
        assert frag in q


def test_token_kiolvasasa_es_hibaja():
    assert UN.parse_token('<?xml version="1.0"?><Login><Token>abc123</Token></Login>') == "abc123"
    with pytest.raises(RuntimeError) as e:
        UN.parse_token("<Login><Error>Hibas API kulcs</Error></Login>")
    assert "Hibas API kulcs" in str(e.value)
    with pytest.raises(RuntimeError):
        UN.parse_token("nem xml")


# --------------------------------------------------------------------------- #
# rekord-lekepezes
# --------------------------------------------------------------------------- #
def test_alap_lekepezes():
    rec = UN.map_product(one(product_xml(extra="<CreateTime>1786000000</CreateTime>")))
    assert rec["id"] == "101" and rec["sku"] == "ABC-1"
    assert rec["name"] == "Teszt termek"
    assert rec["category"] == "Nyomtatok"
    assert rec["price_gross"] == 12990 and rec["orig_price"] is None
    assert rec["available"] is True
    assert rec["url"] == "https://bolt.hu/termek/ABC-1"
    assert rec["image_url"] == "kep/nyomtato.jpg"
    assert rec["created_day"] == 1786000000 // 86400


def test_inaktiv_es_rejtett_termek_kiesik():
    assert UN.map_product(one(product_xml(status="0"))) is None      # inaktiv
    assert UN.map_product(one(product_xml(nolist="1"))) is None      # nem listazando
    assert UN.map_product(one(product_xml(name=""))) is None         # nev nelkul ertelmetlen


def test_aktiv_de_nem_vasarolhato_bekerul_de_nem_elerheto():
    rec = UN.map_product(one(product_xml(status="3")))
    assert rec is not None and rec["available"] is False


def test_keszlet_dontese():
    st = ("<Stocks><Status><Active>1</Active><Empty>%s</Empty></Status>"
          "<Stock><Qty>%s</Qty></Stock></Stocks>")
    assert UN.is_available(one(product_xml(stocks=st % ("0", "0")))) is False
    assert UN.is_available(one(product_xml(stocks=st % ("0", "3")))) is True
    # "vasarolhato, ha nincs raktaron" -> a nulla keszlet sem tiltja
    assert UN.is_available(one(product_xml(stocks=st % ("1", "0")))) is True
    # keszletkezeles kikapcsolva -> mindig vasarolhato
    assert UN.is_available(one(product_xml(
        stocks="<Stocks><Status><Active>0</Active></Status></Stocks>"))) is True
    # tobb raktar keszlete osszeadodik
    assert UN.is_available(one(product_xml(stocks=(
        "<Stocks><Status><Active>1</Active><Empty>0</Empty></Status>"
        "<Stock><Qty>0</Qty></Stock><Stock><WarehouseId>2</WarehouseId>"
        "<Qty>4</Qty></Stock></Stocks>")))) is True


def test_akcios_ar_es_athuzott_eredeti():
    sale = ("<Prices><Price><Type>normal</Type><Gross>19990</Gross></Price>"
            "<Price><Type>sale</Type><Gross>14990</Gross><Actual>1</Actual></Price></Prices>")
    rec = UN.map_product(one(product_xml(prices=sale)))
    assert rec["price_gross"] == 14990 and rec["orig_price"] == 19990

    # ha a NORMAL ar az aktualis, nincs athuzott ar
    normal = ("<Prices><Price><Type>normal</Type><Gross>19990</Gross><Actual>1</Actual></Price>"
              "<Price><Type>sale</Type><Gross>14990</Gross></Price></Prices>")
    rec = UN.map_product(one(product_xml(prices=normal)))
    assert rec["price_gross"] == 19990 and rec["orig_price"] is None

    # Actual jelzes nelkul a normal ar a fallback
    plain = "<Prices><Price><Type>normal</Type><Gross>9990</Gross></Price></Prices>"
    assert UN.price_of(one(product_xml(prices=plain))) == (9990, None)
    assert UN.price_of(one(product_xml(prices="<Prices></Prices>"))) == (None, None)


def test_gyarto_a_parameterbol_es_kiesik_a_facetekbol():
    params = ("<Params>"
              "<Param><Id>5</Id><Name>Gy\u00e1rt\u00f3</Name><Value>Epson</Value></Param>"
              "<Param><Id>9</Id><Name>Sz\u00edn</Name><Value>fekete</Value></Param>"
              "<Param><Id>11</Id><Name>Ures</Name><Value></Value></Param>"
              "</Params>")
    rec = UN.map_product(one(product_xml(params=params)))
    assert rec["brand"] == "Epson"
    assert rec["parameters"] == [{"name": "Sz\u00edn", "value": "fekete"}]   # marka + ures kiesik
    assert UN.map_product(one(product_xml()))["brand"] == ""


def test_alap_kategoria_es_kep_valasztasa():
    cats = ('<Categories><Category><Type>alt</Type><Name>Akciok</Name></Category>'
            '<Category><Type>base</Type><Name>Lezernyomtatok</Name></Category></Categories>')
    assert UN.category_of(one(product_xml(cats=cats))) == "Lezernyomtatok"

    imgs = ('<Images><Image><Type>alt</Type><SefUrl>plusz.jpg</SefUrl></Image>'
            '<Image><Type>base</Type><SefUrl>alap.jpg</SefUrl></Image></Images>')
    assert UN.image_of(one(product_xml(images=imgs))) == "alap.jpg"
    # SefUrl hianyaban a fajlnev, vegso soron a DefaultFilename
    assert UN.image_of(one(product_xml(
        images="<Images><Image><Type>base</Type><Filename>f.jpg</Filename></Image></Images>"
    ))) == "f.jpg"
    assert UN.image_of(one(product_xml(
        images="<Images><DefaultFilename>d.jpg</DefaultFilename></Images>"))) == "d.jpg"


def test_parse_products_es_hibauzenet():
    xml = products_xml(product_xml(pid="1", sku="A"), product_xml(pid="2", sku="B", status="0"))
    recs = UN.parse_products(xml)
    assert [r["id"] for r in recs] == ["1"]        # az inaktiv kiesik
    assert UN.count_products(xml) == 2             # de a lapozas MINDET szamolja
    with pytest.raises(RuntimeError) as e:
        UN.parse_products('<Products><Error>Nincs jogosultsag</Error></Products>')
    assert "Nincs jogosultsag" in str(e.value)


# --------------------------------------------------------------------------- #
# konfiguracio-feloldas
# --------------------------------------------------------------------------- #
def test_api_kulcs_es_prefixek_feloldasa():
    t = _Tenant(api_client_secret="titok", api_client_id="ugyfel")
    assert UN.api_key(t) == "titok"
    assert UN.api_key(t, {"unas": {"api_key": "config"}}) == "config"      # a config nyer
    assert UN.api_key(_Tenant(api_client_id="csak-id")) == "csak-id"
    assert UN.api_key(_Tenant()) == ""

    assert UN.prefixes(t) == ("https://bolt.hu/", "https://bolt.hu/")
    assert UN.prefixes(_Tenant(public_url=""))[0] == "https://bolt.hu/"    # domain-fallback
    assert UN.prefixes(t, {"unas": {"img_prefix": "https://cdn.hu/kepek"}})[1] \
        == "https://cdn.hu/kepek/"
    with pytest.raises(RuntimeError):
        UN.prefixes(_Tenant(public_url="", domain=""))

    assert UN.base_url(_Tenant()) == UN.DEFAULT_BASE
    assert UN.base_url(_Tenant(api_base="https://api11.unas.eu/shop/")) == "https://api11.unas.eu/shop"


# --------------------------------------------------------------------------- #
# fetch (fake halozattal)
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)


def _fake_httpx(pages, login='<Login><Token>TOK</Token></Login>'):
    calls = []

    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, content=None, headers=None):
            calls.append({"url": url, "body": (content or b"").decode("utf-8"),
                          "headers": dict(headers or {})})
            if url.endswith("/login"):
                return _Resp(login)
            return _Resp(pages[min(len([c for c in calls
                                        if c["url"].endswith("/getProduct")]) - 1,
                                   len(pages) - 1)])

    mod = type("m", (), {"AsyncClient": _Client})
    return mod, calls


def test_fetch_lapoz_dedupol_es_tokent_kuld(monkeypatch):
    page1 = products_xml(*[product_xml(pid=str(i), sku="S%d" % i) for i in range(1, 4)])
    page2 = products_xml(product_xml(pid="3", sku="S3"),          # atfedes -> dedup
                         product_xml(pid="4", sku="S4"))
    fake, calls = _fake_httpx([page1, page2])
    monkeypatch.setattr(UN, "httpx", fake)
    monkeypatch.setattr(UN, "_PAGE", 3)
    monkeypatch.setattr(UN, "_SLEEP", 0)

    products, url_prefix, img_prefix = asyncio.run(
        UN.fetch(_Tenant(api_client_secret="titok"), {"unas": {"page_size": 3}}))

    assert [p["id"] for p in products] == ["1", "2", "3", "4"]     # a duplikatum egyszer
    assert (url_prefix, img_prefix) == ("https://bolt.hu/", "https://bolt.hu/")
    assert calls[0]["url"].endswith("/login") and "titok" in calls[0]["body"]
    assert calls[1]["headers"]["Authorization"] == "Bearer TOK"
    assert "<LimitStart>0</LimitStart>" in calls[1]["body"]
    assert "<LimitStart>3</LimitStart>" in calls[2]["body"]        # a kovetkezo lap


def test_fetch_api_kulcs_nelkul_beszedes_hibat_dob(monkeypatch):
    fake, _ = _fake_httpx([products_xml()])
    monkeypatch.setattr(UN, "httpx", fake)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(UN.fetch(_Tenant()))
    assert "API kulcs" in str(e.value)


def test_fetch_login_hibara_megall(monkeypatch):
    fake, _ = _fake_httpx([products_xml()], login="<Login><Error>Nincs jog</Error></Login>")
    monkeypatch.setattr(UN, "httpx", fake)
    monkeypatch.setattr(UN, "_SLEEP", 0)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(UN.fetch(_Tenant(api_client_secret="titok")))
    assert "Nincs jog" in str(e.value)

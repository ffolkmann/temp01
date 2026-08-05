"""K1: Shoprenter mapper tiszta fuggvenyei — file-load import (fake-app-safe)."""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "search" / "shoprenter.py"
_spec = importlib.util.spec_from_file_location("sr_mapper_under_test", _P)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


def _attr(name, *vals):
    return {"href": "h", "id": "i", "type": "LIST", "name": name,
            "value": [{"value": v, "language": {"id": "l1"}} for v in vals]}


def test_attr_values_shapes():
    assert sr.attr_values(_attr("garancia", "12 h\u00f3nap")) == ["12 h\u00f3nap"]
    assert sr.attr_values({"name": "x", "value": "sima"}) == ["sima"]
    assert sr.attr_values({"name": "x", "value": ["a", "", "b"]}) == ["a", "b"]
    assert sr.attr_values({"name": "x"}) == []


def test_collect_attrs_skips_internal():
    p = {"productAttributeExtend": [_attr("kefix_kat", "0%"),
                                    _attr("a_beszallito", "CHS"),
                                    _attr("funkcio", "Nyomtat\u00e1s")]}
    raw = sr.collect_attrs(p)
    assert set(raw) == {"funkcio"}


def test_parse_speed_gate():
    assert sr.parse_speed(["1120 oldal/perc"]) is None
    assert sr.parse_speed(["8 oldal/perc"]) == 8
    assert sr.parse_speed(["18"]) == 18
    assert sr.parse_speed(["15.5 oldal/perc"]) == 16
    assert sr.parse_speed([]) is None


def test_parse_dpi_and_mb():
    assert sr.parse_dpi(["1200 x 600 dpi"]) == 1200
    assert sr.parse_dpi(["2400*1200"]) == 2400
    assert sr.parse_dpi(["dpi"]) is None
    assert sr.parse_mb(["256 MB"]) == 256
    assert sr.parse_mb(["3072"]) == 3072


def test_canon_szin():
    assert sr.canon_szin(["mono"]) == "Mono"
    assert sr.canon_szin(["Sz\u00ednes"]) == "Sz\u00ednes"
    assert sr.canon_szin([], has_color_speed=True) == "Sz\u00ednes"
    assert sr.canon_szin([]) is None


def test_canon_funkcio_merge():
    got = sr.canon_funkcio(["Nyomtat, M\u00e1sol, Szkennel, Faxol"])
    assert got == ["Nyomtat\u00e1s", "M\u00e1sol\u00e1s", "Szkennel\u00e9s", "Fax"]
    assert sr.canon_funkcio(["Nyomtat\u00e1s"]) == ["Nyomtat\u00e1s"]


def test_canon_duplex():
    d, ds = sr.canon_duplex(["Nyomtat\u00e1s, Szkennel\u00e9s/M\u00e1sol\u00e1s"], False)
    assert d == "Automata" and ds is True
    d, ds = sr.canon_duplex(["Manu\u00e1lis"], False)
    assert d == "Manu\u00e1lis" and ds is False
    d, ds = sr.canon_duplex([], True)
    assert d == "Val\u00f3sz\u00edn\u0171" and ds is False
    assert sr.canon_duplex([], False) == (None, False)


def test_canon_adf_papir():
    assert sr.canon_adf(["DSDF"]) == "DSDF"
    assert sr.canon_adf(["Simatet\u0151"]) == "Simatet\u0151"
    assert sr.canon_adf(["ADF"]) == "ADF"
    assert sr.canon_papir(["A3+"]) == "A3+"
    assert sr.canon_papir(["A3"]) == "A3"
    assert sr.canon_papir(["A4"]) == "A4"


def test_canon_tech_fallback():
    assert sr.canon_tech(["L\u00e9zer"], 3420) == "L\u00e9zer"
    assert sr.canon_tech([], 3420) == "Tintasugaras"
    assert sr.canon_tech([], 3474) is None


def test_canon_halozat_combo():
    raw = {"wireless": ["Nincs"], "elsodlegescsatlakozok": ["Wifi, H\u00e1l\u00f3zat, USB 2.0"]}
    assert sr.canon_halozat(raw, "") == ["WiFi", "LAN"]
    assert sr.canon_halozat({}, "a keszulek Wi-Fi kapcsolattal") == ["WiFi"]
    # kisbetus 'lan' szo-reszlet NEM talalat, a nagybetus LAN igen
    assert sr.canon_halozat({}, "az oldalan talan") == []
    assert sr.canon_halozat({}, "10/100 LAN port") == ["LAN"]


def test_canon_brand():
    assert sr.canon_brand("HP Inc.", {}) == "HP"
    assert sr.canon_brand("EPS BUS_IM", {}) == "Epson"
    assert sr.canon_brand("", {"gyarto": ["CANON"]}) == "Canon"
    assert sr.canon_brand("Brother", {}) == "Brother"
    assert sr.canon_brand("OKI", {}) == "OKI"


def test_extract_price_default_group_and_special():
    p = {"productPrices": [
        {"customerGroup": {"default": False}, "gross": "111", "grossSpecial": None,
         "currencyCode": "HUF"},
        {"customerGroup": {"default": True}, "gross": "222190", "grossSpecial": None,
         "currencyCode": "HUF"},
    ]}
    assert sr.extract_price(p) == (222190, None)
    p2 = {"productPrices": [
        {"customerGroup": {"default": True}, "gross": "1000", "grossSpecial": "800",
         "currencyCode": "HUF"}]}
    assert sr.extract_price(p2) == (800, 1000)
    assert sr.extract_price({}) == (None, None)


def test_created_day_naive():
    assert sr.created_day("2019-09-12T13:15:21") == 18151
    assert sr.created_day("") is None


def test_decode_rel_pid():
    import base64
    rid = base64.b64encode(b"productCategory-product_id=18927&category_id=3405").decode()
    assert sr.decode_rel_pid(rid) == "18927"
    assert sr.decode_rel_pid("nem-b64!!") is None


def _full_product(**over):
    p = {
        "innerId": "42",
        "sku": "SKU42",
        "status": "2",
        "stock1": "1", "stock2": "0", "stock3": "0", "stock4": "0",
        "mainPicture": "uploads/products/sku42-1.jpg",
        "dateCreated": "2024-01-10T08:00:00",
        "manufacturer": {"name": "Brother"},
        "urlAliases": [{"urlAlias": "brother-sku42"}],
        "productDescriptions": [{"name": "Brother SKU42 MFP",
                                 "shortDescription": "rovid",
                                 "description": "<p>Ethernet es duplex</p>",
                                 "parameters": ""}],
        "productPrices": [{"customerGroup": {"default": True}, "gross": "100000",
                           "grossSpecial": None, "currencyCode": "HUF"}],
        "productAttributeExtend": [
            _attr("funkcio", "Nyomtat, M\u00e1sol"),
            _attr("szinkezeles", "mono"),
            _attr("nyomtatasisebessegmono", "22 oldal/perc"),
        ],
    }
    p.update(over)
    return p


def test_map_product_full():
    rec = sr.map_product(_full_product(), 3423, "L\u00e9zernyomtat\u00f3")
    assert rec["id"] == "42" and rec["sku"] == "SKU42"
    assert rec["category"] == "L\u00e9zernyomtat\u00f3"
    assert rec["available"] is True
    assert rec["price_gross"] == 100000 and rec["orig_price"] is None
    assert rec["url"] == "brother-sku42"
    names = {(d["name"], d["value"]) for d in rec["parameters"]}
    assert ("funkciok", "Nyomtat\u00e1s") in names
    assert ("funkciok", "M\u00e1sol\u00e1s") in names
    assert ("szinkezeles", "Mono") in names
    assert ("sebesseg_ppm", "22") in names
    assert ("technologia", "L\u00e9zer") in names        # kategoria-fallback
    assert ("halozat", "LAN") in names                   # leiras-regex
    assert ("duplex", "Val\u00f3sz\u00edn\u0171") in names  # leiras-fallback


def test_map_product_filters():
    supply = _full_product(productAttributeExtend=[
        _attr("funkcio", "Nyomtat\u00e1s"), _attr("kellekanyagtipus", "ut\u00e1ngy\u00e1rtott")])
    assert sr.map_product(supply, 3423, "x") is None
    nocore = _full_product(productAttributeExtend=[_attr("garancia", "12 h\u00f3nap")])
    assert sr.map_product(nocore, 3423, "x") is None
    off = _full_product(status="0")
    assert sr.map_product(off, 3423, "x") is None

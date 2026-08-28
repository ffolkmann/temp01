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


def _rel(cat_id, pid="42"):
    import base64
    return {"id": base64.b64encode(("productCategory-product_id=%s&category_id=%s" % (pid, cat_id)).encode()).decode()}


def _full_product(**over):
    p = {
        "innerId": "42",
        "sku": "SKU42",
        "status": "1",
        "stock1": "1", "stock2": "0", "stock3": "0", "stock4": "0",
        "mainPicture": "uploads/products/sku42-1.jpg",
        "dateCreated": "2024-01-10T08:00:00",
        "manufacturer": {"name": "Brother"},
        "urlAliases": [{"urlAlias": "brother-sku42"}],
        "productCategoryRelations": [_rel(3405), _rel(3423)],
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


PRINTER = {"profiles": [{"profile": "printer", "categories": [3405, 3420, 3423]}]}
NAMES = {3405: "Nyomtat\u00f3k", 3423: "L\u00e9zernyomtat\u00f3", 3420: "Tintasugaras", 9001: "Napelem"}


def test_relation_cat_ids_and_pick():
    p = _full_product()
    assert sr.relation_cat_ids(p) == [3405, 3423]
    prof = sr.norm_profiles(PRINTER)
    assert sr.pick_category([3405, 3423], [3423, 3405], prof) == 3423   # tenant-lista sorrendje
    assert sr.pick_category([9001, 3423], [], prof) == 3423             # profil kategoriaja
    assert sr.pick_category([9001, 7], [], prof) == 9001                # elso relacio
    assert sr.pick_category([], [], prof) is None


def test_norm_profiles_defaults():
    prof = sr.norm_profiles(PRINTER)
    assert prof[0]["name"] == "printer" and prof[0]["cats"] == {3405, 3420, 3423}
    assert prof[0]["require"] == set(sr.CORE_ATTRS)
    custom = sr.norm_profiles({"profiles": [{"profile": "printer", "categories": ["3420"],
                                             "require_any_attr": ["funkciok"]}]})
    assert custom[0]["require"] == {"funkciok"} and custom[0]["cats"] == {3420}
    assert sr.norm_profiles({"profiles": [{"profile": "ismeretlen", "categories": [1]}]}) == []
    assert sr.norm_profiles({}) == []


def test_map_product_printer_profile():
    rec = sr.map_product(_full_product(), [3423], sr.norm_profiles(PRINTER), NAMES)
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
    assert ("technologia", "L\u00e9zer") in names        # kategoria-fallback (3423)
    assert ("halozat", "LAN") in names                   # leiras-regex
    assert ("duplex", "Val\u00f3sz\u00edn\u0171") in names  # leiras-fallback
    # kfcat/1: a nyers attributumok IS atmennek - kiveve, amit a profil kanonizalt neven ad
    assert ("funkcio", "Nyomtat, M\u00e1sol") in names
    assert ("nyomtatasisebessegmono", "22 oldal/perc") in names
    assert not any(n == "szinkezeles" and v == "mono" for n, v in names)   # arnyekolva


def test_map_product_generic_no_profile():
    p = _full_product(productCategoryRelations=[_rel(9001)],
                      productAttributeExtend=[_attr("teljesitmeny_w", "470"), _attr("kefix_kat", "0%")])
    rec = sr.map_product(p, [], [], NAMES)
    assert rec is not None and rec["category"] == "Napelem"
    names = {(d["name"], d["value"]) for d in rec["parameters"]}
    assert names == {("teljesitmeny_w", "470")}          # belso attr kimarad, semmi kanonizalas
    # ismeretlen kategoria -> az id a nev
    rec2 = sr.map_product(_full_product(productCategoryRelations=[_rel(777)]), [], [], NAMES)
    assert rec2["category"] == "777"


def test_map_product_wanted_filter():
    assert sr.map_product(_full_product(), [9001], [], NAMES) is None
    assert sr.map_product(_full_product(), [3405], [], NAMES) is not None
    assert sr.map_product(_full_product(), [], [], NAMES) is not None   # ures = teljes katalogus


def test_map_product_require_any_attr():
    prof = sr.norm_profiles(PRINTER)
    # copygo WF-M5899 / EM-C800: nyomtato HIBAS kellek-attributummal -> BENT MARAD (van funkciok)
    epson = _full_product(productCategoryRelations=[_rel(3405), _rel(3420)], productAttributeExtend=[
        _attr("funkciok", "Nyomtat, M\u00e1sol, Szkennel, Faxol"),
        _attr("kellekanyagtipus", "ut\u00e1ngy\u00e1rtott"), _attr("kompatibilitas", "Epson")])
    rec = sr.map_product(epson, [], prof, NAMES)
    assert rec is not None
    names = {(d["name"], d["value"]) for d in rec["parameters"]}
    assert ("funkciok", "Fax") in names and ("technologia", "Tintasugaras") in names
    assert ("funkciok", "Nyomtat, M\u00e1sol, Szkennel, Faxol") not in names   # nyers alak arnyekolva
    assert ("kellekanyagtipus", "ut\u00e1ngy\u00e1rtott") in names             # nyers attr atmegy
    # kellek a nyomtato-kategoriaban, funkcio nelkul -> kiesik
    supply = _full_product(productAttributeExtend=[_attr("kellekanyagtipus", "ut\u00e1ngy\u00e1rtott")])
    assert sr.map_product(supply, [], prof, NAMES) is None
    # ugyanaz PROFIL NELKUL: generikusan bent marad
    assert sr.map_product(supply, [], [], NAMES) is not None
    # status=0 (letiltott) es status=2 (kifutott) is mindig kiesik - kfst/1
    assert sr.map_product(_full_product(status="0"), [], prof, NAMES) is None
    assert sr.map_product(_full_product(status="2"), [], prof, NAMES) is None
    # az engedelyezett termek bent marad akkor is, ha 0 a keszlete
    nostock = sr.map_product(_full_product(status="1", stock1="0"), [], prof, NAMES)
    assert nostock is not None and nostock["available"] is False
    # a statusz-halmaz felulirhato: ha csak a 0-t dobjuk, a kifutott bent marad
    assert sr.map_product(_full_product(status="2"), [], prof, NAMES,
                          drop_status={"0"}) is not None


def test_generic_params_caps_values():
    raw = {"szin": [str(i) for i in range(20)], "x": ["a"]}
    got = sr.generic_params(raw, skip={"x"})
    assert len(got) == sr.MAX_ATTR_VALUES and all(d["name"] == "szin" for d in got)


def test_fetch_streams_collection(monkeypatch):
    import asyncio

    class T:
        client_id = "copygo"; api_base = "https://copygo.api2.myshoprenter.hu/api"
        api_client_id = "k"; api_client_secret = "s"; public_url = "https://copygo.hu"

    async def fake_token(client, shop, cid, sec, force=False):
        return "tok"

    async def fake_names(base, headers, client):
        return NAMES

    calls = {}

    async def fake_list(api_base, cid, sec, full=1, concurrency=4):
        calls["args"] = (api_base, full, concurrency)
        yield [_full_product(), _full_product(innerId="43", sku="OFF", status="0"),
               _full_product(innerId="45", sku="KIFUTO", status="2")]
        yield [_full_product(innerId="44", sku="PANEL", productCategoryRelations=[_rel(9001, "44")],
                             productAttributeExtend=[_attr("teljesitmeny_w", "470")])]

    monkeypatch.setattr(sr, "shoprenter_token", fake_token)
    monkeypatch.setattr(sr, "fetch_category_names", fake_names)
    monkeypatch.setattr(sr, "shoprenter_list_products", fake_list)
    tcfg = {"shoprenter": dict(PRINTER)}
    products, up, ip = asyncio.run(sr.fetch(T(), tcfg))
    assert calls["args"] == ("https://copygo.api2.myshoprenter.hu/api", 1, 4)
    assert up == "https://copygo.hu/"
    assert ip == "https://copygo.hu/custom/copygo/image/cache/w300h300wt1/"
    assert [p["sku"] for p in products] == ["SKU42", "PANEL"]       # status=0 ES status=2 kiesett
    assert products[1]["category"] == "Napelem"
    # kategoria-szures: csak a nyomtato marad
    tcfg2 = {"shoprenter": {"categories": [3423]}}
    products2, _, _ = asyncio.run(sr.fetch(T(), tcfg2))
    assert [p["sku"] for p in products2] == ["SKU42"]

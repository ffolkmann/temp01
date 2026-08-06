"""S1 tesztek: indexcore (portolt mag) + sellvio mapper tiszta reszei.

Fajl-betoltos import (m73/m80b minta) — nem az app-csomagon at, hogy a
fake-app-os tesztfajlok sys.modules-szennyezese ne torje.
"""
import importlib.util
import json
import pathlib

_BASE = pathlib.Path(__file__).resolve().parents[1] / "app" / "search"


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, _BASE / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ic = _load("ss_indexcore_t", "indexcore.py")
sv = _load("ss_sellvio_t", "sellvio.py")


# --------------------------------------------------------------------------- #
# indexcore
# --------------------------------------------------------------------------- #
def test_compact_fields_and_prefix():
    p = {"id": 7, "sku": " A1 ", "name": " Nev ", "brand": "B", "category": "C",
         "price_gross": 100, "available": True,
         "url": "https://x.hu/hu/a/termek/", "image_url": "https://x.hu/tenancy/assets/products/a.webp"}
    r = ic.compact(p, "https://x.hu/", "https://x.hu/tenancy/assets/products/")
    assert list(r.keys()) == ["i", "k", "n", "b", "c", "p", "a", "u", "m"]
    assert r["i"] == "7" and r["k"] == "A1" and r["u"] == "hu/a/termek/" and r["m"] == "a.webp"
    assert r["a"] == 1 and r["p"] == 100


def test_compact_orig_price_only_when_bigger():
    base = {"id": 1, "available": True, "price_gross": 100}
    assert "o" not in ic.compact({**base, "orig_price": None}, "", "")
    assert "o" not in ic.compact({**base, "orig_price": 100}, "", "")
    assert ic.compact({**base, "orig_price": 150}, "", "")["o"] == 150
    assert "o" not in ic.compact({"id": 1, "orig_price": 150}, "", "")  # nincs price


def test_build_params_encoding_dedup_limits():
    prods = [
        {"id": 1, "parameters": [{"name": "Szin", "value": "kek"},
                                 {"name": "Szin", "value": "kek"},
                                 {"name": "Meret", "value": [19, "20"]},
                                 {"name": "x" * 61, "value": "hosszu-nev-kimarad"},
                                 {"name": "Rossz", "value": {"d": 1}}]},
        {"id": 2, "parameters": [{"name": "Szin", "value": "piros"}]},
        {"id": 3},
    ]
    out = ic.build_params(prods)
    assert out["names"] == ["Szin", "Meret"]
    assert out["vals"] == ["kek", "19", "20", "piros"]
    assert out["p"]["1"] == [0, 0, 1, 1, 1, 2]
    assert out["p"]["2"] == [0, 3]
    assert "3" not in out["p"]


def test_apply_days_created_only_no_registry(tmp_path):
    rows = [{"i": "1"}, {"i": "2"}]
    n = ic.apply_days(rows, [100, 200], str(tmp_path))
    assert n == 0 and rows[0]["d"] == 100 and rows[1]["d"] == 200
    assert not (tmp_path / "first_seen.json").exists()


def test_apply_days_mixed_registry_first_run_zero(tmp_path):
    rows = [{"i": "1"}, {"i": "2"}]
    n = ic.apply_days(rows, [None, 500], str(tmp_path))
    assert n == 0 and rows[0]["d"] == 0 and rows[1]["d"] == 500  # elso futas: None -> 0
    rows2 = [{"i": "1"}, {"i": "9"}, {"i": "2"}]
    n2 = ic.apply_days(rows2, [None, None, 500], str(tmp_path))
    assert n2 == 1 and rows2[0]["d"] == 0 and rows2[1]["d"] > 0 and rows2[2]["d"] == 500
    fs = json.loads((tmp_path / "first_seen.json").read_text())
    assert fs["1"] == 0 and fs["9"] > 0


def _prod(i, av=True, cd=100):
    return {"id": i, "sku": f"S{i}", "name": f"N{i}", "brand": "B", "category": "C",
            "price_gross": 10 * i, "available": av, "url": f"https://x.hu/p{i}",
            "image_url": "", "parameters": [{"name": "P", "value": "v"}], "created_day": cd}


def test_build_index_end_to_end(tmp_path):
    prods = [_prod(1), _prod(2), _prod(3, av=False)]
    res = ic.build_index("t1", prods, str(tmp_path), "https://x.hu/", "https://x.hu/img/")
    assert res["count"] == 2 and res["pcount"] == 2
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["v"] == res["v"] and man["count"] == 2 and man["pv"] == res["pv"]
    idx = json.loads((tmp_path / "index.json").read_text())
    assert [r["i"] for r in idx["products"]] == ["1", "2"]
    assert all(r["d"] == 100 for r in idx["products"])


def test_build_index_shrink_guard(tmp_path):
    ic.build_index("t1", [_prod(i) for i in range(1, 11)], str(tmp_path), "", "")
    res = ic.build_index("t1", [_prod(1)], str(tmp_path), "", "")
    assert "error" in res and "zsugorodas" in res["error"]
    idx = json.loads((tmp_path / "index.json").read_text())
    assert len(idx["products"]) == 10  # a regi index maradt
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["count"] == 10 and "error" in man


def test_write_error_manifest_keeps_prev_count(tmp_path):
    ic.build_index("t1", [_prod(1), _prod(2)], str(tmp_path), "", "")
    ic.write_error_manifest(str(tmp_path), "t1", "fetch: boom")
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["error"] == "fetch: boom" and man["count"] == 2


# --------------------------------------------------------------------------- #
# sellvio mapper (tiszta reszek)
# --------------------------------------------------------------------------- #
def test_num():
    assert sv._num(58600) == 58600
    assert sv._num(58600.0) == 58600
    assert sv._num("58600.00") == 58600
    assert sv._num(46141.73) == 46141.73
    assert sv._num(True) is None and sv._num("x") is None and sv._num(None) is None


def test_depth_and_pick_category():
    tree = {1001: None, 1013: 1001, 2000: 2001, 2001: 2000}  # 2000/2001: ciklus
    depth = sv.build_depth(tree)
    assert depth(1001) == 0 and depth(1013) == 1
    assert depth(2000) == 20  # ciklus-guard: nem vegtelen
    cats = {"1001": {"id": 1001, "name": "Model Y"},
            "1013": {"id": 1013, "name": "Model Y, Karbon"}}
    assert sv.pick_category(cats, depth) == "Model Y, Karbon"
    # dontetlen melyseg -> kisebb id
    cats2 = {"5": {"id": 5, "name": "Otos"}, "3": {"id": 3, "name": "Harmas"}}
    d0 = sv.build_depth({})
    assert sv.pick_category(cats2, d0) == "Harmas"
    assert sv.pick_category({}, d0) == "" and sv.pick_category(None, d0) == ""


def test_pick_image():
    g = [{"file": "a.webp", "is_main": False}, {"file": "b.webp", "is_main": True}]
    assert sv.pick_image(g) == "b.webp"
    assert sv.pick_image([{"file": "a.webp"}, {"file": "c.webp"}]) == "a.webp"
    assert sv.pick_image([]) == "" and sv.pick_image(None) == ""


def test_extract_price_object_and_map():
    assert sv.extract_price({"price": {"brutto_price": 58600, "netto_price": 1.0}}) == (58600, None)
    p2 = {"price": None, "prices": {"1": {"brutto_price": "100.00", "old_price": "150.00"}}}
    assert sv.extract_price(p2) == (100, 150)
    p3 = {"prices": {"1": {"brutto_price": "100.00", "old_price": "90.00"}}}
    assert sv.extract_price(p3) == (100, None)
    assert sv.extract_price({}) == (None, None)


def test_created_day():
    assert sv.created_day("2026-04-20T13:57:31.000000Z") == 20563
    assert sv.created_day("") is None and sv.created_day(None) is None
    assert sv.created_day("nem-datum") is None


def test_canon_url_platform_aldomain():
    root = "https://teslashop.hu/"
    # a platform-aldomaint a bolt sajat domainjere cserelyuk
    assert sv.canon_url("https://teslashop.mysellvio.com/hu/termek-1", root) == "https://teslashop.hu/hu/termek-1"
    assert sv.canon_url("//teslashop.mysellvio.com/hu/a", root) == "https://teslashop.hu/hu/a"
    # a kep is a GYOKERRE megy (nem az img_prefixre), hogy az utvonal ne duplazodjon
    assert (sv.canon_url("https://teslashop.mysellvio.com/tenancy/assets/products/1/a.webp", root)
            == "https://teslashop.hu/tenancy/assets/products/1/a.webp")
    # a mar kanonikus es a relativ ertek valtozatlan
    assert sv.canon_url("https://teslashop.hu/hu/x", root) == "https://teslashop.hu/hu/x"
    assert sv.canon_url("hu/x", root) == "hu/x"
    assert sv.canon_url("", root) == "" and sv.canon_url(None, root) == ""


def test_canon_url_az_indexcore_prefix_vagassal_egyutt():
    root, img = "https://teslashop.hu/", "https://teslashop.hu/tenancy/assets/products/"
    u = sv.canon_url("https://teslashop.mysellvio.com/hu/termek-1", root)
    m = sv.canon_url("https://teslashop.mysellvio.com/tenancy/assets/products/1/a.webp", root)
    r = ic.compact({"id": 1, "available": True, "price_gross": 1, "url": u, "image_url": m}, root, img)
    assert r["u"] == "hu/termek-1" and r["m"] == "1/a.webp"      # relativ lett -> a widget jol fuzi


def test_map_product():
    tree = {1003: None, 1008: 1003}
    depth = sv.build_depth(tree)
    p = {"id": 2236, "code": "TWC006-MB", "name": "Felnikupak",
         "brand": {"id": 1, "name": "TESERY"},
         "categories": {"1003": {"id": 1003, "name": "Model Y"},
                        "1008": {"id": 1008, "name": "Model Y, Felni"}},
         "price": {"brutto_price": 58600}, "is_visible": True,
         "is_available_for_order": True, "pretty_url": "https://x.hu/hu/a/termek/",
         "gallery": [{"file": "img.webp", "is_main": True}],
         "created_at": "2026-04-20T13:57:31.000000Z"}
    r = sv.map_product(p, {2236: [{"name": "Komp", "value": "model y"}]}, depth)
    assert r["sku"] == "TWC006-MB" and r["brand"] == "TESERY"
    assert r["category"] == "Model Y, Felni" and r["price_gross"] == 58600
    assert r["available"] is True and r["image_url"] == "img.webp"
    assert r["parameters"] == [{"name": "Komp", "value": "model y"}]
    assert r["created_day"] == 20563
    p["is_available_for_order"] = False
    assert sv.map_product(p, {}, depth)["available"] is False

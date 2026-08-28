"""kfsc/1: build-ideju scope az indexcore-ban - file-load import (fake-app-safe).

A suite mas tesztjei fake `app.services`-t hagyhatnak a sys.modules-ben, ezert a
modult kozvetlenul a fajlbol toltjuk be, nem `import app.search.indexcore`-ral.
"""
import importlib.util
import json
import pathlib
import tempfile

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "search" / "indexcore.py"
_spec = importlib.util.spec_from_file_location("indexcore_under_test", _P)
ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ic)


def _prod(pid, available=True, price=100000, brand="Brother", cat="Lezernyomtato",
          params=None):
    return {"id": pid, "sku": "SKU%s" % pid, "name": "Termek %s" % pid,
            "brand": brand, "category": cat, "price_gross": price,
            "available": available, "url": "https://x.hu/p%s" % pid,
            "image_url": "https://x.hu/i%s.jpg" % pid,
            "parameters": params or [], "created_day": 20000}


def test_scope_match_empty_means_everything():
    row = {"p": 100, "b": "Brother", "c": "Lezer", "a": 1}
    pm = {"technologia": ["Lezer"]}
    assert ic.scope_match(row, pm, None) is True
    assert ic.scope_match(row, pm, []) is True


def test_scope_match_exists():
    row = {"p": 100, "b": "Brother", "c": "Lezer", "a": 1}
    cond = [{"param": "technologia", "op": "exists"}]
    assert ic.scope_match(row, {"technologia": ["Lezer"]}, cond) is True
    assert ic.scope_match(row, {}, cond) is False
    assert ic.scope_match(row, {"technologia": []}, cond) is False


def test_scope_match_operators():
    row = {"p": 100000, "b": "Brother", "c": "Lezernyomtato", "a": 1}
    pm = {"technologia": ["Lezer"], "papirmeret": ["A4", "A3"], "sebesseg_ppm": ["18"]}
    assert ic.scope_match(row, pm, [{"param": "technologia", "op": "has_any",
                                     "value": ["Lezer"]}])
    # has_any kis/nagybetu-fuggetlen (a widget-szuro is igy mukodik)
    assert ic.scope_match(row, pm, [{"param": "technologia", "op": "has_any",
                                     "value": ["lezer"]}])
    assert not ic.scope_match(row, pm, [{"param": "technologia", "op": "has_any",
                                         "value": ["Tintasugaras"]}])
    # tobb-erteku parameter
    assert ic.scope_match(row, pm, [{"param": "papirmeret", "op": "has_any",
                                     "value": ["A3"]}])
    # `field` a kompakt soron
    assert ic.scope_match(row, pm, [{"field": "b", "op": "eq", "value": "Brother"}])
    assert not ic.scope_match(row, pm, [{"field": "b", "op": "eq", "value": "HP"}])
    assert ic.scope_match(row, pm, [{"field": "b", "op": "neq", "value": "HP"}])
    # numerikus mind a soron, mind a parameteren
    assert ic.scope_match(row, pm, [{"field": "p", "op": "gte", "value": 50000}])
    assert not ic.scope_match(row, pm, [{"field": "p", "op": "lte", "value": 50000}])
    assert ic.scope_match(row, pm, [{"param": "sebesseg_ppm", "op": "gte", "value": 10}])
    # a regi "v" kulcs is mukodik (a ruleset ket alakja)
    assert ic.scope_match(row, pm, [{"field": "b", "op": "eq", "v": "Brother"}])


def test_scope_match_conditions_are_and():
    row = {"p": 100000, "b": "Brother", "c": "Lezer", "a": 1}
    pm = {"technologia": ["Lezer"]}
    both = [{"param": "technologia", "op": "exists"},
            {"field": "p", "op": "gte", "value": 1000}]
    assert ic.scope_match(row, pm, both) is True
    bad = [{"param": "technologia", "op": "exists"},
           {"field": "p", "op": "lte", "value": 1000}]
    assert ic.scope_match(row, pm, bad) is False
    # egy elem maga is lehet lista (azon belul is ES)
    nested = [[{"param": "technologia", "op": "exists"},
               {"field": "p", "op": "gte", "value": 1000}]]
    assert ic.scope_match(row, pm, nested) is True


def test_build_index_scope_filters_index_and_params():
    prods = [
        _prod("1", params=[{"name": "technologia", "value": "Lezer"}]),
        _prod("2", params=[{"name": "technologia", "value": "Tintasugaras"}]),
        _prod("3", params=[{"name": "szin", "value": "Fekete"}]),   # nincs technologia
    ]
    with tempfile.TemporaryDirectory() as d:
        res = ic.build_index("t", prods, d, "https://x.hu/", "https://x.hu/",
                             scope=[{"param": "technologia", "op": "exists"}])
        assert res["count"] == 2
        assert res["scoped"] is True
        idx = json.load(open(d + "/index.json", encoding="utf-8"))
        assert [r["i"] for r in idx["products"]] == ["1", "2"]
        # a params.json is CSAK a bent maradt termekeket tartalmazza
        prm = json.load(open(d + "/params.json", encoding="utf-8"))
        assert set(prm["p"]) == {"1", "2"}
        man = json.load(open(d + "/manifest.json", encoding="utf-8"))
        assert man["count"] == 2


def test_build_index_without_scope_unchanged():
    """Scope nelkul a viselkedes valtozatlan - a tobbi tenant nem serul."""
    prods = [_prod("1", params=[{"name": "a", "value": "x"}]), _prod("2")]
    with tempfile.TemporaryDirectory() as d:
        res = ic.build_index("t", prods, d, "https://x.hu/", "https://x.hu/")
        assert res["count"] == 2
        assert res["scoped"] is False


def test_build_index_scope_with_and_without_only_available():
    tech = [{"name": "technologia", "value": "Lezer"}]
    prods = [_prod("1", available=True, params=tech),
             _prod("2", available=False, params=tech)]
    scope = [{"param": "technologia", "op": "exists"}]
    with tempfile.TemporaryDirectory() as d:
        res = ic.build_index("t", prods, d, "https://x.hu/", "https://x.hu/",
                             only_available=True, scope=scope)
        assert res["count"] == 1
    with tempfile.TemporaryDirectory() as d2:
        res2 = ic.build_index("t", prods, d2, "https://x.hu/", "https://x.hu/",
                              only_available=False, scope=scope)
        assert res2["count"] == 2
        idx = json.load(open(d2 + "/index.json", encoding="utf-8"))
        assert sorted(r["a"] for r in idx["products"]) == [0, 1]

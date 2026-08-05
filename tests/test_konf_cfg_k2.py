"""CX Konfigurator K2 — keszlet-szures, kep-prefix, rendezes-opciok.

Fajl-betoltes (nem app-import): a suite mas tesztjei fake app-modulokat
hagyhatnak a sys.modules-ben.
"""
import importlib.util as _ilu
import pathlib as _pl

_P = _pl.Path(__file__).resolve().parents[1] / "app" / "services" / "konfcfg.py"
_spec = _ilu.spec_from_file_location("konfcfg_k2", _P)
konfcfg = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(konfcfg)


def _base(**extra):
    cfg = {
        "enabled": True,
        "index_base": "https://codexpress.cloud/cx-search/demo",
        "questions": [{
            "id": "q1", "title": "Kerdes?", "type": "single",
            "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        }],
    }
    cfg.update(extra)
    return cfg


def test_stock_block_default_off():
    out = konfcfg.normalize_ruleset(_base())
    assert out["stock"]["only_available"] is False
    assert out["stock"]["label_in"]
    assert out["stock"]["label_out"]


def test_stock_only_available_on():
    out = konfcfg.normalize_ruleset(_base(stock={"only_available": True, "label_in": "Raktaron"}))
    assert out["stock"]["only_available"] is True
    assert out["stock"]["label_in"] == "Raktaron"


def test_image_prefix_csak_http():
    ok = konfcfg.normalize_ruleset(_base(image={"prefix": "https://shop.hu/img/", "suffix": ".webp"}))
    assert ok["image"]["prefix"] == "https://shop.hu/img/"
    assert ok["image"]["suffix"] == ".webp"
    bad = konfcfg.normalize_ruleset(_base(image={"prefix": "javascript:alert(1)"}))
    assert bad["image"]["prefix"] == ""


def test_result_sorts_whitelist_es_default():
    out = konfcfg.normalize_ruleset(_base(result={
        "top_n": 6, "more_n": 10,
        "sorts": ["ar_asc", "hamis_mod", "nepszeru", "ar_asc"],
        "sort_default": "ar_asc", "pin_label": "Top",
    }))
    assert out["result"]["top_n"] == 6
    assert out["result"]["more_n"] == 10
    assert out["result"]["sorts"] == ["ar_asc", "nepszeru"]
    assert out["result"]["sort_default"] == "ar_asc"
    assert out["result"]["pin_label"] == "Top"


def test_result_defaults():
    out = konfcfg.normalize_ruleset(_base())
    r = out["result"]
    assert r["sorts"] and "ajanlott" in r["sorts"]
    assert r["sort_default"] == "ajanlott"
    assert r["pin_label"]
    assert r["more_n"] > 0


def test_sort_default_ismeretlen_ertekre_ajanlott():
    out = konfcfg.normalize_ruleset(_base(result={"sort_default": "nincs_ilyen"}))
    assert out["result"]["sort_default"] == "ajanlott"


def test_form_roundtrip_stock_only():
    cfg = _base(stock={"only_available": True}, result={"top_n": 4})
    form = konfcfg.config_to_form(cfg)
    assert form["stock_only"] is True
    form["stock_only"] = False
    form["top_n"] = 3
    back, err = konfcfg.form_to_config(form)
    assert err is None
    assert back["stock"]["only_available"] is False
    assert back["result"]["top_n"] == 3
    assert back["index_base"] == cfg["index_base"]


def test_more_open_es_step():
    d = konfcfg.normalize_ruleset(_base())["result"]
    assert d["more_open"] == 10 and d["more_step"] == 10
    r = konfcfg.normalize_ruleset(_base(result={
        "more_n": 200, "more_open": 25, "more_step": 5}))["result"]
    assert r["more_n"] == 200 and r["more_open"] == 25 and r["more_step"] == 5
    hi = konfcfg.normalize_ruleset(_base(result={"more_open": 999, "more_step": 0}))["result"]
    assert hi["more_open"] == 50 and hi["more_step"] == 1

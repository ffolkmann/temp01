"""S3 - SmartSearch tenant-config parser/formatter (app/services/searchcfg.py).

Fajlbol toltve (suite-konvencio): a modul stdlib-only, app-importot nem hasznal,
igy a fake-app-os tesztfajlok sys.modules-szennyezese nem szamit.
"""

import importlib.util
import json
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "searchcfg.py"
_spec = importlib.util.spec_from_file_location("searchcfg_s3_under_test", _P)
SC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SC)


# --------------------------------------------------------------------------- #
# szinonimak
# --------------------------------------------------------------------------- #
def test_groups_min_ket_tag_es_trim():
    out = SC.parse_groups("  karbon ,  carbon , szenszalas \n egyedul \n\n felni,kerek ")
    assert out == [["karbon", "carbon", "szenszalas"], ["felni", "kerek"]]


def test_groups_max_nyolc_tag():
    assert SC.parse_groups("a,b,c,d,e,f,g,h,i,j") == [["a", "b", "c", "d", "e", "f", "g", "h"]]


def test_groups_to_text_es_vissza():
    txt = SC.groups_to_text([["felni", "kerek"], ["egytag"], "nem lista"])
    assert txt == "felni, kerek"
    assert SC.parse_groups(txt) == [["felni", "kerek"]]


def test_oneway_parse_es_formaz():
    out = SC.parse_oneway("felnik > felni\nnincs nyil\n > csak cel\nnoti > notebook, laptop")
    assert out == [{"f": "felnik", "t": ["felni"]}, {"f": "noti", "t": ["notebook", "laptop"]}]
    assert SC.oneway_to_text(out) == "felnik > felni\nnoti > notebook, laptop"


# --------------------------------------------------------------------------- #
# nepszeru listak
# --------------------------------------------------------------------------- #
def test_terms_cap_nyolc_skus_cap_tiz():
    assert len(SC.parse_terms("\n".join("t%d" % i for i in range(20)))) == 8
    assert len(SC.parse_skus("\n".join("S%d" % i for i in range(20)))) == 10


def test_lista_szoveg_oda_vissza():
    assert SC.list_to_text(["A1", "  ", "B2"]) == "A1\nB2"
    assert SC.parse_skus("A1\n\nB2") == ["A1", "B2"]


# --------------------------------------------------------------------------- #
# merchandising
# --------------------------------------------------------------------------- #
def test_merch_teljes_sor():
    out = SC.parse_merch("felni, kerek | A1, B2 | front | 2026-08-01 | 2026-08-31")
    assert out == [{"kw": ["felni", "kerek"], "skus": ["A1", "B2"], "w": "front",
                    "from": "2026-08-01", "to": "2026-08-31"}]


def test_merch_alapertelmezett_suly_es_kiesok():
    out = SC.parse_merch("kw | A1\nkw | | front\nkw | B2 | nincsilyen\n | C3 | back")
    assert out == [{"kw": ["kw"], "skus": ["A1"], "w": "front"},
                   {"kw": [], "skus": ["C3"], "w": "back"}]


def test_merch_hibas_datum_kiesik_nem_dob():
    out = SC.parse_merch("kw | A1 | up | tegnap | 2026-13-99")
    assert out == [{"kw": ["kw"], "skus": ["A1"], "w": "up"}]


def test_merch_szoveg_oda_vissza():
    txt = "felni | A1, B2 | front | 2026-08-01 | 2026-08-31"
    assert SC.merch_to_text(SC.parse_merch(txt)) == txt


# --------------------------------------------------------------------------- #
# urlap <-> config
# --------------------------------------------------------------------------- #
def _form():
    return {
        "enabled": "true",
        "synonyms": "karbon, carbon\nfelni, kerek",
        "oneway": "felnik > felni",
        "popular_terms": "uleshuzat\npadloszonyeg",
        "popular_skus": "TFM004-3BR\nTSL2902-A",
        "merch": "felni | A1 | front | 2026-08-01 | 2026-08-31",
    }


def test_form_to_config_kanonikus_kulcsok():
    cfg = SC.form_to_config(_form())
    assert set(cfg) == {"enabled", "synonyms", "oneway", "popular_terms", "popular_skus", "merch"}
    assert cfg["enabled"] is True
    assert cfg["synonyms"] == [["karbon", "carbon"], ["felni", "kerek"]]
    assert cfg["popular_skus"] == ["TFM004-3BR", "TSL2902-A"]


def test_korbefordulas_idempotens():
    cfg = SC.form_to_config(_form())
    assert SC.form_to_config(SC.config_to_form(cfg)) == cfg


def test_szemet_bemenet_nem_dob():
    assert SC.form_to_config(None)["synonyms"] == []
    assert SC.form_to_config("nem dict")["enabled"] is False
    form = SC.config_to_form({"synonyms": "nem lista", "merch": 42, "oneway": None})
    assert form["synonyms"] == "" and form["merch"] == "" and form["oneway"] == ""
    assert SC.config_to_form(None)["popular_terms"] == ""


def test_enabled_ertekek():
    for truthy in (True, "true", "on", "1", 1):
        assert SC.form_to_config({"enabled": truthy})["enabled"] is True
    for falsy in (False, "false", "", None, 0, "nope"):
        assert SC.form_to_config({"enabled": falsy})["enabled"] is False


# --------------------------------------------------------------------------- #
# fajl-fallback + index-manifest
# --------------------------------------------------------------------------- #
def test_load_file_config(tmp_path):
    p = tmp_path / "smartsearch.json"
    p.write_text(json.dumps({"tenants": {"teslashop": {"enabled": True}}}), encoding="utf-8")
    assert SC.load_file_config("teslashop", str(p)) == {"enabled": True}
    assert SC.load_file_config("nincsilyen", str(p)) == {}
    assert SC.load_file_config("teslashop", "/nincs/ilyen.json") == {}


def test_index_info_ervenyes_manifest(tmp_path):
    d = tmp_path / "teslashop"
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"tenant": "teslashop", "v": "abc123", "count": 5289,
                    "built_at": 1785829039, "pcount": 3736}), encoding="utf-8")
    info = SC.index_info("teslashop", base=str(tmp_path))
    assert info["ok"] is True and info["count"] == 5289 and info["pcount"] == 3736
    assert info["version"] == "abc123" and info["built_at"] == 1785829039


def test_index_info_hiba_es_hianyzo(tmp_path):
    assert SC.index_info("teslashop", base=str(tmp_path))["ok"] is False
    d = tmp_path / "hibas"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"error": "fetch: 401"}), encoding="utf-8")
    info = SC.index_info("hibas", base=str(tmp_path))
    assert info["ok"] is False and "401" in info["error"]
    d2 = tmp_path / "torott"
    d2.mkdir()
    (d2 / "manifest.json").write_text("{nem json", encoding="utf-8")
    assert SC.index_info("torott", base=str(tmp_path))["ok"] is False

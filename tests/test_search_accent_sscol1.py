"""sscol/1: akcentus-szin normalizalas (searchcfg), file-load importtal.

A suite mas tesztjei fake `app.services` csomagot hagynak a sys.modules-ben,
ezert a modult kozvetlenul a fajlbol toltjuk be.
"""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "searchcfg.py"
_spec = importlib.util.spec_from_file_location("searchcfg_sscol1", _P)
cfgmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfgmod)


def test_accent_normalizal():
    assert cfgmod.parse_accent("#A3C748") == "#a3c748"
    assert cfgmod.parse_accent("a3c748") == "#a3c748"
    assert cfgmod.parse_accent("#ABC") == "#aabbcc"
    assert cfgmod.parse_accent("  #a3c748  ") == "#a3c748"


def test_accent_hibas_ertek_ures():
    for bad in ("", None, "piros", "#12345", "#gggggg", "rgb(1,2,3)", 12):
        assert cfgmod.parse_accent(bad) == ""


def test_accent_urlap_ket_iranyban():
    assert cfgmod.form_to_config({"accent": "#A3C748"})["accent"] == "#a3c748"
    assert cfgmod.config_to_form({"accent": "a3c748"})["accent"] == "#a3c748"


def test_accent_nelkul_minden_marad():
    cfg = cfgmod.form_to_config({})
    assert cfg["accent"] == ""
    old = {"shoprenter": {"categories": [1]}, "server": {"enabled": True}}
    merged = cfgmod.merge_preserving(old, cfg)
    assert merged["shoprenter"] == {"categories": [1]}
    assert merged["server"] == {"enabled": True}
    assert merged["accent"] == ""

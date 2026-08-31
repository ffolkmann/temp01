"""kfsw/1: stock.toggle normalizalasa - file-load import (fake-app-safe)."""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konfcfg.py"
_spec = importlib.util.spec_from_file_location("konfcfg_under_test", _P)
kc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kc)

BASE = {"enabled": True, "index_base": "https://x.hu/cx-search/t"}


def test_stock_toggle_defaults_off():
    out = kc.normalize_ruleset(dict(BASE))
    st = out["stock"]
    assert st["toggle"] is False
    assert st["toggle_label"] == "Csak raktáron lévők"
    assert st["toggle_all_label"] == "Rendelhetők is"
    # a regi mezok valtozatlanok
    assert st["only_available"] is False
    assert st["label_in"] == "Készleten"


def test_stock_toggle_roundtrip():
    cfg = dict(BASE)
    cfg["stock"] = {"toggle": True, "only_available": False,
                    "toggle_label": "Csak keszleten", "toggle_all_label": "Minden"}
    st = kc.normalize_ruleset(cfg)["stock"]
    assert st["toggle"] is True
    assert st["only_available"] is False
    assert st["toggle_label"] == "Csak keszleten"
    assert st["toggle_all_label"] == "Minden"


def test_stock_toggle_bad_values():
    cfg = dict(BASE)
    cfg["stock"] = {"toggle": "yes", "toggle_label": "x" * 500}
    st = kc.normalize_ruleset(cfg)["stock"]
    assert st["toggle"] is True
    assert len(st["toggle_label"]) <= 60

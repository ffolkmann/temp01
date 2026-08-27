"""kfcat/2: ruleset-szintu scope a normalize_ruleset-ben (file-load import, fake-app-safe)."""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konfcfg.py"
_spec = importlib.util.spec_from_file_location("konfcfg_scope_under_test", _P)
kc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kc)

_Q = [{"id": "q", "title": "K?", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}]


def _cfg(**over):
    c = {"enabled": True, "index_base": "https://codexpress.cloud/cx-search/x", "questions": _Q}
    c.update(over)
    return c


def test_scope_default_empty():
    out = kc.normalize_ruleset(_cfg())
    assert out["scope"] == []
    assert out["enabled"] is True


def test_scope_normalized_and_invalid_dropped():
    out = kc.normalize_ruleset(_cfg(scope=[
        {"param": "Technologia", "op": "exists"},
        {"field": "c", "op": "has_any", "value": ["Nyomtat\u00f3", ""]},
        {"field": "zz", "op": "eq", "value": "x"},          # ismeretlen mezo -> kiesik
        {"param": "p", "op": "nincs_ilyen", "value": 1},      # ismeretlen op -> kiesik
        "szemet",
    ]))
    assert out["scope"] == [
        {"param": "technologia", "op": "exists"},
        {"field": "c", "op": "has_any", "value": ["Nyomtat\u00f3"]},
    ]


def test_scope_not_list_is_empty():
    assert kc.normalize_ruleset(_cfg(scope={"param": "x"}))["scope"] == []
    assert kc.normalize_ruleset(_cfg(scope="x"))["scope"] == []


def test_scope_survives_admin_form_roundtrip():
    raw = _cfg(scope=[{"param": "technologia", "op": "exists"}])
    form = kc.config_to_form(raw)
    cfg, err = kc.form_to_config(form, fallback=raw)
    assert err is None and cfg["scope"] == raw["scope"]
    # config_json nelkul (ures urlap) a fallback viszi a scope-ot
    cfg2, _ = kc.form_to_config({"enabled": True}, fallback=raw)
    assert cfg2["scope"] == raw["scope"]

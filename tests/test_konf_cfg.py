"""K2: Konfigurator config-normalizalo tiszta fuggvenyei — file-load import."""
import importlib.util
import json
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konfcfg.py"
_spec = importlib.util.spec_from_file_location("konfcfg_under_test", _P)
kc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kc)


def _base_cfg():
    return {
        "enabled": True,
        "index_base": "https://codexpress.cloud/cx-search/copygo",
        "ui": {"title": "Nyomtato-valaszto", "accent": "#d02b20", "unit": "nyomtato"},
        "questions": [
            {"id": "szin", "title": "Szines?", "type": "single",
             "options": [
                 {"id": "s", "label": "Szines",
                  "filter": [{"param": "szinkezeles", "op": "eq", "value": "Szines"}]},
                 {"id": "m", "label": "Mono",
                  "filter": [{"param": "szinkezeles", "op": "eq", "value": "Mono"}],
                  "boost": [{"param": "sebesseg_ppm", "op": "gte", "value": 20, "w": 10}]},
             ]},
        ],
        "prior": {"pin": ["SKU1"], "boost": "SKU2, SKU3", "stock_w": 25},
        "result": {"top_n": 4},
        "lead": {"enabled": True, "post_url": "https://n8n.example.com/webhook/x",
                 "fallback_email": "info@x.hu"},
    }


def test_normalize_full():
    body = kc.normalize_ruleset(_base_cfg())
    assert body["enabled"] is True
    assert body["index_base"].startswith("https://")
    assert len(body["questions"]) == 1
    q = body["questions"][0]
    assert q["type"] == "single" and len(q["options"]) == 2
    assert q["options"][1]["boost"][0]["w"] == 10
    assert body["prior"]["pin"] == ["SKU1"]
    assert body["prior"]["boost"] == ["SKU2", "SKU3"]     # string -> lista
    assert body["prior"]["sale_w"] == 8                    # default
    assert body["result"]["top_n"] == 4
    assert body["lead"]["enabled"] is True


def test_normalize_drops_invalid():
    cfg = _base_cfg()
    cfg["questions"][0]["options"][0]["filter"] = [
        {"param": "x", "op": "nemletezik", "value": "y"},   # rossz op -> kiesik
        {"op": "eq", "value": "y"},                          # nincs param/field -> kiesik
        {"param": "sebesseg_ppm", "op": "gte", "value": "nem szam"},  # gte nem szam -> kiesik
        {"field": "zz", "op": "eq", "value": "y"},           # rossz field -> kiesik
        {"field": "c", "op": "eq", "value": "Fotonyomtato"},  # jo
    ]
    body = kc.normalize_ruleset(cfg)
    f = body["questions"][0]["options"][0]["filter"]
    assert f == [{"field": "c", "op": "eq", "value": "Fotonyomtato"}]


def test_normalize_disabled_paths():
    cfg = _base_cfg()
    cfg["questions"][0]["options"] = cfg["questions"][0]["options"][:1]  # 1 opcio -> kerdes kiesik
    body = kc.normalize_ruleset(cfg)
    assert body["questions"] == [] and body["enabled"] is False
    cfg2 = _base_cfg()
    cfg2["index_base"] = "ftp://rossz"
    assert kc.normalize_ruleset(cfg2)["enabled"] is False
    assert kc.normalize_ruleset(None)["enabled"] is False


def test_has_any_and_caps():
    c = kc.norm_cond({"param": "funkciok", "op": "has_any", "value": ["A", "", "B"]})
    assert c["value"] == ["A", "B"]
    assert kc.norm_cond({"param": "funkciok", "op": "has_any", "value": []}) is None
    c2 = kc.norm_cond({"param": "x", "op": "eq", "value": "y", "w": "9999"}, with_w=True)
    assert c2["w"] == 1000  # felso kapu


def test_form_roundtrip():
    form = kc.config_to_form(_base_cfg())
    assert form["enabled"] is True and "SKU1" in form["pin"]
    cfg, err = kc.form_to_config(
        {"config_json": form["config_json"], "enabled": False,
         "pin": "AAA, BBB\nCCC", "boost": "", "top_n": 6})
    assert err is None
    assert cfg["enabled"] is False
    assert cfg["prior"]["pin"] == ["AAA", "BBB", "CCC"]
    assert cfg["prior"]["boost"] == []
    assert cfg["result"]["top_n"] == 6
    assert cfg["questions"]  # a JSON-torzs megmaradt


def test_form_bad_json():
    cfg, err = kc.form_to_config({"config_json": "{nem json", "enabled": True})
    assert cfg is None and "JSON" in err


def test_form_empty_json_uses_fallback():
    cfg, err = kc.form_to_config({"config_json": "", "enabled": True, "pin": "P1"},
                                 fallback=_base_cfg())
    assert err is None and cfg["questions"] and cfg["prior"]["pin"] == ["P1"]


def test_load_file_config(tmp_path):
    p = tmp_path / "konfigurator.json"
    p.write_text(json.dumps({"tenants": {"copygo": {"enabled": True}}}), encoding="utf-8")
    assert kc.load_file_config("copygo", str(p)) == {"enabled": True}
    assert kc.load_file_config("masik", str(p)) == {}
    assert kc.load_file_config("copygo", str(tmp_path / "nincs.json")) == {}

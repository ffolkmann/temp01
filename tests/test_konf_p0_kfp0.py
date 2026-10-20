"""kfp0: P0-v1 kor - konf_extra, hide_params, draft-overlay, uj ruleset-kulcsok."""
import ast
import importlib.util
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_konfcfg():
    sp = importlib.util.spec_from_file_location("konfcfg_kfp0", ROOT / "app" / "services" / "konfcfg.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _funcs(path, names, extra=None):
    """Tiszta fuggvenyek kiemelese AST-bol (a modul nehez importjai nelkul)."""
    src = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    keep = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            keep.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in names for t in node.targets):
            keep.append(node)
    mod = ast.Module(body=keep, type_ignores=[])
    ns = {"Any": Any}
    ns.update(extra or {})
    exec(compile(mod, str(path), "exec"), ns)
    return ns


K = _load_konfcfg()
M = _funcs("app/search/__main__.py", {"hide_params", "konf_extra_blocks", "_SFX_OK", "_SFX_RESERVED"})
A = _funcs("app/api/konf.py", {"draft_overlay"})

BASE_Q = [{"id": "a", "title": "A?", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}]}]


def test_legacy_ruleset_gets_no_new_question_keys():
    body = K.normalize_ruleset({"enabled": True, "index_base": "https://x/y", "questions": BASE_Q})
    q = body["questions"][0]
    assert "show_if" not in q and "max" not in q
    for o in q["options"]:
        assert "exclusive" not in o and "goto" not in o
    assert body["result"]["rank"] == ""
    assert body["prior"]["preferred"] == []
    assert body["prior"]["preferred_ratio"] == 0.95


def test_new_keys_normalized():
    qs = [
        {"id": "q4", "title": "Szken?", "options": [{"id": "nem", "label": "Nem"}, {"id": "igen", "label": "Igen"}]},
        {"id": "q4a", "title": "ADF?", "show_if": [{"q": "q4", "any": ["igen", ""]}, "rossz"],
         "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]},
        {"id": "q9", "title": "Kotelezo?", "type": "multi", "max": 2,
         "options": [{"id": "wifi", "label": "Wifi"}, {"id": "nincs", "label": "Nincs", "exclusive": 1}]},
        {"id": "sp", "title": "Spec?", "type": "single", "max": 3, "options": [
            {"id": "c", "label": "Cimke", "goto": {"url": "https://bolt/cimke", "label": "Tovabb"}},
            {"id": "m", "label": "Mas", "goto": {"lead": True, "title": "Irj nekunk"}},
            {"id": "z", "label": "Rossz", "goto": {"url": "javascript:1"}}]},
    ]
    body = K.normalize_ruleset({
        "enabled": True, "index_base": "https://x/y", "questions": qs,
        "prior": {"preferred": [{"param": "prioritas", "op": "eq", "value": "Igen"}], "preferred_ratio": "0.9"},
        "result": {"rank": "TIERED"}})
    q4a, q9, sp = body["questions"][1], body["questions"][2], body["questions"][3]
    assert q4a["show_if"] == [{"q": "q4", "any": ["igen"]}]
    assert q9["max"] == 2 and q9["options"][1]["exclusive"] is True
    assert "max" not in sp                       # single kerdesen nincs max
    assert sp["options"][0]["goto"]["url"] == "https://bolt/cimke"
    assert sp["options"][1]["goto"]["lead"] is True
    assert "goto" not in sp["options"][2]        # nem-http url, lead nelkul -> kiesik
    assert body["result"]["rank"] == "tiered"
    assert body["prior"]["preferred"] == [{"param": "prioritas", "op": "eq", "value": "Igen"}]
    assert body["prior"]["preferred_ratio"] == 0.9


def test_boost_fallback_one_level():
    c = K.norm_cond({"param": "terhelhetoseg", "op": "has_any", "value": ["4-10 fo"], "w": 60,
                     "fallback": [{"param": "lan", "op": "eq", "value": "Igen", "w": 20,
                                   "fallback": [{"param": "x", "op": "exists", "w": 5}]},
                                  {"op": "eq"}]}, with_w=True)
    assert c["w"] == 60
    assert c["fallback"] == [{"param": "lan", "op": "eq", "value": "Igen", "w": 20}]
    # filter-feltetelen (with_w=False) nincs fallback
    f = K.norm_cond({"param": "a", "op": "exists", "fallback": [{"param": "b", "op": "exists"}]})
    assert "fallback" not in f


def test_hide_params():
    prods = [{"id": 1, "parameters": [{"name": "adatverzio", "value": "P0-v1"},
                                      {"name": "funkciok", "value": "Nyomtatas"},
                                      {"name": " prioritas ", "value": "Igen"}]},
             {"id": 2}]
    out = M["hide_params"](prods, ["adatverzio", "prioritas"])
    assert [x["name"] for x in out[0]["parameters"]] == ["funkciok"]
    assert len(prods[0]["parameters"]) == 3      # az eredeti erintetlen
    assert out[1] == {"id": 2}
    assert M["hide_params"](prods, None) is prods
    assert M["hide_params"](prods, "adatverzio") is prods


def test_konf_extra_blocks():
    cfg = {"konf_extra": [
        {"enabled": True, "suffix": "-konfpv", "scope": []},
        {"enabled": True, "suffix": "-konfpv"},          # ismetlodo
        {"enabled": True, "suffix": "-konf"},            # foglalt
        {"enabled": True, "suffix": "konfx"},            # nincs kotojel
        {"enabled": True, "suffix": "-a/b"},             # rossz karakter
        {"enabled": False, "suffix": "-off"},
    ]}
    got = M["konf_extra_blocks"](cfg)
    assert [s for s, _ in got] == ["-konfpv"]
    assert M["konf_extra_blocks"]({}) == []
    assert M["konf_extra_blocks"]({"konf_extra": "x"}) == []


def test_draft_overlay():
    cfg = {"enabled": False, "index_base": "https://a/live", "questions": [1],
           "draft": {"index_base": "https://a/pv", "questions": [2], "draft": {"x": 1}}}
    eff = A["draft_overlay"](cfg)
    assert eff["index_base"] == "https://a/pv" and eff["questions"] == [2]
    assert "draft" not in eff and eff["enabled"] is False
    assert A["draft_overlay"]({"enabled": True}) is None
    assert A["draft_overlay"]({"draft": {}}) is None

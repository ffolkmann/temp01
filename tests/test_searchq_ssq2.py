"""ssq/2: szerver-oldali kereso-mag (app/services/searchq.py) - file-load import + FAKE Qdrant.

A fake a Qdrant szuro-nyelvet (must / should / min_should / match value|any|text / range)
memoria-pontokon ertekeli ki, a pontokat a valodi qdrantout.make_point() gyartja -> a
build- es a kereso-oldal EGYUTT van tesztelve (tokenizalas, ft-prefix, ritka vektor).
"""
import asyncio
import importlib.util
import json
import os
import pathlib
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qo = _load("app/search/qdrantout.py", "ssq2_qdrantout")
sq = _load("app/services/searchq.py", "ssq2_searchq")
qt = sq.qtext


# --------------------------------------------------------------------------- #
# fake Qdrant (async, szuro-kiertekelovel)
# --------------------------------------------------------------------------- #
def _match(cond, pl):
    if any(k in cond for k in ("must", "should", "min_should")):
        return _filter(cond, pl)
    v = pl.get(cond.get("key"))
    m, rng = cond.get("match"), cond.get("range")
    if m is not None:
        if "value" in m:
            return v == m["value"]
        if "any" in m:
            vals = v if isinstance(v, list) else [v]
            return any(x in m["any"] for x in vals)
        if "text" in m:
            words = str(v or "").split()
            return all(any(w.startswith(t) for w in words) for t in m["text"].split())
    if rng is not None:
        if v is None:
            return False
        if "gte" in rng and not v >= rng["gte"]:
            return False
        if "lt" in rng and not v < rng["lt"]:
            return False
        return True
    return False


def _filter(f, pl):
    if not all(_match(c, pl) for c in f.get("must") or []):
        return False
    sh = f.get("should")
    if sh and not any(_match(c, pl) for c in sh):
        return False
    ms = f.get("min_should")
    if ms and sum(1 for c in ms["conditions"] if _match(c, pl)) < ms["min_count"]:
        return False
    return True


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b, self.text = status, body, json.dumps(body)

    def json(self):
        return self._b


class FakeQdrant:
    def __init__(self, points):
        self.points = points          # [{"id", "payload", "vector": {"lex": {...}}}]
        self.calls = []

    def _sel(self, flt):
        return [p for p in self.points if _filter(flt or {}, p["payload"])]

    async def post(self, path, json=None):
        self.calls.append(path)
        body = json or {}
        if path.endswith("/points/count"):
            return _Resp({"result": {"count": len(self._sel(body.get("filter")))}})
        if path.endswith("/points/query"):
            qv = dict(zip(body["query"]["indices"], body["query"]["values"]))
            out = []
            for p in self._sel(body.get("filter")):
                dv = dict(zip(p["vector"]["lex"]["indices"], p["vector"]["lex"]["values"]))
                s = sum(qv[i] * dv[i] for i in qv if i in dv)
                out.append({"id": p["id"], "score": s, "payload": p["payload"]})
            out.sort(key=lambda x: -x["score"])
            return _Resp({"result": {"points": out[:body.get("limit", 10)]}})
        if path.endswith("/points/scroll"):
            sel = self._sel(body.get("filter"))
            ob = body.get("order_by")
            if ob:
                sel = [p for p in sel if p["payload"].get(ob["key"]) is not None]
                sel.sort(key=lambda p: p["payload"][ob["key"]], reverse=ob.get("direction") == "desc")
            return _Resp({"result": {"points": [{"id": p["id"], "payload": p["payload"]} for p in sel[:body.get("limit", 10)]]}})
        if path.endswith("/facet"):
            cnt = {}
            for p in self._sel(body.get("filter")):
                v = p["payload"].get(body["key"])
                for x in (v if isinstance(v, list) else [v]):
                    if x not in (None, ""):
                        cnt[x] = cnt.get(x, 0) + 1
            hits = [{"value": k, "count": n} for k, n in sorted(cnt.items(), key=lambda x: -x[1])]
            return _Resp({"result": {"hits": hits[:body.get("limit", 10)]}})
        return _Resp({"status": {"error": "unknown " + path}}, 404)


def _row(i, n, k="", b="Epson", c="Nyomtató", p=100000, a=1, px=()):
    return {"i": str(i), "k": k or "SKU-%s" % i, "n": n, "b": b, "c": c, "p": p, "a": a,
            "u": "/p%s" % i, "m": "i%s.jpg" % i, "d": 20000}, list(px)


ROWS = [
    _row(1, "Epson WF-M5899 mono nyomtató", k="WF-M5899", p=180000, px=["technologia=Tintasugaras", "szin=Mono"]),
    _row(2, "Epson EM-C800 színes nyomtató", k="EM-C800", p=250000, a=0, px=["technologia=Tintasugaras", "szin=Színes"]),
    _row(3, "HP LaserJet Pro M404 nyomtató", b="HP", p=90000, px=["technologia=Lézer", "szin=Mono"]),
    _row(4, "Brother DCP-L3520CDW lézer", b="Brother", p=120000, px=["technologia=Lézer", "szin=Színes"]),
    _row(5, "Epson toner fekete", b="Epson", c="Toner", p=15000, px=["szin=Fekete"]),
    _row(6, "Lenovo Legion 5 laptop", b="Lenovo", c="Új notebook", p=450000, px=[]),
    _row(7, "Laptop táska 15.6", b="Dicota", c="Táska", p=9000, px=[]),
]


def _build(tmp, cid="t"):
    pts, df = [], {}
    for row, px in ROWS:
        pt, terms = qo.make_point(cid, row, px)
        pts.append(pt)
        for t in terms:
            df[t] = df.get(t, 0) + 1
    d = os.path.join(tmp, cid + "-q")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"tenant": cid, "v": "abc", "count": len(pts), "url_prefix": "https://x.hu",
                   "img_prefix": "https://x.hu/img/", "collection": "cx_search_t_1", "alias": "cx_search_t"}, f)
    with open(os.path.join(d, "vocab.json"), "w", encoding="utf-8") as f:
        json.dump({"v": "abc", "count": len(pts), "terms": sorted([[t, n] for t, n in df.items()])}, f)
    sq._cache.clear()
    return FakeQdrant(pts)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# --------------------------------------------------------------------------- #
# tiszta fuggvenyek
# --------------------------------------------------------------------------- #
def test_synonyms_builtin_plus_tenant():
    syn = sq.synonyms({"synonyms": [["toner", "festékkazetta", "x"], ["csak-egy"]]})
    assert syn["laptop"] == ["laptop", "notebook"] and syn["notebook"][0] == "laptop"
    assert syn["toner"] == ["toner", "festekkazetta"]          # 'x' 1 karakter: kiesik
    assert "csakegy" not in syn
    ow = sq.oneway({"oneway": [{"f": "noti", "t": ["notebook", "noti"]}, {"f": "a", "t": ["b"]}]})
    assert ow == {"noti": ["notebook"]}


def test_logical_groups_and_filters():
    syn, ow = sq.synonyms({}), {"noti": ["notebook"]}
    g = sq.logical_groups(["laptop", "noti", "tok"], syn, ow)
    assert g == [["laptop", "notebook"], ["noti", "notebook"], ["tok"]]
    f_and = sq.build_filter([{"key": "a", "match": {"value": True}}], g, "and")
    assert len(f_and["must"]) == 4 and "min_should" not in f_and
    assert f_and["must"][1] == {"should": [{"key": "ft", "match": {"text": "laptop"}},
                                           {"key": "ft", "match": {"text": "notebook"}}]}
    f_near = sq.build_filter([], g, "near")
    assert f_near["must"] == [] and f_near["min_should"]["min_count"] == 2
    f_or = sq.build_filter([], g, "or")
    assert f_or["min_should"]["min_count"] == 1


def test_base_conditions():
    b = sq.base_conditions(fb=["HP", "Epson"], fc=[], fpr="0,2,zz", fpx=["szin=Mono", "szin=Színes", "technologia=Lézer", "rossz"], avail=True)
    assert b["b"] == {"key": "b", "match": {"any": ["HP", "Epson"]}}
    assert "c" not in b
    assert b["pr"] == {"should": [{"key": "p", "range": {"gte": 0, "lt": 20000}},
                                  {"key": "p", "range": {"gte": 50000, "lt": 100000}}]}
    assert b["px:szin"] == {"key": "px", "match": {"any": ["szin=Mono", "szin=Színes"]}}
    assert b["px:technologia"]["match"]["any"] == ["technologia=Lézer"]
    assert b["a"] == {"key": "a", "match": {"value": True}}
    assert [k for k in sq.conds_except(b, "b")] and len(sq.conds_except(b, "b")) == 4
    assert sq.base_conditions(fpr="6")["pr"] == {"key": "p", "range": {"gte": 500000}}


def test_sparse_query_prefix_expansion():
    with tempfile.TemporaryDirectory() as tmp:
        _build(tmp)
        tix = sq.load_tenant("t", root=tmp)
        assert tix.expand("eps") == ["epson"] and tix.expand("epson") == []
        v = sq.sparse_query([["eps"]], tix)
        w = dict(zip(v["indices"], v["values"]))
        assert w[qt.term_id("eps")] == 1.0 and w[qt.term_id("epson")] == sq.PREFIX_W
        assert tix.expand("z") == []


def test_rerank_stock_intent_merch():
    hits = [(1.0, {"i": "1", "a": False, "c": "Toner", "ks": "a1"}),
            (1.0, {"i": "2", "a": True, "c": "Toner", "ks": "a2"}),
            (0.9, {"i": "3", "a": True, "c": "Új notebook", "ks": "a3"})]
    rows = sq.rerank(hits, ["epson"], "epson", [], 0.15)
    assert [r["i"] for r in rows] == ["2", "3", "1"]                 # keszlet-boost: 1.15 > 1.035 > 1.0
    rows = sq.rerank(hits, ["epson"], "epson", [], 0.0)
    assert [r["i"] for r in rows] == ["1", "2", "3"]                 # boost nelkul stabil
    rows = sq.rerank(hits, ["toner"], "toner", [], 0.15)
    assert [r["i"] for r in rows] == ["2", "1", "3"]                 # kiegeszito-intent: gep-kategoria hatra
    rows = sq.rerank(hits, ["legion"], "legion", [], 0.0)
    assert [r["i"] for r in rows][0] == "3"                           # gep-intent: gep-kategoria elore
    merch = [{"kw": ["toner"], "skus": ["a3"], "w": "front"}]
    rows = sq.rerank(hits, ["toner"], "toner", merch, 0.0)
    assert [r["i"] for r in rows] == ["3", "1", "2"]
    merch2 = [{"kw": ["masvalami"], "skus": ["a3"], "w": "front"}]
    assert [r["i"] for r in sq.rerank(hits, ["toner"], "toner", merch2, 0.0)] == ["1", "2", "3"]


def test_merch_rules_dates_and_fold():
    from datetime import date
    rules = sq.merch_rules({"merch": [
        {"kw": ["Épson"], "skus": ["WF-M5899"], "w": "front", "from": "2026-01-01", "to": "2026-12-31"},
        {"kw": [], "skus": ["X"], "w": "back", "to": "2026-01-01"},
        {"kw": [], "skus": ["Y"], "w": "sideways"}]}, today=date(2026, 8, 31))
    assert rules == [{"kw": ["epson"], "skus": ["wfm5899"], "w": "front"}]


# --------------------------------------------------------------------------- #
# search() vegig, fake Qdranttal
# --------------------------------------------------------------------------- #
def test_search_and_mode_hits_and_shape():
    with tempfile.TemporaryDirectory() as tmp:
        fq = _build(tmp)
        out = _run(sq.search(fq, {}, "t", "epson nyomtató", root=tmp))
        assert out["mode"] == "and" and out["total"] == 2
        ids = [h["i"] for h in out["hits"]]
        assert set(ids) == {"1", "2"} and ids[0] == "1"     # a keszleten levo elorebb (boost)
        h = out["hits"][0]
        assert set(h) >= {"i", "k", "n", "b", "c", "p", "a", "u", "m", "d"} and h["a"] == 1
        assert out["url_prefix"] == "https://x.hu" and out["v"] == "abc" and out["count"] == 7
        # prefix-gepeles: 'eps' -> minden Epson-termek
        out2 = _run(sq.search(fq, {}, "t", "eps", root=tmp))
        assert out2["total"] == 3 and out2["mode"] == "and"
        # cikkszam tomoritve
        out3 = _run(sq.search(fq, {}, "t", "wfm5899", root=tmp))
        assert out3["total"] == 1 and out3["hits"][0]["k"] == "WF-M5899"


def test_search_cascade_near_and_or():
    with tempfile.TemporaryDirectory() as tmp:
        fq = _build(tmp)
        # 2 token, az egyik nem letezik -> near (n-1=1) -> mode 'and' (widget-paritas)
        out = _run(sq.search(fq, {}, "t", "epson zzzz", root=tmp))
        assert out["mode"] == "and" and out["total"] == 3
        # 3 token, ketto nem letezik -> near(2) ures -> OR -> mode 'or'
        out2 = _run(sq.search(fq, {}, "t", "epson zzzz yyyy", root=tmp))
        assert out2["mode"] == "or" and out2["total"] == 3
        # semmi
        out3 = _run(sq.search(fq, {}, "t", "qqqq", root=tmp))
        assert out3["total"] == 0 and out3["hits"] == []


def test_search_synonyms_stop_and_empty_query():
    with tempfile.TemporaryDirectory() as tmp:
        fq = _build(tmp)
        out = _run(sq.search(fq, {}, "t", "notebook", root=tmp))     # beepitett: notebook <-> laptop
        assert out["total"] == 2 and {h["i"] for h in out["hits"]} == {"6", "7"}
        out2 = _run(sq.search(fq, {"synonyms": [["toner", "festékkazetta"]]}, "t", "festékkazetta", root=tmp))
        assert out2["total"] == 1 and out2["hits"][0]["i"] == "5"
        out3 = _run(sq.search(fq, {}, "t", "melyik epson nyomtató jó", root=tmp))   # toltelekszavak
        assert out3["total"] == 2
        out4 = _run(sq.search(fq, {}, "t", "", limit=3, root=tmp))
        assert out4["mode"] == "none" and out4["total"] == 7 and len(out4["hits"]) == 3


def test_search_filters_sort_paging_and_facets():
    with tempfile.TemporaryDirectory() as tmp:
        fq = _build(tmp)
        out = _run(sq.search(fq, {}, "t", "nyomtató", sort="pa", limit=2, offset=1, root=tmp))
        assert out["total"] == 4 and [h["i"] for h in out["hits"]] == ["4", "1"]   # 90k,120k,180k,250k -> [1:3]
        out2 = _run(sq.search(fq, {}, "t", "nyomtató", sort="pd", limit=1, root=tmp))
        assert out2["hits"][0]["i"] == "2"
        out3 = _run(sq.search(fq, {}, "t", "nyomtató", sort="nm", limit=10, root=tmp))
        assert [h["i"] for h in out3["hits"]] == ["4", "2", "1", "3"]
        out4 = _run(sq.search(fq, {}, "t", "nyomtató", avail=True, root=tmp))
        assert out4["total"] == 3
        out5 = _run(sq.search(fq, {}, "t", "nyomtató", fb=["HP"], fpx=["szin=Mono"], want_facets=True, root=tmp))
        assert out5["total"] == 1 and out5["hits"][0]["i"] == "3"
        fac = out5["facets"]
        # a marka-facet a SAJAT szuroje nelkul szamol (szin=Mono mellett): Epson 1 + HP 1
        assert dict(map(tuple, fac["b"])) == {"Epson": 1, "HP": 1}
        assert dict(map(tuple, fac["c"])) == {"Nyomtató": 1}
        assert fac["pr"]["2"] == 1 and fac["pr"]["3"] == 0
        # aktiv parameter-csoport a sajat szuroje nelkul: HP nyomtatoknal csak Mono
        assert fac["px"]["szin"] == [["Mono", 1]]
        out6 = _run(sq.search(fq, {}, "t", "nyomtató", fpr="0,1", root=tmp))
        assert out6["total"] == 0
        out7 = _run(sq.search(fq, {}, "t", "nyomtató", want_facets=True, root=tmp))
        assert out7["facets"]["px"] == {}          # widget-szabaly: need = max(5, 20%) -> 4 talalatnal nincs param-facet
        assert out7["facets"]["pr"] == {"0": 0, "1": 0, "2": 1, "3": 2, "4": 1, "5": 0, "6": 0}
        old_min = sq.FACET_MIN
        sq.FACET_MIN = 2
        try:
            out8 = _run(sq.search(fq, {}, "t", "nyomtató", want_facets=True, root=tmp))
        finally:
            sq.FACET_MIN = old_min
        assert out8["facets"]["px"]["technologia"] == [["Lézer", 2], ["Tintasugaras", 2]]
        assert out8["facets"]["px"]["szin"] == [["Mono", 2], ["Színes", 2]]


def test_unknown_tenant_raises():
    with tempfile.TemporaryDirectory() as tmp:
        fq = _build(tmp)
        try:
            _run(sq.search(fq, {}, "nincs", "x", root=tmp))
            assert False, "SearchUnavailable kellett volna"
        except sq.SearchUnavailable:
            pass

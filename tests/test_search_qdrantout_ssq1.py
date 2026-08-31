"""ssq/1: Qdrant kimeneti profil (app/search/qdrantout.py) + szoveg-paritas (qtext.py).

File-load import (a suite mas tesztjei fake `app.services`-t hagyhatnak a sys.modules-ben),
es FAKE Qdrant-kliens: a HTTP-utvonalakat egy memoria-allapot szolgalja ki.
"""
import importlib.util
import json
import pathlib
import tempfile

_D = pathlib.Path(__file__).resolve().parents[1] / "app" / "search"


def _load(name):
    spec = importlib.util.spec_from_file_location("ssq1_" + name, _D / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qt = _load("qtext")
qo = _load("qdrantout")


# --------------------------------------------------------------------------- #
# szoveg-paritas a widgettel (smartsearch.js fold/qTokens)
# --------------------------------------------------------------------------- #
def test_fold_and_words_parity():
    assert qt.fold("Épület Ő ű") == "epulet o u"
    assert qt.words("WF-M5899 Nyomtató") == ["wf", "m5899", "nyomtato"]
    # 'ß' nem bomlik egy karakterre -> marad, es elvalasztokent viselkedik (widget-szabaly)
    assert qt.words("Straße") == ["stra", "e"]
    assert qt.compact_sku("WF-M5899") == "wfm5899"
    assert qt.compact_sku("") == ""


def test_tokens_stopwords_only_from_three_words():
    assert qt.tokens("melyik nyomtato jo") == ["nyomtato"]
    assert qt.tokens("a nyomtato") == ["a", "nyomtato"]          # 2 szo: nincs szures
    assert qt.tokens("van egy jo") == ["van", "egy", "jo"]        # csupa toltelek: marad
    assert qt.tokens("  ") == []


def test_term_id_is_stable_u32():
    a = qt.term_id("epson")
    assert a == qt.term_id("epson")
    assert 0 <= a <= 0xFFFFFFFF
    assert a != qt.term_id("epsom")


# --------------------------------------------------------------------------- #
# pont-epites
# --------------------------------------------------------------------------- #
def _row(i="1", k="WF-M5899", n="Epson WF-M5899 nyomtató", b="Epson", c="Nyomtató",
         p=120000, a=1, d=20000, o=None):
    r = {"i": i, "k": k, "n": n, "b": b, "c": c, "p": p, "a": a, "u": "/p" + i, "m": "i.jpg", "d": d}
    if o:
        r["o"] = o
    return r


def test_doc_terms_field_boosts_add_up():
    w = qo.doc_terms(_row())
    assert w["epson"] == 4.5          # nev 3 + marka 1.5
    assert w["wf"] == 8.0             # nev 3 + cikkszam 5
    assert w["m5899"] == 8.0
    assert w["nyomtato"] == 4.0       # nev 3 + kategoria 1
    assert w["wfm5899"] == 5.0        # tomoritett cikkszam


def test_sparse_vector_sorted_unique():
    v = qo.sparse_vector({"b": 1.0, "a": 2.0})
    assert v["indices"] == sorted(v["indices"]) and len(set(v["indices"])) == 2
    assert len(v["values"]) == 2


def test_make_point_payload_and_id():
    pt, terms = qo.make_point("t", _row(o=150000), ["technologia=Tintasugaras"])
    pl = pt["payload"]
    assert pt["id"] == qo.point_id("t", "1") and pt["id"] != qo.point_id("u", "1")
    assert pl["a"] is True and pl["p"] == 120000.0 and pl["o"] == 150000.0
    assert pl["px"] == ["technologia=Tintasugaras"]
    assert pl["ks"] == "wfm5899" and pl["d"] == 20000
    assert set(pl["ft"].split()) == set(terms)
    assert "lex" in pt["vector"] and pt["vector"]["lex"]["indices"]
    pt2, _ = qo.make_point("t", _row(p=None, a=0), [])
    assert "p" not in pt2["payload"] and pt2["payload"]["a"] is False and "px" not in pt2["payload"]


# --------------------------------------------------------------------------- #
# fake Qdrant
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, body=None, status=200):
        self.status_code = status
        self._body = body if body is not None else {"result": {}}
        self.content = b"x"
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeQdrant:
    def __init__(self, lose_points=False, fail_create=False):
        self.cols = {}       # name -> {"points": {id: pt}, "indexes": []}
        self.aliases = {}    # alias -> name
        self.calls = []
        self.lose_points = lose_points
        self.fail_create = fail_create

    def request(self, method, path, json=None):
        self.calls.append((method, path))
        p = path.split("?")[0]
        if method == "GET" and p == "/collections":
            return _Resp({"result": {"collections": [{"name": n} for n in self.cols]}})
        if method == "GET" and p == "/aliases":          # a GYOKER /aliases (nem /collections/aliases)
            return _Resp({"result": {"aliases": [
                {"alias_name": a, "collection_name": n} for a, n in self.aliases.items()]}})
        if method == "POST" and p == "/collections/aliases":
            for act in json["actions"]:
                if "delete_alias" in act:
                    self.aliases.pop(act["delete_alias"]["alias_name"], None)
                if "create_alias" in act:
                    self.aliases[act["create_alias"]["alias_name"]] = act["create_alias"]["collection_name"]
            return _Resp()
        parts = p.split("/")
        name = parts[2] if len(parts) > 2 else ""
        if method == "PUT" and p == f"/collections/{name}":
            if self.fail_create:
                return _Resp({"status": {"error": "boom"}}, status=500)
            self.cols[name] = {"points": {}, "indexes": [], "cfg": json}
            return _Resp()
        if method == "PUT" and p == f"/collections/{name}/index":
            self.cols[name]["indexes"].append(json["field_name"])
            return _Resp()
        if method == "PUT" and p == f"/collections/{name}/points":
            pts = json["points"][1:] if self.lose_points else json["points"]
            for pt in pts:
                self.cols[name]["points"][pt["id"]] = pt
            return _Resp()
        if method == "POST" and p == f"/collections/{name}/points/count":
            real = self.aliases.get(name, name)
            n = len(self.cols[real]["points"]) if real in self.cols else 0
            return _Resp({"result": {"count": n}})
        if method == "DELETE" and p == f"/collections/{name}":
            self.cols.pop(name, None)
            return _Resp()
        return _Resp({"status": {"error": "unknown " + path}}, status=404)


def _prod(pid, available=True, params=None, price=100000):
    return {"id": pid, "sku": "SKU-%s" % pid, "name": "Termék %s Épson" % pid,
            "brand": "Epson", "category": "Nyomtató", "price_gross": price,
            "available": available, "url": "https://x.hu/p%s" % pid,
            "image_url": "https://x.hu/i%s.jpg" % pid,
            "parameters": params or [], "created_day": 20000}


def test_build_creates_collection_alias_manifest_vocab():
    fq = FakeQdrant()
    prods = [_prod("1", params=[{"name": "technologia", "value": "Lézer"}]),
             _prod("2", available=False), _prod("3")]
    with tempfile.TemporaryDirectory() as d:
        res = qo.build("t", prods, d, "https://x.hu/", "https://x.hu/", client=fq, batch=2)
        assert "error" not in res, res
        assert res["count"] == 3 and res["avail"] == 2 and res["batches"] == 2
        assert fq.aliases["cx_search_t"] == res["collection"]
        assert res["collection"].startswith("cx_search_t_")
        col = fq.cols[res["collection"]]
        assert len(col["points"]) == 3
        assert set(col["indexes"]) >= {"b", "c", "px", "ks", "a", "p", "ft"}
        assert col["cfg"]["sparse_vectors"]["lex"]["modifier"] == "idf"
        pt = col["points"][qo.point_id("t", "1")]
        assert pt["payload"]["px"] == ["technologia=Lézer"]
        assert pt["payload"]["a"] is True
        man = json.load(open(d + "/t-q/manifest.json", encoding="utf-8"))
        assert man["count"] == 3 and man["collection"] == res["collection"] and man["alias"] == "cx_search_t"
        voc = json.load(open(d + "/t-q/vocab.json", encoding="utf-8"))
        terms = [t for t, _ in voc["terms"]]
        assert terms == sorted(terms) and "epson" in terms
        df = dict(voc["terms"])
        assert df["epson"] == 3 and df["sku1"] == 1


def test_second_build_switches_alias_and_drops_old():
    fq = FakeQdrant()
    prods = [_prod("1"), _prod("2")]
    with tempfile.TemporaryDirectory() as d:
        r1 = qo.build("t", prods, d, "https://x.hu/", "https://x.hu/", client=fq)
        # ugyanabban a masodpercben azonos nev lenne -> a fake-ben atnevezzuk a regit
        old = r1["collection"]
        fq.cols["cx_search_t_20000101000000"] = fq.cols.pop(old)
        fq.aliases["cx_search_t"] = "cx_search_t_20000101000000"
        fq.cols["cx_search_t_19990101000000"] = {"points": {}, "indexes": []}   # arva, sikertelen build
        r2 = qo.build("t", prods + [_prod("3")], d, "https://x.hu/", "https://x.hu/", client=fq)
        assert "error" not in r2, r2
        assert fq.aliases["cx_search_t"] == r2["collection"]
        assert "cx_search_t_20000101000000" not in fq.cols
        assert "cx_search_t_19990101000000" not in fq.cols
        assert r2["prev"] == 2 and r2["count"] == 3
        assert any(a == "cx_search_t_20000101000000" for a in r2["removed"])


def test_min_ratio_guard_keeps_old_collection():
    fq = FakeQdrant()
    with tempfile.TemporaryDirectory() as d:
        r1 = qo.build("t", [_prod(str(i)) for i in range(10)], d, "https://x.hu/", "https://x.hu/", client=fq)
        ncols = len(fq.cols)
        r2 = qo.build("t", [_prod("1")], d, "https://x.hu/", "https://x.hu/", client=fq)
        assert "error" in r2 and "zsugorodas" in r2["error"]
        assert len(fq.cols) == ncols and fq.aliases["cx_search_t"] == r1["collection"]
        man = json.load(open(d + "/t-q/manifest.json", encoding="utf-8"))
        assert man["error"] and man["count"] == 10


def test_count_mismatch_after_upload_rolls_back():
    fq = FakeQdrant(lose_points=True)
    with tempfile.TemporaryDirectory() as d:
        r = qo.build("t", [_prod("1"), _prod("2")], d, "https://x.hu/", "https://x.hu/", client=fq)
        assert "error" in r and "darabszam" in r["error"]
        assert not fq.aliases and not fq.cols          # az uj kollekcio torolve, alias nincs


def test_qdrant_error_is_reported_not_raised():
    fq = FakeQdrant(fail_create=True)
    with tempfile.TemporaryDirectory() as d:
        r = qo.build("t", [_prod("1")], d, "https://x.hu/", "https://x.hu/", client=fq)
        assert "error" in r and r["error"].startswith("qdrant:")
        man = json.load(open(d + "/t-q/manifest.json", encoding="utf-8"))
        assert man["error"].startswith("qdrant:")


def test_scope_and_only_available():
    fq = FakeQdrant()
    tech = [{"name": "technologia", "value": "Lézer"}]
    prods = [_prod("1", params=tech), _prod("2", available=False, params=tech), _prod("3")]
    with tempfile.TemporaryDirectory() as d:
        r = qo.build("t", prods, d, "https://x.hu/", "https://x.hu/", client=fq,
                     scope=[{"param": "technologia", "op": "exists"}])
        assert r["count"] == 2 and r["avail"] == 1 and r["scoped"] is True
    fq2 = FakeQdrant()
    with tempfile.TemporaryDirectory() as d2:
        r2 = qo.build("t", prods, d2, "https://x.hu/", "https://x.hu/", client=fq2, only_available=True)
        assert r2["count"] == 2 and r2["avail"] == 2


def test_empty_products_error():
    fq = FakeQdrant()
    with tempfile.TemporaryDirectory() as d:
        r = qo.build("t", [], d, "https://x.hu/", "https://x.hu/", client=fq)
        assert "error" in r and not fq.cols

"""m122: laza kereso-modok szigoritasa + nem letezo tipusszam jelzese + HTML-entitas a nevekben.

Kivalto eset (Hungarotoner / copygo, 2026-10-16): 'Western Digital Purple SC QD101 256GB'
-> 2003 talalat OR-modban (barmelyik szo eleg volt, az 'sc' prefixkent a 'scanner'-re is
illeszkedett), a QD101 termek nincs a boltban, a nevekben '3.5&quot;' latszott.

A fake Qdrant es a pont-epites a test_searchq_ssq2.py-bol jon (file-load, sajat modulnevvel).
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


t2 = _load("tests/test_searchq_ssq2.py", "m122_ssq2")
sq, qo = t2.sq, t2.qo
ic = _load("app/search/indexcore.py", "m122_indexcore")

R = t2._row
ROWS = [
    R(1, 'WESTERN DIGITAL 3.5" HDD SATA-III 4TB 5400rpm 256MB Cache, CAVIAR Purple', b="Western Digital", c="HDD"),
    R(2, "Western Digital Elements kulso HDD 2TB", b="Western Digital", c="HDD"),
    R(3, "Canon scanner LiDE 300", b="Canon", c="Szkenner"),
    R(4, "Purple toll keszlet", b="Noname", c="Iroszer"),
    R(5, "Digital fenykepezo kamera", b="Noname", c="Foto"),
    R(6, "HP LaserJet Pro M404dn nyomtato", b="HP", c="Nyomtato"),
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
        json.dump({"tenant": cid, "v": "m122", "count": len(pts), "url_prefix": "", "img_prefix": "",
                   "collection": "cx_search_t_1", "alias": "cx_search_t"}, f)
    with open(os.path.join(d, "vocab.json"), "w", encoding="utf-8") as f:
        json.dump({"v": "m122", "count": len(pts), "terms": sorted([[t, n] for t, n in df.items()])}, f)
    sq._cache.clear()
    return t2.FakeQdrant(pts)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# build_filter
# --------------------------------------------------------------------------- #
def test_or_mod_legalabb_a_tokenek_fele():
    g = [["western"], ["digital"], ["purple"], ["sc"], ["qd101"], ["256gb"]]
    assert sq.build_filter([], g, "or")["min_should"]["min_count"] == 3
    assert sq.build_filter([], g, "near")["min_should"]["min_count"] == 5
    g5 = g[:5]
    assert sq.build_filter([], g5, "or")["min_should"]["min_count"] == 2
    g3 = [["epson"], ["zzzz"], ["yyyy"]]
    assert sq.build_filter([], g3, "or")["min_should"]["min_count"] == 1   # 3 tokennel valtozatlan


def test_rovid_token_laza_modban_egyedul_nem_eleg():
    f = sq.build_filter([], [["sc"], ["scanner"]], "near")
    nested = [c for c in f["must"] if "min_should" in c]
    assert len(nested) == 1 and nested[0]["min_should"]["min_count"] == 1
    assert nested[0]["min_should"]["conditions"] == [{"key": "ft", "match": {"text": "scanner"}}]
    # nincs rovid token -> nincs plusz feltetel (a regi szuro-alak)
    f2 = sq.build_filter([], [["epson"], ["zzzz"]], "near")
    assert f2["must"] == []
    # csak rovid tokenek -> nincs mibol 'eros' feltetelt csinalni, marad a regi
    f3 = sq.build_filter([], [["hp"], ["sc"]], "near")
    assert f3["must"] == []
    # AND-modban a rovid token is kotelezo, plusz feltetel nelkul
    f4 = sq.build_filter([], [["hp"], ["toner"]], "and")
    assert len(f4["must"]) == 2 and "min_should" not in f4


def test_tipusszam_felismeres():
    assert sq.is_code("qd101") and sq.is_code("m404dn") and sq.is_code("dcpl3520cdw")
    assert not sq.is_code("256gb") and not sq.is_code("5400rpm") and not sq.is_code("4tb")
    assert not sq.is_code("purple") and not sq.is_code("12345") and not sq.is_code("a4")


# --------------------------------------------------------------------------- #
# search() vegig
# --------------------------------------------------------------------------- #
def test_panasz_eset_szuk_hasonlo_lista_es_hianyzo_tipusszam():
    with tempfile.TemporaryDirectory() as tmp:
        fq = _build(tmp)
        out = _run(sq.search(fq, {}, "t", "Western Digital Purple SC QD101 256GB", root=tmp))
        assert out["mode"] == "or"
        assert [h["i"] for h in out["hits"]] == ["1"] and out["total"] == 1   # csak a 3 szavas WD Purple
        assert out["missing"] == ["qd101"]


def test_rovid_token_egyedul_nem_hoz_talalatot():
    with tempfile.TemporaryDirectory() as tmp:
        fq = _build(tmp)
        out = _run(sq.search(fq, {}, "t", "sc qd101", root=tmp))
        assert out["total"] == 0 and out["hits"] == []                      # regen: a scanner jott
        assert out["missing"] == ["qd101"]


def test_letezo_tipusszam_nem_hianyzo_es_a_pontos_kereses_valtozatlan():
    with tempfile.TemporaryDirectory() as tmp:
        fq = _build(tmp)
        out = _run(sq.search(fq, {}, "t", "m404", root=tmp))
        assert out["total"] == 1 and out["hits"][0]["i"] == "6"
        assert "missing" not in out
        out2 = _run(sq.search(fq, {}, "t", "western digital", root=tmp))
        assert out2["mode"] == "and" and out2["total"] == 2 and "missing" not in out2


# --------------------------------------------------------------------------- #
# indexcore: HTML-entitasok
# --------------------------------------------------------------------------- #
def test_indexcore_html_entitas_dekodolas():
    row = ic.compact({"id": 1, "sku": "X1", "name": " WESTERN DIGITAL 3.5&quot; HDD ",
                      "brand": "Black &amp; Decker", "category": "Merevlemez &gt; 3.5&quot;",
                      "price_gross": 100, "available": True, "url": "", "image_url": ""}, "", "")
    assert row["n"] == 'WESTERN DIGITAL 3.5" HDD'
    assert row["b"] == "Black & Decker"
    assert row["c"] == 'Merevlemez > 3.5"'
    row2 = ic.compact({"id": 2, "name": None, "brand": "Tom & Jerry"}, "", "")
    assert row2["n"] == "" and row2["b"] == "Tom & Jerry"

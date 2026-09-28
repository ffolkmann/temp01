"""m109: elgepeles-tures a Smart Search szerver-kereseben (+ a lexpool atveszi a javitast).

Fajl-betoltos import (a suite mas tesztjei fake app.services-t hagyhatnak a sys.modules-ben).
"""
import asyncio
import importlib.util
import pathlib

_root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, _root / fname)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


sq = _load("searchq_m109", "searchq.py")
lp = _load("lexpool_m109", "lexpool.py")

VOCAB = sorted([
    ("lezernyomtato", 172), ("nyomtato", 724), ("fejhallgato", 432), ("instinct", 11),
    ("instant", 59), ("redmi", 145), ("xiaomi", 471), ("kerekek", 40), ("akku", 29),
    ("ritkaszo", 3), ("canon", 1396), ("canyon", 18),
])


def _tix():
    terms = [t for t, _ in VOCAB]
    dfs = [d for _, d in VOCAB]
    return sq.TenantIndex("t", {"alias": "cx_search_t"}, terms, dfs, 0)


def test_dl_tavolsag():
    assert sq._dl("fejhalgato", "fejhallgato", 2) == 1
    assert sq._dl("xioami", "xiaomi", 1) == 1          # szomszedos csere = 1
    assert sq._dl("abc", "xyz", 1) == 2               # korai kilepes: maxd+1
    assert sq._dl("nyomtato", "nyomtato", 1) == 0


def test_javitas_csak_0_prefix_talalatos_tokenre():
    tix = _tix()
    assert tix.correct("fejhalgato") == ["fejhallgato"]
    assert tix.correct("lezernyomtto") == ["lezernyomtato"]
    assert tix.correct("xioami") == ["xiaomi"]
    # van prefix-talalata -> nincs javitas (a kereso ma is talal)
    assert tix.correct("nyomt") == []
    assert tix.correct("lezer") == []


def test_javitas_korlatok():
    tix = _tix()
    assert tix.correct("redmk") == ["redmi"]           # 5 betu, d1
    assert tix.correct("rdmi") == []                   # 4 betu: tul rovid
    assert tix.correct("keresek") == []                # STOP-szo (teslashop FP: -> kerekek)
    assert tix.correct("ritkaszi") == []               # a cel df < FUZZY_MIN_DF
    assert tix.correct("instonct") == ["instinct"]     # 8 betu, d1 a legkozelebbi (instant d2)
    assert tix.correct("abc123x") == []                # nem csupa betu (cikkszam)
    assert tix.correct("zzzzzzz") == []                # nincs kozeli szo
    # a legkozelebbi tavolsagon tobb jelolt: df szerint, max 2
    assert tix.correct("cannon") == ["canon", "canyon"]


def test_apply_fuzzy_csak_egyalternativas_csoport():
    tix = _tix()
    groups = [["fejhalgato"], ["lezer", "laser"], ["nyomtato"]]
    out, fz = sq.apply_fuzzy(groups, tix)
    assert out == [["fejhalgato", "fejhallgato"], ["lezer", "laser"], ["nyomtato"]]
    assert fz == {"fejhalgato": ["fejhallgato"]}
    # fake tenant-index correct() nelkul (regi tesztek) -> valtozatlan
    out2, fz2 = sq.apply_fuzzy(groups, object())
    assert out2 == groups and fz2 == {}


def test_javitas_cache():
    tix = _tix()
    tix.correct("fejhalgato")
    assert "fejhalgato" in tix._fzc
    tix.terms.append("zzz")  # a cache-bol jon, nem szamol ujra
    assert tix.correct("fejhalgato") == ["fejhallgato"]


def test_lexpool_atveszi_a_javitast():
    cfg = {"enabled": True, "server": {"enabled": True}}
    dense = [{"id": 1, "score": 0.5, "payload": {"type": "product", "sku": "m1",
                                                  "name": "Logitech R400 Laser Pointer"}}]
    rows = [
        {"k": "a", "n": "BROTHER Lezernyomtato HL-1110E", "p": 35790},
        {"k": "b", "n": "XEROX FF lezernyomtato B230", "p": 52990},
        {"k": "c", "n": "Kyocera ECOSYS PA4000cx szines lezernyomtato", "p": 219690},
    ]

    async def search_fn(q, sort="rel", offset=0):
        return {"mode": "and", "total": 3, "hits": rows if offset == 0 else [],
                "fuzzy": {"lezernyomtto": ["lezernyomtato"]}}

    async def fetch_fn(cid, skus):
        return {s: {"id": s, "payload": {"type": "product", "sku": s, "name": s}} for s in skus}

    out = asyncio.run(lp.superlative_lex_pool("copygo", "lézernyomttó", dense, "asc",
                                              cfg=cfg, search_fn=search_fn, fetch_fn=fetch_fn))
    assert out and [h["payload"]["sku"] for h in out] == ["a", "b", "c"]

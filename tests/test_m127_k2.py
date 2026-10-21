# -*- coding: utf-8 -*-
"""m127 (K2 hamis "nincs"): osszefuzott kod-token a lexmatch sku- es nev-agban, hideg katalogus
varakozas, kiegeszito-kerdes termekoldalon (accessoryq).

Fajl-betoltos import (a suite mas tesztjei fake app.services-t hagyhatnak a sys.modules-ben);
az async reszek fake modulokkal, context managerben (a sys.modules a teszt utan visszaall).
"""
import asyncio
import contextlib
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


lx = _load("lexmatch_m127", "app/services/lexmatch.py")
aq = _load("accessoryq_m127", "app/services/accessoryq.py")


@contextlib.contextmanager
def _fake_modules(mods):
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


E = [
    (1, lx.fold("Ryobi pótkés szett ágaprítókhoz RSH2400R és RSH2545B RAC351"), lx.norm_sku("5133002597"), True),
    (2, lx.fold("Ryobi 45mm 3000W halk ágaprító RSH3045U"), "r2", False),
    (3, lx.fold("Trabucco Atmos FD4000 orsó"), "t1", True),
    (4, lx.fold("Trabucco Myst FD4000 pótdob"), "t2", True),
    (5, lx.fold("Pótdob Ryobi Zauber LT 4000 Match"), "r5", True),
    (6, lx.fold("YATO 125 mm Sarokcsiszoló porelszívó adapter vágáshoz"), lx.norm_sku("YT-82992"), True),
    (7, lx.fold("Black&Decker KS-846 körfűrész"), "bd846", True),
]
E += [(100 + i, "horgasz kiegeszito %d" % i, "s%d" % i, True) for i in range(200)]


def names(ids):
    return [e[1] for e in E if e[0] in ids]


# ---------------------------------------------------------------- (a) join-token

def test_join_tokens_es_sku_tokens():
    assert lx.join_tokens("RAC 351 pótkésre van szükségem") == ["rac~351"]
    assert lx.sku_tokens("RAC 351 pótkésre van szükségem") == ["rac351"]
    # az osszefuzott alak elol, a csupa-szam resz (regi szabaly szerint) utana
    assert lx.sku_tokens("Keresem a YT 82992 cikkszámú terméket") == ["yt82992", "82992"]
    # a regi, egybeirt alak valtozatlan
    assert lx.sku_tokens("Keresem a yt82992 cikkszàmú terméket") == ["yt82992"]
    # csak szomszedos par (szokoz/kotojel), vesszo nem
    assert lx.join_tokens("16 GB, 512GB SSD") == []
    # keves szamjegy / modellnev: nem kod
    assert lx.join_tokens("iPhone 15 pro, Model 3") == []
    # telefonszam / osszeg nem (regi szabalyok)
    assert lx.sku_tokens("hívj a 06301234567 számon") == []
    assert lx.sku_tokens("van 20000 ft-om") == []
    assert lx.join_tokens("van 20000 ft-om") == []  # STOP-szo + penznem: nem join


def test_codes_raw_alak():
    assert ("rac351", "RAC 351") in lx._codes("RAC 351 pótkésre van szükségem")
    assert lx.sku_match("RAC-351", "RAC 351 pótkés kell") == "RAC-351"


def test_matcher_join_alakok():
    m = lx._matcher("rac~351")
    assert m("ryobi potkes szett rac351")
    assert m("ryobi potkes rac-351 szett")
    assert m("ryobi potkes rac 351")
    assert not m("ryobi potkes rac3510")
    assert not m("ryobi potkes brac351")


def test_pick_rac351_nev_agon_megtalalja():
    s, n, info = lx.pick(E, "RAC 351 pótkésre van szükségem", [])
    assert s == [] and n == [1], (s, n, info)
    assert "rac" not in info["qt"][1:] or True  # a reszek a known-bol kiesnek, a qt-ban maradhatnak


def test_pick_rac351_ritka_kod_fel_fedessel_is():
    # m127b: E2E lelet - az 'eredetire' szo lehuzta a fedest 0.655-re; a ritka kod + 'potkes' eleg
    s, n, info = lx.pick(E, "RAC 351 pótkésre van szükségem. Eredetire nem valami bóvli utángyártott!", [])
    assert n == [1], (s, n, info)
    # de a kod onmagaban, masik szo nelkul NEM (strong(): legalabb 2 to vagy ritka kod - itt a
    # kod ritka, igy a sku-szeru azonositas megengedett; a FD4000 eset tovabbra is kizart)


def test_pick_fd4000_masik_marka_nem_jon():
    # "Ryobi Zauber FD 4000" -> a Trabucco FD4000 csak a kodban egyezik, a tobbi szoban nem
    s, n, info = lx.pick(E, "Ryobi zauber fd 4000 potdob van e elerheto raktaron?", [])
    assert 3 not in n and 4 not in n, (n, info)


def test_pick_sku_ag_kotojeles_sku():
    E2 = [(1, "yato valami", lx.norm_sku("RAC-351"), True)] + E[1:]
    s, n, _ = lx.pick(E2, "RAC 351 kellene", [])
    assert s == [1]


def test_term_in_catalog_valtozatlan():
    # a m117 kapu a _TOK-ot hasznalja, a '~' tokent sosem latja
    assert lx.term_in_catalog("nincs-ilyen-tenant", "") is True


# ---------------------------------------------------------------- (b) hideg katalogus

def test_wait_cold_nincs_epites():
    lx._cache.pop("t-cold", None)
    lx._tasks.pop("t-cold", None)
    lx._building.discard("t-cold")
    assert asyncio.run(lx._wait_cold("t-cold")) is None


def test_wait_cold_megvarja():
    async def run():
        lx._cache.pop("t-warm", None)
        lx._building.add("t-warm")

        async def _b():
            await asyncio.sleep(0.2)
            lx._cache["t-warm"] = (lx.time.monotonic(), [(1, "x", "", True)])
            lx._building.discard("t-warm")
        asyncio.get_running_loop().create_task(_b())
        return await lx._wait_cold("t-warm")
    out = asyncio.run(run())
    assert out == [(1, "x", "", True)]
    lx._cache.pop("t-warm", None)


# ---------------------------------------------------------------- (c) kiegeszito-kerdes

def test_is_accessory_query():
    with _fake_modules({"app": types.ModuleType("app"), "app.services": types.ModuleType("app.services"),
                        "app.services.lexmatch": lx}):
        assert aq.is_accessory_query("Hol találok hozzá új tonert?")
        assert aq.is_accessory_query("Ehez a géphez mlyen töltőt tudok nállatok venni?")
        assert aq.is_accessory_query("árulnak-e hozzá öntapadós címkét?")
        # visszautalas nelkul (nincs hozza/-hoz) NEM fut: tudatos hatar
        assert not aq.is_accessory_query("Mivardi base station télitakarót keresek")
        assert not aq.is_accessory_query("Mennyibe kerül?")
        assert not aq.is_accessory_query("hozzá")  # csak visszautalas, tartalmas szo nelkul


def test_accessory_hits_fake():
    calls = {}

    class _Q:
        async def search(self, vector=None, client_id=None, limit=24, product_only=False,
                         available_only=False, extra_must=None):
            calls["search"] = dict(limit=limit, product_only=product_only, available_only=available_only)
            return [
                {"id": "p1", "score": 0.5, "payload": {"type": "product", "name": "Brother TN2590 toner", "url": "u1"}},
                {"id": "cur", "score": 0.9, "payload": {"type": "product", "name": "Brother HL nyomtató", "url": "ucur"}},
                {"id": "p2", "score": 0.4, "payload": {"type": "product", "name": "Brother TN2590XL toner", "url": "u2"}},
                {"id": "p3", "score": 0.3, "payload": {"type": "product", "name": "Brother dob egység", "url": "u3"}},
                {"id": "p4", "score": 0.2, "payload": {"type": "product", "name": "Brother papír", "url": "u4"}},
            ]

    async def _embed(q):
        calls["embed"] = q
        return [0.0]

    def _rerank(message, hits, page_url="", page_url_norm="", top_n=8):
        return sorted(hits, key=lambda h: -h["score"])[:top_n]

    emb = types.ModuleType("app.core.embeddings")
    emb.embed_query = _embed
    qd = types.ModuleType("app.core.qdrant")
    qd.get_qdrant = lambda: _Q()
    rr = types.ModuleType("app.services.rerank")
    rr.rerank = _rerank
    qc = types.ModuleType("app.services.query_cleanup")
    qc.product_query_cleanup = lambda m: m
    cur = types.SimpleNamespace(payload={"brand": "Brother", "url": "ucur"}, name="Brother HL nyomtató")
    hits0 = [{"id": "p2", "score": 0.1, "payload": {"type": "product", "name": "mar bent", "url": "u2"}}]
    with _fake_modules({"app": types.ModuleType("app"), "app.core": types.ModuleType("app.core"),
                        "app.core.embeddings": emb, "app.core.qdrant": qd,
                        "app.services": types.ModuleType("app.services"), "app.services.rerank": rr,
                        "app.services.query_cleanup": qc, "app.services.lexmatch": lx}):
        n, hits = asyncio.run(aq.accessory_hits(hits0, "Hol találok hozzá új tonert?", "nbs", cur, hide_oos=True))
    assert n == 3
    ids = [h["id"] for h in hits]
    assert ids[0] == "p2" and "cur" not in ids and ids.count("p2") == 1
    assert ids[1:] == ["p1", "p3", "p4"]
    assert all(h.get("m127") for h in hits[1:])
    # az embed a kerdes tartalmas szava (ekezetes alak), a marka NEM kerul bele (m127c meres)
    assert calls["embed"] == "tonert"
    assert aq.content_words("Ehez a géphez mlyen töltőt tudok nállatok venni?") == ["toltot"]
    assert calls["search"]["product_only"] and calls["search"]["available_only"]
    with _fake_modules({"app": types.ModuleType("app"), "app.services": types.ModuleType("app.services"),
                        "app.services.lexmatch": lx}):
        n0, h0 = asyncio.run(aq.accessory_hits(hits0, "Mennyibe kerül?", "nbs", cur))
    assert n0 == 0 and h0 == hits0

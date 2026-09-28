"""m108: lexikai jelolt-pool az ar-szuperlativusz aghoz - tiszta fuggvenyek + fake kereso.

Fajl-betoltos import (a suite mas tesztjei fake app.services-t hagyhatnak a sys.modules-ben).
"""
import asyncio
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "lexpool.py"
_spec = importlib.util.spec_from_file_location("lexpool_m108", _p)
lp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lp)

CFG = {"enabled": True, "server": {"enabled": True}}
G_LASER = [["lezer", "laser"], ["nyomtato", "printer"]]


def _dense(names):
    return [{"id": i, "score": 0.5, "payload": {"type": "product", "sku": "d%d" % i, "name": n}}
            for i, n in enumerate(names)]


MICE = _dense([
    "LOGITECH Kiegeszito - Presenter R400 Laser Pointer, Fekete Logitech",
    "LOGITECH Billentyuzet + eger - MK120 Vezetekes Combo USB, HUN",
    "LOGITECH Eger - G203 Lightsync RGB Vezetekes Gaming, Feher",
    "2D MEGA PIXEL FIX MOUNT READER W/ 50 CM DIRECT USB CABLE. LASER",
])


def _row(k, n, p, c="", a=True):
    return {"k": k, "n": n, "p": p, "c": c, "a": 1 if a else 0}


ROWS = [
    _row("pap1", "A/4 HP Color Choise lézernyomtató papír 200g.", 3390, "Papír"),
    _row("ton1", "CANON, C-EXV49M Lézertoner IR C250 nyomtatókhoz magenta", 31590, "Toner"),
    _row("hl1110", "BROTHER Lézernyomtató HL-1110E, A4, mono", 35790, "Lézernyomtató"),
    _row("m110w", "HP LaserJet M110w mono lézer egyfunkciós nyomtató", 41790, "Nyomtató"),
    _row("b415", "Xerox VersaLink B415DN MFP", 237590, "Lézer nyomtató"),
    _row("tel1", "Panasonic kx-tgb610hgb", 10190, "Telefon"),
    _row("m209", "HP LaserJet Pro M209d mono lézer egyfunkciós nyomtató", 42790, "Nyomtató"),
    _row("free", "HP LaserJet ingyenes nyomtató", 0, "Nyomtató"),
]


def _search_fn(rows, mode="and"):
    calls = []

    async def fn(q, sort="rel", offset=0):
        calls.append((q, sort, offset))
        hits = rows if offset == 0 else []
        if sort == "pa":
            hits = sorted(hits, key=lambda r: r["p"])
        return {"mode": mode, "total": len(rows), "hits": hits}
    return fn, calls


async def _fetch(cid, skus):
    return {s: {"id": "pt-" + s, "payload": {"type": "product", "sku": s, "name": s,
                                              "price": "1", "available": True}} for s in skus}


def run(coro):
    return asyncio.run(coro)


def test_covers_osszetett_szo_mindket_iranyban():
    assert lp.covers("BROTHER Lézernyomtató HL-1110E", G_LASER)
    assert lp.covers("HP LaserJet M110w mono lézer egyfunkciós nyomtató", G_LASER)
    assert not lp.covers("Logitech R400 Laser Pointer", G_LASER)
    assert not lp.covers("barmi", [])


def test_covers_osszetett_tema_ket_darabban():
    g = [["lezernyomtato"]]
    assert lp.covers("HP LaserJet M110w mono lézer egyfunkciós nyomtató", g)
    assert lp.covers("BROTHER Lézernyomtató HL-1110E", g)
    assert not lp.covers("Logitech R400 Laser Pointer", g)
    # rovid tema-szo nem bomlik (okosora: 7 betu) -> 'okos' + 'ora' nem eleg
    assert not lp.covers("TP-Link okoskonnektor, oraval", [["okosora"]])


def test_topic_groups_szinonimaval():
    syn = {"lezer": ["lezer", "laser"], "laser": ["lezer", "laser"]}
    assert lp.topic_groups("lézer nyomtató", syn, {}) == [["lezer", "laser"], ["nyomtato"]]
    assert lp.topic_groups("lézernyomtató") == [["lezernyomtato"]]


def test_kiegeszito_osszetett_szoban_is():
    assert lp.is_accessory("CANON C-EXV49M Lézertoner", "lézer nyomtató")
    assert lp.is_accessory("A/4 IQ Economy+ 80g. másolópapír", "fénymásoló")
    assert lp.is_accessory("Leitz Ergo monitorállvány", "monitor")
    assert not lp.is_accessory("HP LaserJet M110w mono lézer egyfunkciós nyomtató", "lézer nyomtató")
    # a tema maga kiegeszito -> nem szurjuk
    assert not lp.is_accessory("HP 305A fekete toner", "HP toner")
    # rovid szavak csak egesz szokent: tokeletes / tintasugaras nem kiegeszito
    assert not lp.is_accessory("Tökéletes tintasugaras nyomtató", "nyomtató")
    assert lp.is_accessory("Szilikon tok iPhone", "iphone")


def test_dense_cover_szamolas():
    assert lp.dense_cover(MICE, G_LASER) == 0
    good = _dense(["HP LaserJet M110w mono lézer nyomtató", "BROTHER Lézernyomtató HL-1110E"])
    assert lp.dense_cover(good + MICE, G_LASER) == 2


def test_pick_rows_fedes_kiegeszito_ar():
    kept = [r["k"] for r in lp.pick_rows(ROWS, "lézer nyomtató", G_LASER)]
    # b415: csak a KATEGORIA fedi -> kiesik (gyujto-kategoria elleni nev-kapu)
    assert kept == ["hl1110", "m110w", "m209"]


def test_query_variants_osszeirt_alak():
    assert lp.query_variants("lézer nyomtató") == ["lézer nyomtató", "lezernyomtato"]
    assert lp.query_variants("lézernyomtató") == ["lézernyomtató"]
    assert lp.query_variants("alfa beta gamma delta") == ["alfa beta gamma delta"]


def test_pool_eles_eset_lezer_nyomtato():
    fn, calls = _search_fn(ROWS)
    out = run(lp.superlative_lex_pool("copygo", "lézer nyomtató", MICE, "asc",
                                      cfg=CFG, search_fn=fn, fetch_fn=_fetch))
    assert out and [h["payload"]["sku"] for h in out] == ["hl1110", "m110w", "m209"]
    assert out[0]["score"] > out[-1]["score"]
    assert ("lézer nyomtató", "pa", 0) in calls  # az ar szerinti veg is lekerve
    assert ("lezernyomtato", "rel", 0) in calls  # az osszeirt alak is


def test_desc_ar_rendezest_ker():
    fn, calls = _search_fn(ROWS)
    run(lp.superlative_lex_pool("copygo", "lézernyomtató", MICE, "desc",
                                cfg=CFG, search_fn=fn, fetch_fn=_fetch))
    assert any(c[1] == "pd" for c in calls)


def test_jo_dense_pool_nem_valtozik():
    good = _dense(["HP LaserJet M110w mono lézer nyomtató", "BROTHER Lézernyomtató HL-1110E"])
    fn, calls = _search_fn(ROWS)
    assert run(lp.superlative_lex_pool("copygo", "lézer nyomtató", good, "asc",
                                       cfg=CFG, search_fn=fn, fetch_fn=_fetch)) is None
    assert calls == []


def test_nincs_kereso_profil():
    fn, calls = _search_fn(ROWS)
    for cfg in ({}, {"enabled": True}, {"enabled": True, "server": {"enabled": False}}):
        assert run(lp.superlative_lex_pool("x", "lézer nyomtató", MICE, "asc",
                                           cfg=cfg, search_fn=fn, fetch_fn=_fetch)) is None
    assert calls == []


def test_nem_and_mod_es_keves_talalat():
    fn, _ = _search_fn(ROWS, mode="near")
    assert run(lp.superlative_lex_pool("copygo", "lézer nyomtató", MICE, "asc",
                                       cfg=CFG, search_fn=fn, fetch_fn=_fetch)) is None
    fn, _ = _search_fn(ROWS[:4])  # papir + toner + 2 gep -> 2 < MIN_HITS
    assert run(lp.superlative_lex_pool("copygo", "lézer nyomtató", MICE, "asc",
                                       cfg=CFG, search_fn=fn, fetch_fn=_fetch)) is None


def test_chat_kollekcioban_hianyzo_cikkszam_kiesik():
    fn, _ = _search_fn(ROWS)

    async def fetch_part(cid, skus):
        full = await _fetch(cid, skus)
        return {k: v for k, v in full.items() if k in ("hl1110", "m110w")}
    assert run(lp.superlative_lex_pool("copygo", "lézer nyomtató", MICE, "asc",
                                       cfg=CFG, search_fn=fn, fetch_fn=fetch_part)) is None


def test_rovid_tema():
    fn, calls = _search_fn(ROWS)
    assert run(lp.superlative_lex_pool("copygo", "tv", MICE, "asc",
                                       cfg=CFG, search_fn=fn, fetch_fn=_fetch)) is None
    assert calls == []

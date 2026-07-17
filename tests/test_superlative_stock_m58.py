"""m58 - keszlet-szures az ar-szuperlativusz agban. PURE modul-teszt (app-import nelkul)."""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "superlative_m58", ROOT / "app" / "services" / "superlative.py"
)
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def _hit(name, price="", stock=None, available=None, score=0.5):
    p = {"price": price, "sku": "SKU-" + name, "name": name, "type": "product"}
    if stock is not None:
        p["stock"] = stock
    if available is not None:
        p["available"] = available
    return {"id": name, "score": score, "payload": p}


def test_detect_stock_filter():
    assert S.detect_stock_filter(u"Melyik a legolcs\u00f3bb rakt\u00e1ron l\u00e9v\u0151 notebook?")
    assert S.detect_stock_filter(u"legolcsobb keszleten levo gep")
    assert S.detect_stock_filter(u"mi a legjobb ar, ami azonnal atveheto?")
    assert S.detect_stock_filter(u"rakt\u00e1rr\u00f3l azonnal vihet\u0151?")
    assert not S.detect_stock_filter(u"Melyik a legolcs\u00f3bb notebook?")
    assert not S.detect_stock_filter(u"mikor lesz akci\u00f3?")


def test_topic_strips_stock_words():
    t = S.topic_of(u"Melyik a legolcs\u00f3bb rakt\u00e1ron l\u00e9v\u0151 notebook?")
    assert t == "notebook"
    t2 = S.topic_of(u"mennyi a legolcs\u00f3bb azonnal \u00e1tvehet\u0151 laptop?")
    assert t2 == "laptop"


def test_availability():
    assert S.availability(_hit("a", available=True)) is True
    assert S.availability(_hit("b", available=False)) is False
    assert S.availability(_hit("c", stock="3")) is True
    assert S.availability(_hit("d", stock="0")) is False
    assert S.availability(_hit("e")) is None
    assert S.availability(_hit("f", stock="sok")) is None


def test_stock_filtered_only_available():
    hits = [
        _hit("noteA", price="200000", available=True, score=0.9),
        _hit("noteB", price="150000", available=False, score=0.8),
        _hit("noteC", price="300000", available=True, score=0.7),
        _hit("noteD", price="120000", available=False, score=0.6),
        _hit("kabel", price="990", available=True, score=0.3),
        _hit("noteE", price="450000", available=True, score=0.5),
    ]
    out, mode = S.price_context_stock(hits, "asc", 8, True)
    assert mode == S.STOCK_FILTERED
    assert out, "nem lehet ures"
    for h in out:
        assert S.availability(h) is True
    # m61: az ar-padlo a 990 Ft-os kabelt kiszuri -> a legolcsobb VALODI gep a horgony
    assert out[0]["id"] == "noteA"
    ids = {h["id"] for h in out}
    assert "kabel" not in ids
    assert "noteB" not in ids and "noteD" not in ids


def test_stock_filtered_relaxed_few():
    hits = [
        _hit("noteA", price="200000", available=True, score=0.9),
        _hit("noteB", price="150000", available=False, score=0.8),
        _hit("noteC", price="300000", available=True, score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 8, True)
    assert mode == S.STOCK_FILTERED
    assert [h["id"] for h in out] == ["noteA", "noteC"]


def test_stock_none_available():
    hits = [
        _hit("noteA", price="200000", available=False, score=0.9),
        _hit("noteB", price="150000", available=False, score=0.8),
        _hit("noteC", price="300000", available=False, score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 8, True)
    assert mode == S.STOCK_NONE
    assert out  # a temara illeszkedo kontextus tovabbra is megy a modellnek


def test_stock_unknown():
    hits = [
        _hit("tA", price="200000", score=0.9),
        _hit("tB", price="150000", score=0.8),
        _hit("tC", price="300000", score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 8, True)
    assert mode == S.STOCK_UNKNOWN
    assert out


def test_not_stock_only_passthrough():
    hits = [
        _hit("tA", price="200000", score=0.9),
        _hit("tB", price="150000", score=0.8),
        _hit("tC", price="300000", score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 8, False)
    assert mode == ""
    assert out


def test_stock_notes_keys():
    assert set(S.STOCK_NOTES) == {S.STOCK_FILTERED, S.STOCK_NONE, S.STOCK_UNKNOWN, S.STOCK_HINT}
    for v in S.STOCK_NOTES.values():
        assert len(v) > 40


def test_stock_hint_plain_superlative():
    hits = [
        _hit("olcsoA", price="85000", available=False, score=0.9),
        _hit("olcsoB", price="99000", available=False, score=0.85),
        _hit("olcsoC", price="110000", available=False, score=0.8),
        _hit("dragaAvail", price="465000", available=True, score=0.7),
        _hit("kozepAvail", price="325000", available=True, score=0.4),
        _hit("legolcsobbAvail", price="300000", available=True, score=0.3),
    ]
    out, mode = S.price_context_stock(hits, "asc", 4, False)
    assert mode == S.STOCK_HINT
    ids = [h["id"] for h in out]
    assert ids[0] == "olcsoA"  # az ar-veg valtozatlanul az elso
    assert "legolcsobbAvail" in ids and "kozepAvail" in ids  # a 2 legolcsobb raktaros bekerult


def test_stock_hint_absent_without_stock_data():
    hits = [
        _hit("tA", price="200000", score=0.9),
        _hit("tB", price="150000", score=0.8),
        _hit("tC", price="300000", score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 8, False)
    assert mode == ""
    assert out


def test_stock_notes_has_hint():
    assert S.STOCK_HINT in S.STOCK_NOTES


def test_avail_pool_used_for_extras():
    hits = [
        _hit("olcsoNincs", price="85000", available=False, score=0.9),
        _hit("kozepNincs", price="120000", available=False, score=0.8),
        _hit("dragaVan", price="325000", available=True, score=0.7),
    ]
    pool = [
        _hit("legolcsobbVan", price="109000", available=True, score=0.6),
        _hit("masodikVan", price="119000", available=True, score=0.55),
        _hit("dragaVan", price="325000", available=True, score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 4, False, avail_pool=pool)
    assert mode == S.STOCK_HINT
    ids = [h["id"] for h in out]
    assert "legolcsobbVan" in ids and "masodikVan" in ids


def test_avail_pool_used_for_stock_only():
    hits = [
        _hit("olcsoNincs", price="85000", available=False, score=0.9),
        _hit("dragaVan", price="325000", available=True, score=0.7),
    ]
    pool = [
        _hit("legolcsobbVan", price="109000", available=True, score=0.6),
        _hit("dragaVan", price="325000", available=True, score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 8, True, avail_pool=pool)
    assert mode == S.STOCK_FILTERED
    assert out[0]["id"] == "legolcsobbVan"
    assert all(S.availability(h) is True for h in out)


def test_avail_pool_none_falls_back_to_hits():
    hits = [
        _hit("noteA", price="200000", available=True, score=0.9),
        _hit("noteB", price="150000", available=False, score=0.8),
        _hit("noteC", price="300000", available=True, score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 8, True, avail_pool=None)
    assert mode == S.STOCK_FILTERED
    assert [h["id"] for h in out] == ["noteA", "noteC"]


def test_price_floor_drops_accessories():
    pool = [
        _hit("taska1", price="4690", available=True, score=0.62),
        _hit("taska2", price="4890", available=True, score=0.61),
        _hit("gepDraga", price="465000", available=True, score=0.7),
        _hit("gepKozep", price="325000", available=True, score=0.68),
        _hit("gepOlcso", price="109900", available=True, score=0.6),
        _hit("gepMasik", price="119900", available=True, score=0.58),
        _hit("gepPlusz", price="399000", available=True, score=0.66),
    ]
    hits = [
        _hit("nincsRakt", price="85990", available=False, score=0.9),
        _hit("nincsRakt2", price="99000", available=False, score=0.85),
        _hit("gepDraga", price="465000", available=True, score=0.7),
    ]
    out, mode = S.price_context_stock(hits, "asc", 4, False, avail_pool=pool)
    assert mode == S.STOCK_HINT
    ids = [h["id"] for h in out]
    assert "gepOlcso" in ids  # a 109 900-as gep a jelolt
    assert "taska1" not in ids and "taska2" not in ids  # a taskak kiesnek a padlon

    out2, mode2 = S.price_context_stock(pool, "asc", 6, True, avail_pool=pool)
    assert mode2 == S.STOCK_FILTERED
    ids2 = [h["id"] for h in out2]
    assert ids2[0] == "gepOlcso"  # ar-horgony: a legolcsobb VALODI gep
    assert "taska1" not in ids2 and "taska2" not in ids2


def test_price_floor_failsafe_all_cheap():
    pool = [
        _hit("a", price="990", available=True, score=0.9),
        _hit("b", price="1290", available=True, score=0.8),
        _hit("c", price="1590", available=True, score=0.7),
    ]
    out, mode = S.price_context_stock(pool, "asc", 4, True, avail_pool=pool)
    assert mode == S.STOCK_FILTERED
    assert out and out[0]["id"] == "a"  # homogen olcso tema: a padlo nem vag ki semmit


def test_needs_available_boost():
    assert S.needs_available_boost([
        _hit("a", price="100", available=False),
        _hit("b", price="200", available=False),
    ]) is True
    assert S.needs_available_boost([
        _hit("a", price="100", available=False),
        _hit("b", price="200", available=True),
    ]) is False
    assert S.needs_available_boost([
        _hit("a", price="100"),
        _hit("b", price="200"),
    ]) is False
    assert S.needs_available_boost([]) is False


def test_merge_available_extras():
    hits = [_hit("a", price="100", available=False, score=0.9)]
    pool = [
        _hit("a", price="100", available=False, score=0.9),   # duplikatum
        _hit("x", price="300", available=True, score=0.8),
        _hit("y", price="400", available=False, score=0.7),   # nem raktaros -> kimarad
        _hit("z", price="500", available=True, score=0.6),
        _hit("w", price="600", available=True, score=0.5),
        _hit("v", price="700", available=True, score=0.4),    # k=3 folott -> kimarad
    ]
    out = S.merge_available_extras(hits, pool, 3)
    ids = [h["id"] for h in out]
    assert ids == ["a", "x", "z", "w"]

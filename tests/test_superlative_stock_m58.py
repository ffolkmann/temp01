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
    assert out[0]["id"] == "kabel"  # ar-horgony: a szurt halmaz legolcsobbja
    ids = {h["id"] for h in out}
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
    assert set(S.STOCK_NOTES) == {S.STOCK_FILTERED, S.STOCK_NONE, S.STOCK_UNKNOWN}
    for v in S.STOCK_NOTES.values():
        assert len(v) > 40

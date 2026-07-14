# m40: price_context -- ar-szuperlativusz hibrid kontextus (ar-veg + tema-relevancia).
# Eles minta: copygo "melyik a legolcsobb fotonyomtato?" -- a tiszta ar-asc top-8
# 8/8 utangyartott tintapatron volt, egyetlen fotonyomtato sem (2026-07-14).
# PURE modul, fajlbol toltve (a suite mas tesztjei fake app-csomagot ultetnek a
# sys.modules-ba, ezert a normal import a collection alatt nem mukodik).

import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "superlative.py"
_spec = importlib.util.spec_from_file_location("superlative_m40_under_test", _P)
_s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_s)
price_context = _s.price_context
sort_by_price = _s.sort_by_price


def _hit(hid, name, price, score):
    return {
        "id": hid,
        "score": score,
        "payload": {"type": "product", "name": name, "price": str(price), "sku": str(hid)},
    }


def _copygo_pool():
    return [
        _hit(1, "Utangyartott BROTHER LC3619XL Tintapatron Yellow", 80, 0.435),
        _hit(2, "EPSON T048140 BK ECOPIXEL", 610, 0.430),
        _hit(3, "Utangyartott BROTHER LC3619XL Tintapatron Cyan", 860, 0.429),
        _hit(4, "Utangyartott BROTHER LC3617 Tintapatron Black", 1090, 0.436),
        _hit(5, "MINOLTA B164 Toner TN116", 3390, 0.453),
        _hit(6, "Canon PFI-300 Photo Cyan tintapatron", 6190, 0.456),
        _hit(7, "Canon ZOEMINI 2 Fotonyomtato Rozsaarany", 46290, 0.500),
        _hit(8, "CANON Mobil fotonyomtato ZINK ZOEMINI 2", 50990, 0.496),
        _hit(9, "Canon Selphy CP1500 fotonyomtato fekete", 68990, 0.456),
        _hit(10, "Epson SCP700 A3 Fotonyomtato", 345090, 0.447),
        _hit(11, "Utangyartott BROTHER LC3617 Tintapatron Yellow", 1090, 0.443),
        _hit(12, "Utangyartott BROTHER LC3617 Tintapatron Magenta", 1090, 0.438),
        _hit(13, "MINOLTA B223 Toner TN217", 3490, 0.440),
        _hit(14, "Utangyartott EPSON T9441 Patron Black", 5190, 0.429),
    ]


def test_asc_ar_horgony_plusz_tema_legerosebbjei():
    out = price_context(_copygo_pool(), "asc", 8)
    ids = [h["id"] for h in out]
    assert len(out) == 8
    assert ids[0] == 1  # a legolcsobb elem az elen (ar-horgony)
    assert 7 in ids and 8 in ids  # ZOEMINI-k (score-top) bekerulnek
    assert 9 in ids  # Selphy fekete is


def test_regi_sort_by_price_hibaja_dokumentalva():
    out = sort_by_price(_copygo_pool(), "asc", 8)
    ids = [h["id"] for h in out]
    assert 7 not in ids and 8 not in ids and 9 not in ids  # csupa kellek volt


def test_desc_iranyban_a_draga_veg_a_horgony():
    out = price_context(_copygo_pool(), "desc", 8)
    assert out[0]["id"] == 10  # Epson SCP700 (345 090 Ft)


def test_top_n_es_dedup():
    out = price_context(_copygo_pool(), "asc", 4)
    ids = [h["id"] for h in out]
    assert len(ids) == 4 and len(set(ids)) == 4
    assert 7 in ids  # a tema-legerosebb kis top_n-nel is bekerul


def test_haromnal_kevesebb_arazott_termek_ures():
    hits = [_hit(1, "A", 100, 0.5), _hit(2, "B", 200, 0.4)]
    assert price_context(hits, "asc", 8) == []


def test_nem_termek_es_arazatlan_kiesik():
    hits = _copygo_pool() + [
        {"id": 99, "score": 0.9, "payload": {"type": "kb", "name": "ASZF reszlet", "price": ""}},
        _hit(98, "Arazatlan termek", "", 0.9),
    ]
    out = price_context(hits, "asc", 8)
    ids = [h["id"] for h in out]
    assert 98 not in ids and 99 not in ids

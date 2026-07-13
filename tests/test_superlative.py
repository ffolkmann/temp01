"""superlative (m38) — ar-szuperlativusz felismeres + determinisztikus ar-rendezes.

PURE modul, fajlbol toltve.
"""

import importlib.util
import pathlib

import pytest

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "superlative.py"
_spec = importlib.util.spec_from_file_location("superlative_under_test", _P)
_s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_s)


def _prod(price, name="X", sku="A1"):
    return {"payload": {"type": "product", "sku": sku, "name": name, "price": price}}


def _doc():
    return {"payload": {"type": None, "text": "ASZF...", "price": ""}}


# --- felismeres ----------------------------------------------------------------
@pytest.mark.parametrize(
    "q,want",
    [
        ("mennyi a legolcsóbb laptop nálatok?", "asc"),
        ("és a legolcsóbb laptop?", "asc"),
        ("melyik a legkedvezőbb árú gép?", "asc"),
        ("mi a legalacsonyabb árú monitor?", "asc"),
        ("melyik a LEGDRÁGÁBB gépetek?", "desc"),
        ("mi a legmagasabb árú konfiguráció?", "desc"),
        ("olcsó laptopot keresek", None),          # nem szuperlativusz
        ("és olcsóbban?", None),                    # kozepfok -> normal rangsor
        ("ez elég drága, van jobb?", None),
        ("", None),
    ],
)
def test_detect(q, want):
    assert _s.detect_price_superlative(q) == want


# --- ar-parse -------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,want",
    [
        ("246990", 246990.0),
        ("2 990", 2990.0),
        ("", None),
        ("0", None),
        ("n/a", None),
        (None, None),
    ],
)
def test_price_parse(raw, want):
    assert _s._price(_prod(raw)) == want


# --- rendezes ---------------------------------------------------------------------
def test_asc_a_legolcsobb_elol():
    hits = [_prod("199900"), _prod("144990"), _prod("269900"), _prod("162990")]
    out = _s.sort_by_price(hits, "asc", 8)
    prices = [(h["payload"]["price"]) for h in out]
    assert prices == ["144990", "162990", "199900", "269900"]


def test_desc_a_legdragabb_elol():
    hits = [_prod("199900"), _prod("144990"), _prod("269900")]
    out = _s.sort_by_price(hits, "desc", 8)
    assert out[0]["payload"]["price"] == "269900"


def test_doksi_es_arazatlan_kiesik():
    hits = [_doc(), _prod(""), _prod("100"), _prod("50"), _prod("70")]
    out = _s.sort_by_price(hits, "asc", 8)
    assert [h["payload"]["price"] for h in out] == ["50", "70", "100"]


def test_keves_arazott_termek_eseten_ures_a_fallbackhoz():
    """<3 arazott termek -> [] -> a hivo a normal rerank-agra esik vissza."""
    assert _s.sort_by_price([_prod("100"), _prod("200")], "asc", 8) == []
    assert _s.sort_by_price([_doc(), _doc()], "asc", 8) == []


def test_top_n_vagas():
    hits = [_prod(str(i * 10 + 10)) for i in range(12)]
    assert len(_s.sort_by_price(hits, "asc", 8)) == 8


# --- tema-kinyeres (m39: kor-fuggetlen embed) -----------------------------------
@pytest.mark.parametrize(
    "q,want",
    [
        ("mennyi a legolcsóbb laptop nálatok?", "laptop"),
        ("és a legolcsóbb laptop?", "laptop"),
        ("melyik a legdrágább gépetek?", "gépetek"),
        ("legkedvezőbb árú gaming monitor", "gaming monitor"),
        ("és a legolcsóbb?", ""),          # nincs tema -> a hivo normal utra esik
    ],
)
def test_topic_of(q, want):
    assert _s.topic_of(q) == want


def test_ket_kor_ugyanazt_a_temat_adja():
    t1 = _s.topic_of("mennyi a legolcsóbb laptop nálatok?")
    t2 = _s.topic_of("és a legolcsóbb laptop?")
    assert t1 == t2 == "laptop"

"""policy_filter (m34) — a termék-zaj kiszűrése policy-témájú kérdésnél. PURE, fájlból töltve."""

import importlib.util
import pathlib

import pytest

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "policy_filter.py"
_spec = importlib.util.spec_from_file_location("policy_filter_under_test", _P)
_pf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pf)


def _prod(name="Dell 3 ev garancia", sku="ABC123"):
    return {"payload": {"type": "product", "sku": sku, "name": name}}


def _doc(text="A garancia idotartama..."):
    return {"payload": {"type": None, "text": text, "filename": "aszf.docx"}}


# --- policy-felismeres -------------------------------------------------------
@pytest.mark.parametrize(
    "q,want",
    [
        ("milyen garancia van a gépeken", True),
        ("hány napig van elállási jog", True),
        ("mennyi a szállítási idő", True),
        ("hogyan tudok fizetni", True),
        ("van házhozszállítás?", True),
        ("visszaküldhetem a terméket?", True),
        ("ajánlj egy laptopot egyetemre", False),
        ("van RTX 4060-as géped?", False),
        ("mennyibe kerül a Lenovo ThinkPad", False),
        ("", False),
    ],
)
def test_is_policy_query(q, want):
    assert _pf.is_policy_query(q) is want


# --- a szures maga -----------------------------------------------------------
def test_policy_kerdesnel_a_termekek_kiesnek():
    hits = [_prod(), _prod(sku="X2"), _doc(), _doc(), _doc()]
    out = _pf.filter_for_policy("mennyi a garancia", hits)
    assert len(out) == 3
    assert all(not _pf._is_product(h) for h in out)


def test_nem_policy_kerdesnel_valtozatlan():
    hits = [_prod(), _doc()]
    assert _pf.filter_for_policy("ajánlj egy laptopot", hits) == hits


def test_egyetlen_doksi_is_eleg_a_szureshez():
    """min_docs=1: barmennyi hiteles KB-chunk jobb, mint a termeknevek zaja."""
    hits = [_prod(), _prod(sku="X2"), _doc()]
    out = _pf.filter_for_policy("mennyi a garancia", hits)
    assert out == [hits[2]]  # csak a doksi marad


def test_explicit_magasabb_kuszob_meg_mukodik():
    hits = [_prod(), _doc()]
    assert _pf.filter_for_policy("mennyi a garancia", hits, min_docs=2) == hits


def test_nulla_doksinal_megtartja_a_termekeket():
    """A tenant nem toltott policy-doksit -> a termekek maradnak (a factuality-blokk tilt)."""
    hits = [_prod(), _prod(sku="X2")]
    assert _pf.filter_for_policy("mennyi a garancia", hits) == hits


def test_is_product_sku_alapjan():
    assert _pf._is_product({"payload": {"sku": "ABC"}}) is True
    assert _pf._is_product({"payload": {"type": "product"}}) is True
    assert _pf._is_product({"payload": {"type": None, "sku": ""}}) is False
    assert _pf._is_product({"payload": {"sku": "  "}}) is False  # csak whitespace


# --- query-dusitas (m34) -----------------------------------------------------
def test_policy_embed_input_dusit_policy_kerdesnel():
    out = _pf.policy_embed_input("mennyi a garancia", "mennyi a garancia")
    assert out.startswith("mennyi a garancia")
    assert "jotallas" in out and "elallas" in out and "aszf" in out


def test_policy_embed_input_nem_dusit_termektanacsnal():
    ei = "gamer laptop RTX"
    assert _pf.policy_embed_input("ajánlj egy gamer laptopot", ei) == ei


def test_policy_embed_input_ures_embed_input_eseten_a_message_a_bazis():
    out = _pf.policy_embed_input("van házhozszállítás", "")
    assert out.startswith("van házhozszállítás")
    assert "szallitas" in out

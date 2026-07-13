"""query_cleanup (m36) — koszones/toltelek-zaj eltavolitasa a beagyazando querybol.

PURE modul, fajlbol toltve.
"""

import importlib.util
import pathlib

import pytest

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "query_cleanup.py"
_spec = importlib.util.spec_from_file_location("query_cleanup_under_test", _P)
_qc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_qc)

clean = _qc.product_query_cleanup


# --- az eles fishingoutlet-eset ------------------------------------------------
def test_a_shimano_eset():
    assert clean("Szia , shimano bojlit keresek") == "shimano bojlit"


@pytest.mark.parametrize(
    "src,want",
    [
        ("Jó napot kívánok! Daiwa orsót szeretnék", "Daiwa orsót"),
        ("hello, van feeder bototok?", "van feeder bototok?"),
        ("Sziasztok! Fox sátrat keresek 2 személyeset", "Fox sátrat 2 személyeset"),
        ("üdv, pergető botot keresnék", "pergető botot"),
    ],
)
def test_koszones_es_toltelek(src, want):
    assert clean(src) == want


# --- amihez NEM szabad nyulnia --------------------------------------------------
@pytest.mark.parametrize(
    "src",
    [
        "Milyen garancia van a gépeken?",       # policy-kerdes: valtozatlan
        "Mennyi a szállítási idő?",
        "gaming laptop 500 ezerig",
        "Van nálatok élő zsiráf?",
        "Ajánlj egy laptopot egyetemre.",
    ],
)
def test_nem_zajos_query_valtozatlan(src):
    assert clean(src) == src


def test_a_marka_es_a_ragozott_szo_megmarad():
    out = clean("Szia, SHIMANO bojlit keresek")
    assert "SHIMANO" in out and "bojlit" in out
    assert "Szia" not in out and "keresek" not in out


# --- vedokorlatok ----------------------------------------------------------------
def test_csak_koszones_eseten_az_eredeti_marad():
    assert clean("Szia!") == "Szia!"
    assert clean("Jó napot!") == "Jó napot!"


def test_ures_es_none():
    assert clean("") == ""
    assert clean(None) == ""


def test_koszones_a_mondat_kozepen_nem_esik_ki():
    # a "szia" csak az ELEJEN koszones; kesobb tartalom lehet
    out = clean("póló szia felirattal")
    assert out == "póló szia felirattal"

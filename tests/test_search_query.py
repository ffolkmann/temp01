"""search_query — a bolti kereső query-kaszkádja (pure, app-függőség nélkül).

A modult FÁJLBÓL töltjük (importlib), mert a többi teszt `app.services` stubot rak a
sys.modules-ba `__path__=[]`-szal; ez a modul viszont semmit sem importál az appból.
"""

import importlib.util
import pathlib

import pytest

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "search_query.py"
_spec = importlib.util.spec_from_file_location("search_query_under_test", _P)
_sq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sq)

build_queries = _sq.build_queries
search_queries = _sq.search_queries
_stem = _sq._stem


# --- tárgyrag-vágás ----------------------------------------------------------
@pytest.mark.parametrize(
    "raw,want",
    [
        ("botot", "bot"),
        ("hálót", "háló"),
        ("horgokat", "horg"),
        ("szett", "szett"),   # dupla-t nem rag
        ("watt", "watt"),
        ("bot", "bot"),       # <=4 karakter erintetlen
    ],
)
def test_stem(raw, want):
    assert _stem(raw) == want


# --- query-kaszkad -----------------------------------------------------------
def test_build_queries_termeknev():
    assert build_queries("Lenovo ThinkPad E14") == ["lenovo thinkpad e14", "thinkpad"]


def test_build_queries_altalanos():
    assert build_queries("gamer laptop RTX") == ["gamer laptop rtx", "laptop"]


def test_build_queries_stopszo_szures():
    # stopszavak kiesnek; "botot" -> "bot" (tárgyrag), "pergető" változatlan (ő-re végződik)
    assert build_queries("szeretnék venni egy jó pergető botot") == [
        "pergető bot",
        "pergető botot",
        "pergető",
    ]


def test_build_queries_ures():
    assert build_queries("") == [""]


# --- platformfuggo szures (m29 fazis 2) --------------------------------------
def test_search_queries_webdoc_elhagyja_az_egyszavas_mentsvart():
    """A WebDoc kereső részstringre illeszt -> a 'laptop' notebooktáskákat hozna."""
    assert search_queries("webdoc", "gamer laptop RTX") == ["gamer laptop rtx"]
    assert search_queries("WebDoc", "Lenovo ThinkPad E14") == ["lenovo thinkpad e14"]


def test_search_queries_webdoc_tobb_tobbszavas_query_megmarad():
    """Mindkét többszavas query kimegy; csak az egyszavas mentsvár ("pergető") esik ki."""
    qs = search_queries("webdoc", "szeretnék venni egy jó pergető botot")
    assert qs == ["pergető bot", "pergető botot"]


def test_search_queries_webdoc_egyetlen_tartalomszo_megmarad():
    """Ha eleve csak egy tartalomszó van, az nem 'mentsvár' — kimegy."""
    assert search_queries("webdoc", "thinkpad") == ["thinkpad"]
    assert search_queries("webdoc", "") == [""]


@pytest.mark.parametrize("plat", ["shoprenter", "unas", "woocommerce", "sellvio", "", None])
def test_search_queries_mas_platformon_valtozatlan(plat):
    msg = "gamer laptop RTX"
    assert search_queries(plat, msg) == build_queries(msg)

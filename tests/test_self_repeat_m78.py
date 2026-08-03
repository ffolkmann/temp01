"""m78: is_self_repeat egyseg-tesztek (fajl-betoltes, app-import nelkul)."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "selfrepeat.py"
_spec = importlib.util.spec_from_file_location("selfrepeat_m78", _p)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)

LONG = "A legolcsobb uzleti notebook a HP 250R G10 304 990 Ft aron kaphato. " * 5


def test_identical_long_is_repeat():
    assert sr.is_self_repeat(LONG, [LONG])


def test_whitespace_nbsp_case_normalized():
    variant = LONG.replace(" ", "\u00a0").upper()
    assert sr.is_self_repeat(variant, [LONG])


def test_containment_is_repeat():
    assert sr.is_self_repeat("Elozmeny: " + LONG + " Udvozlettel.", [LONG])


def test_short_identical_not_repeat():
    assert not sr.is_self_repeat("Szia!", ["Szia!"])


def test_different_long_not_repeat():
    other = "A legolcsobb 17 colos laptop taska a HP Prelude 7 990 Ft-ert. " * 5
    assert not sr.is_self_repeat(other, [LONG])


def test_empty_history_not_repeat():
    assert not sr.is_self_repeat(LONG, [])


def test_price_tokens_hungarian_formats():
    s = "A gep **304 990 Ft**, a taska 7 990 Ft-ert, a masik 22\u00a0390 Ft."
    assert sr.price_tokens(s) == {"304990", "7990", "22390"}


def test_price_tokens_ignores_phone_and_specs():
    s = "Hivj: +36 70 587 8680, 16GB RAM, 512GB SSD, 17.3 colos."
    assert sr.price_tokens(s) == set()


def test_stale_price_echo_detected():
    old = "A legolcsobb a HP 250R G10, 304 990 Ft-ert kaphato. " * 3
    new = "Tovabbra is a HP 250R G10 a legolcsobb, 304 990 Ft. Mas szoveg."
    assert sr.has_stale_price(new, [old])


def test_no_stale_price_on_disjoint_prices():
    old = "A legolcsobb a Lenovo V15, 159 900 Ft. " * 3
    new = "A legolcsobb taska a HP Prelude, 7 990 Ft."
    assert not sr.has_stale_price(new, [old])

"""handoff_offer (m32) — a bot által felajánlott élő átadás elfogadása.

PURE modul, fájlból töltjük (a többi teszt `app.services` stubot rak a sys.modules-ba).

A LEGFONTOSABB teszt a round-trip: a promptba írt mondatot a felismerő regexnek
látnia kell. Ha valaki átfogalmazza a mondatot és elfelejti a regexet, az átadás
CSENDBEN elromlik — a látogató igent mond, és nem történik semmi.
"""

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "handoff_offer.py"
_spec = importlib.util.spec_from_file_location("handoff_offer_under_test", _P)
_ho = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ho)


def _bot(text):
    return SimpleNamespace(role="assistant", content=text)


def _user(text):
    return SimpleNamespace(role="user", content=text)


# --- ROUND-TRIP: amit a bottal mondatunk, azt fel is ismerjük -----------------
@pytest.mark.parametrize("informal", [True, False])
def test_a_promptba_irt_mondatot_felismeri_a_regex(informal):
    block = _ho.prompt_block(informal=informal)
    sentence = _ho.OFFER_SENTENCE_INFORMAL if informal else _ho.OFFER_SENTENCE_FORMAL
    assert sentence in block, "a blokk tartalmazza a pontos mondatot"
    assert _ho.OFFER_RE.search(_ho.fold(sentence)), "a regex felismeri a sajat mondatunkat"


def test_a_blokk_tiltja_az_email_kerest():
    assert "NE e-mail-cimet kerj" in _ho.prompt_block()
    assert "collect_lead legyen false" in _ho.prompt_block()


# --- felajanlas-felismeres ---------------------------------------------------
def test_bot_felajanlotta():
    h = [_user("segitseg"), _bot("Sajnos erre nincs adatom. Szeretnéd, hogy átadjam egy élő munkatársnak?")]
    assert _ho.bot_offered_handoff(h) is True


def test_csak_a_LEGUTOBBI_bot_uzenet_szamit():
    """Harom korrel korabbi felajanlasra adott 'igen' mar masra vonatkozik."""
    h = [
        _bot("Szeretnéd, hogy átadjam egy élő munkatársnak?"),
        _user("nem, koszi"),
        _bot("Rendben! Miben segithetek meg?"),
    ]
    assert _ho.bot_offered_handoff(h) is False


def test_ures_history():
    assert _ho.bot_offered_handoff(None) is False
    assert _ho.bot_offered_handoff([]) is False


def test_dict_alaku_history_is_mukodik():
    h = [{"role": "assistant", "content": "Szeretné, hogy átadjam egy élő munkatársnak?"}]
    assert _ho.bot_offered_handoff(h) is True


# --- rabolintas --------------------------------------------------------------
@pytest.mark.parametrize(
    "msg,want",
    [
        ("igen", True),
        ("Igen, kérem", True),
        ("  IGEN!", True),
        ("rendben", True),
        ("persze", True),
        ("ok", True),
        ("mehet", True),
        ("nem", False),
        ("nem szeretnék ügyintézőt", False),
        ("igenis nem", False),  # a \b megvedi: az "igen" utan szokoznek kell jonnie
        ("okos vagy", False),  # az 'ok' nem ehet bele a szoba
        ("", False),
    ],
)
def test_is_affirmative(msg, want):
    assert _ho.is_affirmative(msg) is want


# --- a ketto egyutt ----------------------------------------------------------
def test_accepted_offer_teljes_kor():
    h = [_bot("Szeretnéd, hogy átadjam egy élő munkatársnak?")]
    assert _ho.accepted_offer("igen", h) is True
    assert _ho.accepted_offer("nem", h) is False


def test_igen_felajanlas_nelkul_nem_atadas():
    """A 'igen' onmagaban SOHA ne kapcsoljon operatorra."""
    h = [_bot("A szállítás 2-3 nap. Segíthetek még?")]
    assert _ho.accepted_offer("igen", h) is False

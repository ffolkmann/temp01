"""operator_notify (m31) — per-tenant Telegram bot vs. központi bot.

A modul semmit nem importál az appból (csak httpx + re), így FÁJLBÓL tölthető,
stubok nélkül.

Kulcs-invariáns: érvényes saját token -> a Telegram Bot API-ra megy a kérés;
nincs vagy hibás alakú token -> a központi n8n-webhookra (ne tűnjön el némán az
értesítés). A token SOHA nem kerül logba.
"""

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "operator_notify.py"
_spec = importlib.util.spec_from_file_location("operator_notify_under_test", _P)
_on = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_on)

VALID = "8123456789:AAF_dummy-Token_0123456789abcdefghijk"


def _t(**kw):
    kw.setdefault("client_id", "notebookstore")
    kw.setdefault("bot_name", "NotebookStore asszisztens")
    return SimpleNamespace(**kw)


# --- chatId-parse ------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,want",
    [
        ("123", ["123"]),
        ("123,456", ["123", "456"]),
        ("123\n456; 789", ["123", "456", "789"]),
        ("123 123", ["123"]),  # duplikátum kiesik
        ("", []),
        (None, []),
    ],
)
def test_parse_chat_ids(raw, want):
    assert _on._parse_chat_ids(raw) == want


# --- token-validalas ---------------------------------------------------------
@pytest.mark.parametrize(
    "raw,valid",
    [
        (VALID, True),
        ("  " + VALID + "  ", True),      # trimmelunk
        ("8123456789:rovid", False),      # tul rovid titok
        ("nincs-ketospont", False),
        ("", False),
        (None, False),
        ("abc:AAF_dummy-Token_0123456789abcdefghijk", False),  # nem szam a bot_id
    ],
)
def test_bot_token(raw, valid):
    got = _on.bot_token(_t(operator_bot_token=raw))
    assert bool(got) is valid
    if valid:
        assert got == VALID


def test_bot_token_hianyzo_mezo():
    """Régi tenant-objektum (nincs is ilyen attribútuma) -> nincs saját bot."""
    assert _on.bot_token(_t()) == ""


# --- kuldesi URL -------------------------------------------------------------
def test_send_url_sajat_bot():
    assert _on.send_url(VALID) == f"https://api.telegram.org/bot{VALID}/sendMessage"


def test_send_url_kozponti_fallback():
    url = _on.send_url("")
    assert url.startswith("http://n8n-cxxz-n8n-1:5678/webhook/")
    assert "api.telegram.org" not in url


def test_hibas_token_a_kozponti_botra_esik_vissza():
    """Ne tűnjön el némán az értesítés, ha az ügyfél elgépeli a tokent."""
    tok = _on.bot_token(_t(operator_bot_token="8123456789:rovid"))
    assert tok == ""
    assert "api.telegram.org" not in _on.send_url(tok)


# --- uzenet-osszeallitas -----------------------------------------------------
def test_compose_eles():
    txt = _on._compose(_t(), "hol tart a rendelesem")
    assert txt.startswith("🔔 Új élő ügyintéző-kérés")
    assert "notebookstore (NotebookStore asszisztens)" in txt
    assert "operator.html" in txt


def test_compose_teszt_mas_fejlec():
    txt = _on._compose(_t(), "proba", test=True)
    assert txt.startswith("🧪 Teszt-üzenet")


def test_compose_hosszu_elonezet_vagasa():
    txt = _on._compose(_t(), "x" * 300)
    assert "…" in txt
    assert len(txt.split("Üzenet: „")[1].split("”")[0]) == 158  # 157 + ellipszis

import importlib.util
import logging
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "operator_notify.py"
_spec = importlib.util.spec_from_file_location("operator_notify_redact_test", _P)
_on = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_on)

TOKEN = "8123456789:AAF_dummy-Token_0123456789abcdefghijk"


def _record(msg, *args):
    return logging.LogRecord("httpx", logging.INFO, __file__, 1, msg, args, None)


def test_httpx_url_bol_kimaszkolja_a_tokent():
    """Az httpx a teljes URL-t logolja INFO-n — a token nem maradhat benne."""
    r = _record('HTTP Request: POST https://api.telegram.org/bot%s/sendMessage "200 OK"', TOKEN)
    assert _on._redactor.filter(r) is True
    out = r.getMessage()
    assert TOKEN not in out
    assert "/bot***/sendMessage" in out


def test_a_kozponti_webhook_url_erintetlen():
    r = _record("HTTP Request: POST http://n8n-cxxz-n8n-1:5678/webhook/cx-notify-b41e88c2f7a3")
    _on._redactor.filter(r)
    assert "cx-notify-b41e88c2f7a3" in r.getMessage()


def test_nem_torik_el_formazatlan_uzeneten():
    r = _record("sima uzenet %s", "x")
    assert _on._redactor.filter(r) is True
    assert r.getMessage() == "sima uzenet x"


def test_a_szuro_fel_van_teve_a_httpx_loggerre():
    assert any(isinstance(f, type(_on._redactor)) for f in logging.getLogger("httpx").filters)

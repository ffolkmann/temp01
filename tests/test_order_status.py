"""order_status m24/A+B — matched chat-válasz, státusznév-parse, 'ismeretlen' tiltás.

A modult FÁJLBÓL töltjük (importlib) az app-stubok miatt; a mailer/platform_api
függőségeket minimál stubbal regisztráljuk.
"""

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]

# fuggoseg-stubok (csak ami az importhoz kell)
for name in ("app", "app.core", "app.services", "app.models"):
    m = sys.modules.setdefault(name, types.ModuleType(name))
    m.__path__ = []
_mailer = types.ModuleType("app.core.mailer")
_mailer.schedule_email = lambda *a, **k: None
sys.modules["app.core.mailer"] = _mailer
_pa = types.ModuleType("app.services.platform_api")
for fn in ("norm_email", "sellvio_token", "shoprenter_resource_id", "shoprenter_shop",
           "shoprenter_token", "unas_login", "xml_first_text", "xml_root"):
    setattr(_pa, fn, lambda *a, **k: None)
_pa.UNAS_BASE = "https://api.unas.eu/shop"
sys.modules["app.services.platform_api"] = _pa

_p = ROOT / "app" / "services" / "order_status.py"
_spec = importlib.util.spec_from_file_location("order_status_under_test", _p)
_os = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_os)


def test_pick_status_name_shapes():
    assert _os._pick_status_name({"name": "Csomagolható"}) == "Csomagolható"
    assert _os._pick_status_name(
        {"orderStatusDescriptions": [{"name": "Teljesítve"}]}) == "Teljesítve"
    assert _os._pick_status_name(
        {"orderStatus": {"orderStatusDescriptions": {"orderStatusDescription": [
            {"language": {"href": "x"}, "name": "Utalásra vár"}]}}}) == "Utalásra vár"
    assert _os._pick_status_name({"orderStatusDescriptions": []}) == ""
    assert _os._pick_status_name({}) == ""


def test_matched_reply_with_status():
    r = _os._matched_reply("12345", "Csomagolható")
    assert "#12345" in r and "Csomagolható" in r and "e-mailben is" in r


def test_matched_reply_never_ismeretlen():
    r = _os._matched_reply("12345", "ismeretlen")
    assert "ismeretlen" not in r and "#12345" in r
    r2 = _os._matched_reply("12345", "")
    assert "ismeretlen" not in r2


def test_safe_status_guard():
    assert _os._safe_status({"href": "x"}, None, "Teljesítve") == "Teljesítve"
    assert _os._safe_status({"href": "x"}, None) == "ismeretlen"

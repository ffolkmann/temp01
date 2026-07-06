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


def test_pick_status_name_items_shape():
    # a masodik hop (orderStatusDescriptions lista) valasz-alakja items alatt
    assert _os._pick_status_name({"items": [{"name": "Csomagolható"}]}) == ""  # ez NEM a pick dolga
    # (a lista-agat a _sr_status_name kezeli; itt csak dokumentaljuk a hatarvonalat)


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


def test_format_wh_note():
    n = _os._format_wh_note([("saját raktár", "2 munkanap", 2), ("külső raktár", "4-5 munkanap", 1)])
    assert n == ("Raktár szerinti bontás — saját raktár: 2 tétel (szállítás: 2 munkanap); "
                 "külső raktár: 1 tétel (szállítás: 4-5 munkanap). "
                 "A csomag szállítási ideje a leghosszabb szállítású tétel szerint alakul."), n
    n1 = _os._format_wh_note([("saját raktár", "2 munkanap", 3)])
    assert n1.endswith("saját raktár: 3 tétel (szállítás: 2 munkanap).") and "leghosszabb" not in n1
    assert _os._format_wh_note([]) == ""


def test_matched_reply_with_note():
    r = _os._matched_reply("99", "Csomagolható", "Raktár szerinti bontás — saját raktár: 1 tétel.")
    assert r.endswith("Raktár szerinti bontás — saját raktár: 1 tétel.")

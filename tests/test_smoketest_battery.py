"""smoketest_battery (m35) — a go-live tesztsor tenant-tudatossaga + auto-ellenorzes.

PURE modul, fajlbol toltjuk (a tobbi teszt `app.services` stubot rak a sys.modules-ba).
"""

import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "smoketest_battery.py"
_spec = importlib.util.spec_from_file_location("smoketest_battery_under_test", _P)
_b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_b)


def _cfg(**kw):
    base = {"platform": "sellvio", "live_agent": False, "elallas": False,
            "search_fb": False, "_kb": 0}
    base.update(kw)
    return base


# --- tenant-tudatossag -------------------------------------------------------
def test_bolti_kereso_csak_ha_bekapcsolt():
    with_fb = _b.build_cases(_cfg(search_fb=True))
    without = _b.build_cases(_cfg(search_fb=False))
    assert any(c["kat"] == "Bolti kereso" for c in with_fb)
    assert not any(c["kat"] == "Bolti kereso" for c in without)
    assert len(with_fb) == len(without) + 1


def test_webdoc_urlap_elvarasa_iranyitoszam():
    cases = _b.build_cases(_cfg(platform="webdoc"))
    of = next(c for c in cases if c["check"] == "order_form")
    assert "iranyitoszam" in of["elvart"]


def test_nem_webdoc_urlap_elvarasa_email():
    cases = _b.build_cases(_cfg(platform="sellvio"))
    of = next(c for c in cases if c["check"] == "order_form")
    assert "e-mail" in of["elvart"]


def test_kb_nelkuli_tenant_figyelmeztetest_kap():
    cases0 = _b.build_cases(_cfg(_kb=0))
    cases8 = _b.build_cases(_cfg(_kb=8))
    szall0 = next(c for c in cases0 if c["cel"] == "Szallitas")
    szall8 = next(c for c in cases8 if c["cel"] == "Szallitas")
    assert "FIGYELEM" in szall0["elvart"]
    assert "FIGYELEM" not in szall8["elvart"]


def test_live_agent_elvaras_szovege():
    live = _b.build_cases(_cfg(live_agent=True))
    nolive = _b.build_cases(_cfg(live_agent=False))
    l = next(c for c in live if c["cel"] == "Kifejezett keres")
    n = next(c for c in nolive if c["cel"] == "Kifejezett keres")
    assert "operator_wait" in l["elvart"]
    assert "nincs elo pult" in n["elvart"]


def test_minden_esetnek_van_kerdese_es_elvarasa():
    for c in _b.build_cases(_cfg(search_fb=True, live_agent=True, _kb=5)):
        assert c["kerdes"].strip() and c["elvart"].strip()
        assert c["check"] in ("manual", "order_form", "handoff", "links")


# --- evaluate ----------------------------------------------------------------
def test_evaluate_order_form_webdoc_ok():
    case = {"check": "order_form"}
    s, _ = _b.evaluate(case, "order_status_form", ["number", "zip"], "", "", "webdoc")
    assert s == "OK"


def test_evaluate_order_form_rossz_mezok():
    case = {"check": "order_form"}
    s, note = _b.evaluate(case, "order_status_form", ["number", "email"], "", "", "webdoc")
    assert s == "NEZD MEG" and "zip" in note


def test_evaluate_handoff_ok_mindket_action():
    case = {"check": "handoff"}
    assert _b.evaluate(case, "collect_lead", None, "", "", "sellvio")[0] == "OK"
    assert _b.evaluate(case, "operator_wait", None, "", "", "sellvio")[0] == "OK"
    assert _b.evaluate(case, None, None, "", "", "sellvio")[0] == "NEZD MEG"


def test_evaluate_links():
    case = {"check": "links"}
    assert _b.evaluate(case, None, None, "nezd: https://x.hu/p1", "", "s")[0] == "OK"
    assert _b.evaluate(case, None, None, "nincs link", "", "s")[0] == "NEZD MEG"


def test_evaluate_hiba_barmely_checknel():
    for chk in ("manual", "order_form", "handoff", "links"):
        s, note = _b.evaluate({"check": chk}, None, None, "", "timeout", "s")
        assert s == "HIBA" and note == "timeout"


def test_evaluate_manual():
    assert _b.evaluate({"check": "manual"}, None, None, "valasz", "", "s") == ("— kezi", "")


def test_order_form_fields_of_alakok():
    assert _b.order_form_fields_of({"order_form": {"fields": ["number", "zip"]}}) == ["number", "zip"]
    assert _b.order_form_fields_of({"order_form": ["number", "email"]}) == ["number", "email"]
    assert _b.order_form_fields_of({}) is None

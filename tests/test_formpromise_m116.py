# -*- coding: utf-8 -*-
"""m116: urlap-igeret felismerese (valodi korpusz-mondatokbol)."""
import importlib.util
import os

_P = os.path.join(os.path.dirname(__file__), "..", "app", "services", "formpromise.py")
_spec = importlib.util.spec_from_file_location("formpromise_m116", _P)
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)


def test_order_promise_megjeleno():
    assert fp.promised_form("Kérlek add meg a megjelenő űrlapon a **rendelésszámodat** és a "
                            "rendeléskor használt e-mail-címed.") == "order"


def test_order_promise_alabbi():
    assert fp.promised_form("csak töltsd ki az alábbi űrlapot a rendelésszámoddal és az "
                            "e-mail-címeddel") == "order"


def test_lead_promise():
    assert fp.promised_form("Add meg az elérhetőségeidet a megjelenő űrlapon, hogy a kolléga "
                            "felvegye veled a kapcsolatot.") == "lead"


def test_conditional_offer_not_promise():
    assert fp.promised_form("Ha a rendelésed állapotára vagy kíváncsi, szólj, és megjelenítek "
                            "egy űrlapot, ahol megadhatod a rendelésszámot.") is None


def test_back_reference_not_promise():
    assert fp.promised_form("Kérlek, ellenőrizd, hogy a fenti űrlapon mindkét adat "
                            "(rendelésszám + e-mail) helyesen szerepel-e.") is None


def test_shop_form_link_not_promise():
    assert fp.promised_form("Ehhez az alábbi oldalon van egy űrlap: [Jótállási bejelentés]"
                            "(https://www.kellegyszerszam.hu/jotallas-bejelentes)") is None
    assert fp.promised_form("a [jótállás-bejelentő űrlapon](https://x.hu/j) tudod megtenni, "
                            "a rendelésszámmal") is None


def test_product_text_not_promise():
    assert fp.promised_form("9 tűs mátrix nyomtató, folyamatos űrlapokhoz") is None


def test_no_context_none():
    assert fp.promised_form("Töltsd ki a megjelenő űrlapot.") is None


def test_chat_wiring_present():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "api", "chat.py"),
               encoding="utf-8").read()
    assert "m116 urlap-igeret" in src and "promised_form" in src

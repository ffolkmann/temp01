"""Webdoc rendelés-státusz — pure logika (m29).

A hálózati ág (_webdoc_lookup) nincs itt: a number->id feloldást, az irányítószám-
guardot és a kódszótárt fedjük, azaz mindent, ami adatvédelmi szempontból dönt.
"""

from types import SimpleNamespace

import pytest

from app.services.webdoc_status import (
    DEFAULT_STATUS_MAP,
    first_order,
    normalize_zip,
    order_zips,
    parse_order_number,
    pick_items,
    pick_payment,
    pick_shipping,
    pick_status,
    status_maps,
    zip_matches,
)


# --- rendelésszám -> id ------------------------------------------------------
@pytest.mark.parametrize(
    "raw,want",
    [
        ("2026/0047322", 47322),
        ("2026 / 0047322", 47322),
        ("#47322", 47322),
        (" # 2026/0047322 ", 47322),
        ("47322", 47322),
        ("0047322", 47322),
    ],
)
def test_parse_order_number_ok(raw, want):
    assert parse_order_number(raw) == want


@pytest.mark.parametrize("raw", ["", "  ", "abc", "2026/", "2026/abc", "0", "#0", None, "12/34/56"])
def test_parse_order_number_bad(raw):
    assert parse_order_number(raw) is None


# --- irányítószám ------------------------------------------------------------
@pytest.mark.parametrize("raw,want", [(1111, "1111"), ("1111", "1111"), (" 7694 ", "7694")])
def test_normalize_zip_ok(raw, want):
    assert normalize_zip(raw) == want


@pytest.mark.parametrize("raw", ["", None, "111", "11111", "abcd", "11a1", 0])
def test_normalize_zip_bad(raw):
    assert normalize_zip(raw) == ""


def _order(ship_zip=None, bill_zip=None):
    o = {"id": 47322, "number": "2026/0047322"}
    if ship_zip is not None:
        o["shipping"] = {"delivery": {"address": {"zip": ship_zip}}}
    if bill_zip is not None:
        o["payment"] = {"billing": {"address": {"zip": bill_zip}}}
    return o


def test_order_zips_both():
    assert order_zips(_order(ship_zip=1111, bill_zip=7694)) == ["1111", "7694"]


def test_order_zips_dedup():
    assert order_zips(_order(ship_zip=1111, bill_zip=1111)) == ["1111"]


def test_order_zips_billing_only_csomagpont():
    """Személyes átvét / csomagpont: nincs szállítási irsz, csak számlázási (élesben 32%)."""
    o = _order(bill_zip=7694)
    o["shipping"] = {"id": 4, "aptNumber": "hu328"}
    assert order_zips(o) == ["7694"]


def test_zip_matches_shipping():
    assert zip_matches(_order(ship_zip=1111, bill_zip=7694), "1111") is True


def test_zip_matches_billing():
    assert zip_matches(_order(ship_zip=1111, bill_zip=7694), "7694") is True


def test_zip_matches_wrong():
    assert zip_matches(_order(ship_zip=1111, bill_zip=7694), "9999") is False


@pytest.mark.parametrize("want", ["", None, "111", "abcd"])
def test_zip_matches_fail_closed(want):
    """Érvénytelen bemenetnél NEM matched — inkább ne adjunk ki adatot."""
    assert zip_matches(_order(ship_zip=1111), want) is False


def test_zip_matches_empty_string_zip_in_order():
    """Az API csomagpontnál üres stringet ad a zip helyén — az ne legyen match."""
    assert zip_matches(_order(ship_zip="", bill_zip=7694), "7694") is True
    assert zip_matches(_order(ship_zip=""), "") is False


# --- kódszótár ---------------------------------------------------------------
def test_status_maps_default_when_no_tenant_override():
    t = SimpleNamespace(order_status_map=None)
    m = status_maps(t)
    assert m["status"]["3"] == "Feldolgozás alatt"
    assert m["payment_paid"]["1"] == "fizetve"


def test_status_maps_tenant_overrides_and_extends():
    t = SimpleNamespace(order_status_map={"shipping": {"6": "Sprinter futár", "1": "Kiszállítás"}})
    m = status_maps(t)
    assert m["shipping"]["6"] == "Sprinter futár"   # új kód
    assert m["shipping"]["1"] == "Kiszállítás"      # felülírt
    assert m["shipping"]["4"] == "FoxPost"          # defaultból megmaradt
    assert m["status"]["1"] == "Rendelés megérkezett"


def test_status_maps_ignores_garbage():
    t = SimpleNamespace(order_status_map={"status": "nem dict", "shipping": {"1": ""}})
    m = status_maps(t)
    assert m["status"]["1"] == "Rendelés megérkezett"
    assert m["shipping"]["1"] == "Házhozszállítás"


def test_status_maps_no_tenant():
    assert status_maps(None)["status"]["6"] == "Törölve"


def test_default_map_not_mutated_by_override():
    t = SimpleNamespace(order_status_map={"status": {"1": "XXX"}})
    status_maps(t)
    assert DEFAULT_STATUS_MAP["status"]["1"] == "Rendelés megérkezett"


# --- mező-kiolvasás ----------------------------------------------------------
def test_pick_status_known():
    o = {"status": {"id": 3, "dateTime": "2026-07-08 10:06:41"}}
    assert pick_status(o, status_maps(None)) == ("Feldolgozás alatt", "2026-07-08 10:06:41")


def test_pick_status_unknown_code_gives_empty_name():
    """Nyers kód és az 'ismeretlen' szó SOHA nem mehet ki a vásárlónak."""
    name, _dt = pick_status({"status": {"id": 99}}, status_maps(None))
    assert name == ""


def test_pick_shipping_undocumented_code_is_empty():
    """A 6/7/8 élesben létezik, de a doksiban nincs -> nem mondunk szállítási módot."""
    assert pick_shipping({"shipping": {"id": 6}}, status_maps(None)) == ""


def test_pick_shipping_after_admin_override():
    t = SimpleNamespace(order_status_map={"shipping": {"6": "Sprinter futár"}})
    assert pick_shipping({"shipping": {"id": 6}}, status_maps(t)) == "Sprinter futár"


def test_pick_payment_mode_and_paid():
    o = {"payment": {"id": 4, "status": 1}}
    assert pick_payment(o, status_maps(None)) == "Bankkártya (online) – fizetve"


def test_pick_payment_unpaid():
    o = {"payment": {"id": 1, "status": 0}}
    assert pick_payment(o, status_maps(None)) == "Utánvét (készpénz) – nincs fizetve"


def test_pick_payment_bool_status():
    """A spec 'boolean'-t ír, az élesben 0/1 int jön — mindkettő működjön."""
    assert pick_payment({"payment": {"id": 3, "status": True}}, status_maps(None)).endswith("fizetve")


def test_pick_payment_unknown_mode_keeps_paid():
    assert pick_payment({"payment": {"id": 99, "status": 1}}, status_maps(None)) == "fizetve"


def test_pick_payment_empty():
    assert pick_payment({}, status_maps(None)) == ""


def test_pick_items():
    o = {"items": [
        {"name": "HP DeskJet 2710E", "quantity": 2},
        {"name": "", "quantity": 1},
        {"name": "Egér", "quantity": 1.0},
        "nem dict",
    ]}
    assert pick_items(o) == [("HP DeskJet 2710E", "2"), ("Egér", "1")]


def test_pick_items_no_price_leak():
    o = {"items": [{"name": "X", "quantity": 1, "price": {"ammount": 199900, "vat": 27}}]}
    assert pick_items(o) == [("X", "1")]


# --- válasz-alak -------------------------------------------------------------
def test_first_order_from_list():
    assert first_order([{"id": 1}, {"id": 2}])["id"] == 1


def test_first_order_from_bare_object():
    assert first_order({"id": 47322})["id"] == 47322


def test_first_order_from_wrapper():
    assert first_order({"orders": [{"id": 7}]})["id"] == 7


@pytest.mark.parametrize("payload", [[], {}, None, "x", [{"nincs_id": 1}], {"orders": []}])
def test_first_order_empty(payload):
    assert first_order(payload) is None

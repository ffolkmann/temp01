"""Sellvio + Unas order-lookup teljes értékű ág — tételek + szállítási mód, adatvédelmi guard.

A modult FÁJLBÓL töltjük (importlib); a platform_api-t VALÓDIAN töltjük (a norm_email /
xml_root / xml_first_text pure helperek kellenek), a mailert stubbal, a hálózatot pedig
fake httpx-klienssel + felülírt token/login-nel váltjuk ki (nincs valódi hívás).

Fixture-ök: Sellvio JSON és Unas XML minta-válaszok. Kulcs-invariáns (adatvédelem):
email + rendelésszám EGYÜTTES egyezés -> matched (tételek+szállítás); csak email VAGY
csak rendelésszám -> NEM matched.
"""

import asyncio
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]

# --- app package stubok -----------------------------------------------------
for _name in ("app", "app.core", "app.services", "app.models"):
    _m = sys.modules.setdefault(_name, types.ModuleType(_name))
    _m.__path__ = []

_mailer = types.ModuleType("app.core.mailer")
_mailer.schedule_email = lambda *a, **k: None
sys.modules["app.core.mailer"] = _mailer

# --- VALÓDI platform_api (pure helperek: norm_email / xml_root / xml_first_text) ---
_pa_path = ROOT / "app" / "services" / "platform_api.py"
_pa_spec = importlib.util.spec_from_file_location("app.services.platform_api", _pa_path)
_pa = importlib.util.module_from_spec(_pa_spec)
sys.modules["app.services.platform_api"] = _pa
_pa_spec.loader.exec_module(_pa)

# --- order_status under test ------------------------------------------------
_p = ROOT / "app" / "services" / "order_status.py"
_spec = importlib.util.spec_from_file_location("order_status_under_test", _p)
_os = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_os)


# --------------------------------------------------------------------------- #
# Fake httpx / tenant / order
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, *, json_data=None, text=""):
        self._json = json_data
        self.text = text
        self.content = b"x"
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self):
        return None

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, *, get_resp=None, post_resp=None):
        self._get = get_resp
        self._post = post_resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        return self._get

    async def post(self, url, **kw):
        return self._post


def _patch(monkeypatch, *, get_resp=None, post_resp=None):
    fake_httpx = types.SimpleNamespace(
        AsyncClient=lambda *a, **k: _FakeClient(get_resp=get_resp, post_resp=post_resp),
        HTTPError=Exception,
    )
    monkeypatch.setattr(_os, "httpx", fake_httpx)

    async def _tok(*a, **k):
        return "tok"

    monkeypatch.setattr(_os, "sellvio_token", _tok)
    monkeypatch.setattr(_os, "unas_login", _tok)


def _tenant(platform):
    return types.SimpleNamespace(
        client_id="teszt",
        platform=platform,
        bot_name="TesztBot",
        api_base="https://shop.example.com",
        api_client_id="cid",
        api_client_secret="secret",
    )


def _order(order_id, email):
    return types.SimpleNamespace(order_id=order_id, order_email=email)


# --------------------------------------------------------------------------- #
# Fixture-ök
# --------------------------------------------------------------------------- #
SELLVIO_BODY = {
    "data": {
        "items": [
            {  # egy MÁSIK vevő rendelése — nem szabad kiadni
                "id": 555,
                "email": "masik@example.com",
                "status": {"name": "Lezárva"},
                "delivery_type": {"name": "Személyes átvétel"},
                "order_items": [{"name": "Más termék", "quantity": 1}],
            },
            {  # a keresett rendelés
                "id": 12345,
                "email": "Vevo@Example.com",  # nagybetű -> norm_email teszt
                "created_at": "2026-07-01",
                "payment_status": "paid",
                "payment_type": "card",
                "status": {"name": "Feldolgozás alatt"},
                "delivery_type": {"name": "GLS futárszolgálat"},
                "deliveries": [{"name": "GLS csomagpont"}],
                "order_items": [
                    {"name": "Teszt termék A", "quantity": 2},
                    {"name": "Teszt termék B", "quantity": 1},
                ],
                "addresses": [{"city": "Budapest"}],
            },
        ],
        "last_page": 1,
        "next_page_url": None,
    }
}

UNAS_ORDER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Orders><Order>"
    "<Key>67890</Key>"
    "<Status>Teljesítve</Status>"  # rendelés-SZINTŰ státusz (Order közvetlen gyereke)
    "<Customer><Email>vevo@example.com</Email></Customer>"
    "<Delivery><Type>package</Type><Mode>Csomagküldő automata</Mode></Delivery>"
    "<Items>"
    "<Item><Id>1</Id><Sku>SKU1</Sku><Name><![CDATA[Unas Termék A]]></Name>"
    "<Unit>db</Unit><Quantity>3</Quantity><PriceNet>1000</PriceNet>"
    "<PriceGross>1270</PriceGross><Vat>27</Vat><Status>Raktáron</Status></Item>"
    "<Item><Id>2</Id><Sku>SKU2</Sku><Name>Unas Termék B</Name>"
    "<Unit>db</Unit><Quantity>1</Quantity><PriceNet>500</PriceNet>"
    "<PriceGross>635</PriceGross><Vat>27</Vat><Status>Raktáron</Status></Item>"
    "</Items>"
    "</Order></Orders>"
)

# csak email egyezik, rendelésszám NEM -> a Key-szűrő miatt a szerver üres választ ad
UNAS_EMPTY_XML = '<?xml version="1.0" encoding="UTF-8"?><Orders></Orders>'


# --------------------------------------------------------------------------- #
# Pure helper tesztek
# --------------------------------------------------------------------------- #
def test_fmt_qty():
    assert _os._fmt_qty(2) == "2"
    assert _os._fmt_qty("2.0") == "2"
    assert _os._fmt_qty("2,0") == "2"
    assert _os._fmt_qty("1.5") == "1.5"
    assert _os._fmt_qty("") == ""
    assert _os._fmt_qty("kb") == "kb"


def test_format_order_note():
    n = _os._format_order_note([("A", "2"), ("B", "1")], "GLS")
    assert n == "Tételek: 2× A; 1× B. Szállítási mód: GLS."
    # üres qty -> csak név; üres/nincs delivery -> nincs szállítás rész
    assert _os._format_order_note([("A", "")], "") == "Tételek: A."
    # névtelen tétel kimarad
    assert _os._format_order_note([("", "3"), ("B", "1")], "") == "Tételek: 1× B."
    # nincs tétel, csak szállítás
    assert _os._format_order_note([], "Foxpost") == "Szállítási mód: Foxpost."
    assert _os._format_order_note([], "") == ""


def test_sellvio_match_both_required():
    items = SELLVIO_BODY["data"]["items"]
    # email + id egyezik -> matched
    ok, o = _os._sellvio_match(items, "12345", "vevo@example.com")
    assert ok is True and o["id"] == 12345
    # id egyezik, email NEM -> nem matched (guard), de az ordert visszaadja (megállásra)
    ok, o = _os._sellvio_match(items, "12345", "rossz@example.com")
    assert ok is False and o is not None
    # id NEM egyezik -> nem matched, nincs order (lapozni kell)
    ok, o = _os._sellvio_match(items, "99999", "vevo@example.com")
    assert ok is False and o is None


def test_sellvio_extractors():
    o = SELLVIO_BODY["data"]["items"][1]
    assert _os._sellvio_status(o) == "Feldolgozás alatt"
    assert _os._sellvio_delivery(o) == "GLS futárszolgálat"
    assert _os._sellvio_items(o) == [("Teszt termék A", "2"), ("Teszt termék B", "1")]
    # status str-alak és fallback
    assert _os._sellvio_status({"status": "Kiszállítva"}) == "Kiszállítva"
    assert _os._sellvio_status({"payment_status": "paid"}) == "ismeretlen"


def test_unas_order_status_ignores_item_status():
    root = _pa.xml_root(UNAS_ORDER_XML)
    order_el = root.find(".//Order")
    # a rendelés-szintű Status (Teljesítve), NEM az Item <Status>Raktáron</Status>
    assert _os._unas_order_status(order_el) == "Teljesítve"


def test_unas_extractors():
    root = _pa.xml_root(UNAS_ORDER_XML)
    order_el = root.find(".//Order")
    assert _os._unas_items(order_el) == [("Unas Termék A", "3"), ("Unas Termék B", "1")]
    assert _os._unas_delivery(order_el) == "Csomagküldő automata"


# --------------------------------------------------------------------------- #
# Sellvio lookup — integrációs (fake httpx)
# --------------------------------------------------------------------------- #
def test_sellvio_matched(monkeypatch):
    _patch(monkeypatch, get_resp=_FakeResp(json_data=SELLVIO_BODY))
    matched, status, note = asyncio.run(
        _os._sellvio_lookup(_tenant("sellvio"), _order("12345", "vevo@example.com"))
    )
    assert matched is True
    assert status == "Feldolgozás alatt"
    assert note == "Tételek: 2× Teszt termék A; 1× Teszt termék B. Szállítási mód: GLS futárszolgálat."


def test_sellvio_only_id_not_matched(monkeypatch):
    # helyes rendelésszám, ROSSZ email -> NEM matched, nincs note
    _patch(monkeypatch, get_resp=_FakeResp(json_data=SELLVIO_BODY))
    matched, status, note = asyncio.run(
        _os._sellvio_lookup(_tenant("sellvio"), _order("12345", "rossz@example.com"))
    )
    assert matched is False
    assert note == ""


def test_sellvio_only_email_not_matched(monkeypatch):
    # helyes email, ROSSZ rendelésszám -> NEM matched
    _patch(monkeypatch, get_resp=_FakeResp(json_data=SELLVIO_BODY))
    matched, status, note = asyncio.run(
        _os._sellvio_lookup(_tenant("sellvio"), _order("99999", "vevo@example.com"))
    )
    assert matched is False
    assert note == ""


# --------------------------------------------------------------------------- #
# Unas lookup — integrációs (fake httpx)
# --------------------------------------------------------------------------- #
def test_unas_matched(monkeypatch):
    _patch(monkeypatch, post_resp=_FakeResp(text=UNAS_ORDER_XML))
    matched, status, note = asyncio.run(
        _os._unas_lookup(_tenant("unas"), _order("67890", "vevo@example.com"))
    )
    assert matched is True
    assert status == "Teljesítve"
    assert note == "Tételek: 3× Unas Termék A; 1× Unas Termék B. Szállítási mód: Csomagküldő automata."


def test_unas_only_id_not_matched(monkeypatch):
    # a szerver a Key alapján visszaadja a rendelést, de a válasz email-je NEM egyezik -> NEM matched
    _patch(monkeypatch, post_resp=_FakeResp(text=UNAS_ORDER_XML))
    matched, status, note = asyncio.run(
        _os._unas_lookup(_tenant("unas"), _order("67890", "rossz@example.com"))
    )
    assert matched is False
    assert note == ""


def test_unas_only_email_not_matched(monkeypatch):
    # rossz rendelésszám -> a Key-szűrő üres választ ad (nincs Order) -> NEM matched
    _patch(monkeypatch, post_resp=_FakeResp(text=UNAS_EMPTY_XML))
    matched, status, note = asyncio.run(
        _os._unas_lookup(_tenant("unas"), _order("99999", "vevo@example.com"))
    )
    assert matched is False
    assert note == ""

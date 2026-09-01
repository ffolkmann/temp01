"""m96: Kontúr Reklám élő ár/készlet — POST {api_client_id}/products {"skus":[sku]}.

Amit rögzít:
  (1) kontur_live_from_product: variáns-összegzés (qty = készlet-összeg, available = van
      raktáros variáns, price = "nettó X Ft-tól" a legolcsóbb variánsból, note a kifutó-jellel)
  (2) _kontur_live: X-Api-Key fejléc + POST body; a válaszban a kért sku-t választja
  (3) 10 perces per-sku cache: második hívás NEM megy ki
  (4) óránkénti 80-as plafon: fölötte nincs hívás, None (vagy a régi cache), a chat nem törik
  (5) fail-safe: hiányzó base/kulcs -> None hívás nélkül; üres válasz -> None

A live_product.py-t fájl-betöltéssel húzzuk be, a platform_api-t ideiglenes stubbal
(sys.modules visszaállítva finally-ben — a suite más tesztjei fake app.services-t hagyhatnak).
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])


def _load_live():
    saved = {k: sys.modules.get(k) for k in ("app", "app.services", "app.services.platform_api")}
    try:
        for n in ("app", "app.services"):
            if n not in sys.modules:
                sys.modules[n] = types.ModuleType(n)
                sys.modules[n].__path__ = []
        pa = types.ModuleType("app.services.platform_api")
        for name in ("UNAS_BASE", "sellvio_token", "shoprenter_shop", "shoprenter_token",
                     "unas_login", "xml_first_text", "xml_root"):
            setattr(pa, name, (lambda *a, **k: None) if name != "UNAS_BASE" else "x")
        sys.modules["app.services.platform_api"] = pa
        spec = importlib.util.spec_from_file_location(
            "live_product_m96_kontur", f"{ROOT}/app/services/live_product.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m          # a @dataclass exec kozben sys.modules-bol olvassa a modult
        try:
            spec.loader.exec_module(m)
        finally:
            sys.modules.pop(spec.name, None)
        return m
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


live = _load_live()


class _T:
    client_id = "konturreklam"
    platform = "kontur"
    api_base = "https://www.konturreklam.hu/chatbot_feed.php"
    api_client_id = "https://api.konturreklam.hu"
    api_client_secret = "kr_test_key"
    public_url = "https://www.konturreklam.hu/"


def _api_product(**kw):
    p = {
        "sku": "U GI5000", "name": "HEAVY COTTON™ FELNŐTT PÓLÓ", "active": True, "price_net_from": 858,
        "variants": [
            {"variant_sku": "a", "color": "Red", "size": "S", "price_net": 1047, "stock": 509,
             "discontinued": False, "available": True},
            {"variant_sku": "b", "color": "Red", "size": "3XL", "price_net": 1536, "stock": 0,
             "discontinued": False, "available": False},
            {"variant_sku": "c", "color": "White", "size": "S", "price_net": 858, "stock": 12000,
             "discontinued": False, "available": True},
        ],
        "currency": "HUF", "price_type": "net", "checked_at": "2026-08-31T16:50:10+02:00",
    }
    p.update(kw)
    return p


def test_parse_product():
    r = live.kontur_live_from_product(_api_product())
    assert r is not None and r.has_data()
    assert r.qty == 12509 and r.available is True
    assert r.price == "nettó 858 Ft-tól"
    assert r.name.startswith("HEAVY COTTON")
    assert "2/3 szín-méret variáns raktáron" in r.note and "nettó" in r.note
    assert "KIFUTÓ" not in r.note


def test_parse_edge_cases():
    # kifutó termék + egyforma árak + available hiányzik (a készletből származik)
    p = _api_product(discontinued=True, variants=[
        {"variant_sku": "a", "color": "Navy", "size": "S", "price_net": 12345, "stock": 3},
        {"variant_sku": "b", "color": "Navy", "size": "M", "price_net": 12345, "stock": 0},
    ])
    r = live.kontur_live_from_product(p)
    assert r.price == "nettó 12 345 Ft" and r.qty == 3 and r.available is True
    assert "KIFUTÓ termék" in r.note and "1/2" in r.note
    # minden variáns 0 -> available False, qty 0
    p0 = _api_product(variants=[{"variant_sku": "a", "color": "X", "size": "S", "price_net": 1, "stock": 0}])
    r0 = live.kontur_live_from_product(p0)
    assert r0.available is False and r0.qty == 0
    assert live.kontur_live_from_product({"sku": "x", "variants": []}) is None
    assert live.kontur_live_from_product(None) is None


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)

    def json(self):
        return self._p


class _Client:
    calls = []
    payload = {"products": []}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, **k):
        _Client.calls.append((url, json, headers))
        return _Resp(_Client.payload)


def _fresh(now=1000.0):
    live._kontur_cache.clear()
    live._kontur_calls.clear()
    _Client.calls.clear()
    live.httpx = types.SimpleNamespace(AsyncClient=_Client)
    live._kontur_now = lambda: now


def test_live_call_headers_cache_and_pick():
    _fresh()
    _Client.payload = {"products": [_api_product(sku="OTHER", name="Masik"), _api_product()]}
    r = asyncio.run(live._kontur_live(_T(), "U GI5000"))
    assert r is not None and r.name.startswith("HEAVY") and r.qty == 12509
    assert len(_Client.calls) == 1
    url, body, hdr = _Client.calls[0]
    assert url == "https://api.konturreklam.hu/products"
    assert body == {"skus": ["U GI5000"]}
    assert hdr["X-Api-Key"] == "kr_test_key" and "User-Agent" in hdr
    # (3) cache: második hívás nem megy ki
    r2 = asyncio.run(live._kontur_live(_T(), "U GI5000"))
    assert r2 is r and len(_Client.calls) == 1
    # lejárt cache -> újra hív
    live._kontur_now = lambda: 1000.0 + live._KONTUR_TTL + 1
    asyncio.run(live._kontur_live(_T(), "U GI5000"))
    assert len(_Client.calls) == 2


def test_dispatch_via_fetch_live_price_stock():
    _fresh()
    _Client.payload = {"products": [_api_product()]}
    cur = types.SimpleNamespace(payload={"sku": "U GI5000", "type": "product"})
    r = asyncio.run(live.fetch_live_price_stock(_T(), cur))
    assert r is not None and r.qty == 12509 and len(_Client.calls) == 1
    assert "kontur" in live._LIVE and live._ID_FIELDS["kontur"] == ()


def test_hourly_cap():
    _fresh(now=5000.0)
    _Client.payload = {"products": [_api_product()]}
    # 80 különböző sku az elmúlt órában -> a 81. nem megy ki
    for i in range(live._KONTUR_HOURLY_CAP):
        asyncio.run(live._kontur_live(_T(), f"SKU-{i}"))
    assert len(_Client.calls) == live._KONTUR_HOURLY_CAP
    r = asyncio.run(live._kontur_live(_T(), "SKU-NEW"))
    assert r is None and len(_Client.calls) == live._KONTUR_HOURLY_CAP
    # a cache-elt sku plafon fölött is a régi értéket adja (hívás nélkül)
    r0 = asyncio.run(live._kontur_live(_T(), "SKU-0"))
    assert r0 is not None and len(_Client.calls) == live._KONTUR_HOURLY_CAP
    # egy óra múlva újra szabad
    live._kontur_now = lambda: 5000.0 + 3601.0
    asyncio.run(live._kontur_live(_T(), "SKU-NEW"))
    assert len(_Client.calls) == live._KONTUR_HOURLY_CAP + 1


def test_fail_safe():
    _fresh()
    _Client.payload = {"products": []}
    assert asyncio.run(live._kontur_live(_T(), "U GI5000")) is None
    assert asyncio.run(live._kontur_live(_T(), "")) is None
    t = _T()
    t.api_client_secret = ""
    assert asyncio.run(live._kontur_live(t, "U GI5000")) is None
    t2 = _T()
    t2.api_client_id = "nem-url"
    assert asyncio.run(live._kontur_live(t2, "U GI5000")) is None
    assert len(_Client.calls) == 1   # csak az üres-válasz eset hívott

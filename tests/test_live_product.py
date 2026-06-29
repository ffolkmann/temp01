"""live_product teszt — injektált fake httpx + platform_api (dev-gépen is fut).
Futtatás: python tests/test_live_product.py

Lefedi: platform-id feloldás (sellvio_id/fallback sku), Sellvio/WC/Shoprenter/Unas
élő ár/készlet kinyerés, fail-safe (hiba->None, üres->None, ismeretlen platform->None).
"""
import asyncio
import importlib.util
import sys
import types

ROOT = "/home/folkm/chatbot"
for name in ("app", "app.core", "app.services", "app.models"):
    sys.modules.setdefault(name, types.ModuleType(name)).__path__ = []

# --- fake httpx: URL-substring router ---
REQS = []
ROUTES = {}
class _Resp:
    def __init__(self, spec): self._spec = spec or {}
    def raise_for_status(self):
        if self._spec.get("raise"): raise RuntimeError("HTTP error")
    def json(self): return self._spec.get("json", {})
    @property
    def text(self): return self._spec.get("text", "")
def _match(url):
    for sub, spec in ROUTES.items():
        if sub in url: return _Resp(spec)
    return _Resp({"json": {}, "text": ""})
class _Client:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, data=None, json=None, content=None, headers=None, **k):
        REQS.append(("POST", url, {"content": content.decode() if isinstance(content, bytes) else content}))
        return _match(url)
    async def get(self, url, auth=None, headers=None, params=None, **k):
        REQS.append(("GET", url, {"auth": auth, "headers": headers, "params": params})); return _match(url)
fh = types.ModuleType("httpx"); fh.AsyncClient = _Client; sys.modules["httpx"] = fh

# --- valódi platform_api (faked httpx), app.services.platform_api néven ---
_pa_spec = importlib.util.spec_from_file_location(
    "app.services.platform_api", f"{ROOT}/app/services/platform_api.py")
_pa = importlib.util.module_from_spec(_pa_spec)
sys.modules["app.services.platform_api"] = _pa
_pa_spec.loader.exec_module(_pa)

# --- valódi live_product.py ---
spec = importlib.util.spec_from_file_location("lp_under_test", f"{ROOT}/app/services/live_product.py")
lp = importlib.util.module_from_spec(spec)
sys.modules["lp_under_test"] = lp          # @dataclass module-lookup miatt (Py3.14)
spec.loader.exec_module(lp)


class T:
    def __init__(self, platform, base="https://shop.example.hu"):
        self.client_id="c"; self.platform=platform; self.api_base=base
        self.api_client_id="id"; self.api_client_secret="sec"
class C:  # duck-typed CurrentProduct: csak payload kell
    def __init__(self, payload): self.payload = payload

def reset(): REQS.clear(); ROUTES.clear()


async def main():
    ok = []

    # --- _product_id: platform-id (igazolt mezők) + sku fallback ---
    assert lp._product_id({"sellvio_id": "777", "sku": "ABC"}, "sellvio") == "777"
    assert lp._product_id({"sku": "ABC"}, "sellvio") == "ABC"          # fallback
    assert lp._product_id({"wc_id": 55, "sku": ""}, "woocommerce") == "55"   # wc_id, NEM woo_id
    assert lp._product_id({"sku": "SK"}, "shoprenter") == "SK"         # SR: nincs id -> sku
    assert lp._product_id({"sku": "SK"}, "unas") == "SK"              # Unas: nincs id -> sku
    assert lp._product_id({}, "sellvio") == ""
    ok.append("_product_id: sellvio_id / wc_id / SR+Unas sku")

    # --- Sellvio élő: price DICT (brutto_price), is_available_for_order, NINCS qty ---
    reset()
    ROUTES["/oauth/token"] = {"json": {"access_token": "tok"}}
    ROUTES["/api/v2/products/"] = {"json": {"data": {"name": "X",
        "price": {"netto_price": 63465, "vat": 27, "brutto_price": 80600, "discount": 0},
        "is_available_for_order": True}}}
    live = await lp.fetch_live_price_stock(T("sellvio", "https://teslashop.sellvio.hu"),
                                           C({"sellvio_id": "777", "sku": "TSL1"}))
    assert live and live.price == "80600" and live.qty is None and live.available is True
    g = [q for q in REQS if q[0] == "GET"][0]
    assert g[1] == "https://teslashop.sellvio.hu/api/v2/products/777"   # sellvio_id az URL-ben
    ok.append("Sellvio élő: brutto_price, is_available_for_order, qty None")

    # --- WooCommerce élő: wc_id az URL-ben, sku üres is lehet ---
    reset()
    ROUTES["/wp-json/wc/v3/products/55"] = {"json": {
        "id": 55, "name": "W", "price": "12990", "stock_status": "outofstock", "stock_quantity": 0}}
    live = await lp.fetch_live_price_stock(T("woocommerce", "https://woo.example.hu"),
                                           C({"wc_id": 55, "sku": ""}))
    assert live and live.price == "12990" and live.qty == 0 and live.available is False
    ok.append("WooCommerce élő: wc_id (üres sku is ok), stock_status=outofstock")

    # --- Shoprenter élő: ?sku= szűrő, items[0], stock1, ár SYNCED (price="") ---
    reset()
    ROUTES["oauth.app.shoprenter.net"] = {"json": {"access_token": "srtok"}}
    ROUTES["/products"] = {"json": {"items": [
        {"name": "S", "price": "9990", "stock1": 10, "quantity": 0.0, "orderable": 1}]}}
    live = await lp.fetch_live_price_stock(T("shoprenter", "https://teslashop.api2.myshoprenter.hu/api"),
                                           C({"sku": "SKU-SR"}))
    assert live and live.qty == 10 and live.available is True
    assert live.price == ""                                            # ár synced marad
    g = [q for q in REQS if q[0] == "GET" and q[1].endswith("/products")][0]
    assert g[2]["params"] == {"sku": "SKU-SR", "full": "1"}
    ok.append("Shoprenter élő: ?sku=&full=1, items[0].stock1, price='' (synced)")

    # --- Unas élő: getProduct, Prices/Price[Actual=1]/Gross, Stocks/Stock/Qty ---
    reset()
    ROUTES["/shop/login"] = {"text": "<Login><Token>ut</Token></Login>"}
    ROUTES["/shop/getProduct"] = {"text": (
        "<Products><Product><Name>U</Name>"
        "<Prices><Price><Type>special</Type><Actual>0</Actual><Gross>5000</Gross></Price>"
        "<Price><Type>normal</Type><Actual>1</Actual><Net>3543</Net><Gross>4500</Gross></Price></Prices>"
        "<Stocks><Stock><Qty>10</Qty></Stock></Stocks></Product></Products>")}
    live = await lp.fetch_live_price_stock(T("unas"), C({"sku": "SKU9"}))
    assert live and live.price == "4500" and live.qty == 10 and live.available is True
    body = [q for q in REQS if "getProduct" in q[1]][0][2]["content"]
    assert "<Sku>SKU9</Sku>" in body
    ok.append("Unas élő: Actual=1 Gross (4500), Stocks/Stock/Qty (10)")

    # --- Unas multi-raktár: a fej-<Stock> (WarehouseId nélkül) qty-ja, SORREND-független ---
    reset()
    ROUTES["/shop/login"] = {"text": "<Login><Token>ut</Token></Login>"}
    ROUTES["/shop/getProduct"] = {"text": (
        "<Products><Product>"
        "<Prices><Price><Type>normal</Type><Actual>1</Actual><Gross>4990</Gross></Price></Prices>"
        "<Stocks>"
        "<Stock><WarehouseId>2</WarehouseId><Qty>3</Qty></Stock>"   # raktár — ELŐL
        "<Stock><Qty>5</Qty></Stock>"                              # fej (WarehouseId nélkül)
        "</Stocks></Product></Products>")}
    live = await lp.fetch_live_price_stock(T("unas"), C({"sku": "169059"}))
    assert live and live.qty == 5 and live.price == "4990"          # a fej 5, NEM az első (3)
    ok.append("Unas multi-raktár: fej-Stock qty=5 (sorrend-független, nem az első warehouse 3)")

    # --- Unas fallback: ha minden Stock raktár-specifikus -> első Qty ---
    reset()
    ROUTES["/shop/login"] = {"text": "<Login><Token>ut</Token></Login>"}
    ROUTES["/shop/getProduct"] = {"text": (
        "<Products><Product>"
        "<Prices><Price><Type>normal</Type><Actual>1</Actual><Gross>100</Gross></Price></Prices>"
        "<Stocks><Stock><WarehouseId>1</WarehouseId><Qty>7</Qty></Stock></Stocks>"
        "</Product></Products>")}
    live = await lp.fetch_live_price_stock(T("unas"), C({"sku": "X"}))
    assert live and live.qty == 7                                   # nincs fej-Stock -> fallback első Qty
    ok.append("Unas qty fallback: nincs fej-Stock -> első Qty (7)")

    # --- Unas ár fallback: nincs Actual=1 -> normal típusú Price Gross ---
    reset()
    ROUTES["/shop/login"] = {"text": "<Login><Token>ut</Token></Login>"}
    ROUTES["/shop/getProduct"] = {"text": (
        "<Products><Product><Prices>"
        "<Price><Type>normal</Type><Actual>0</Actual><Gross>7000</Gross></Price></Prices>"
        "<Stocks><Stock><Qty>0</Qty></Stock></Stocks></Product></Products>")}
    live = await lp.fetch_live_price_stock(T("unas"), C({"sku": "X"}))
    assert live and live.price == "7000" and live.qty == 0 and live.available is False
    ok.append("Unas ár fallback: normal típusú Price Gross; qty 0 -> nincs raktaron")

    # === FAIL-SAFE ===
    reset()
    ROUTES["/oauth/token"] = {"raise": True}
    live = await lp.fetch_live_price_stock(T("sellvio"), C({"sellvio_id": "9"}))
    assert live is None                                                # hiba -> None (synced marad)
    ok.append("hiba -> None (fail-safe, synced marad)")

    reset()
    live = await lp.fetch_live_price_stock(T("magento"), C({"sku": "S"}))
    assert live is None and REQS == []                                 # ismeretlen platform
    ok.append("ismeretlen platform -> None, nincs hívás")

    reset()
    live = await lp.fetch_live_price_stock(T("sellvio"), C({}))         # nincs id/sku
    assert live is None and REQS == []
    ok.append("nincs termék-azonosító -> None, nincs hívás")

    reset()
    ROUTES["/oauth/token"] = {"json": {"access_token": "tok"}}
    ROUTES["/api/v2/products/"] = {"json": {"data": {}}}               # üres -> has_data() False
    live = await lp.fetch_live_price_stock(T("sellvio"), C({"sellvio_id": "9"}))
    assert live is None
    ok.append("üres élő adat -> None (has_data False)")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

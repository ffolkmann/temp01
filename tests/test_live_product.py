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
    async def get(self, url, auth=None, headers=None, **k):
        REQS.append(("GET", url, {"auth": auth, "headers": headers})); return _match(url)
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

    # --- _product_id: platform-id elsőbbség, sku fallback ---
    assert lp._product_id({"sellvio_id": "777", "sku": "ABC"}, "sellvio") == "777"
    assert lp._product_id({"sku": "ABC"}, "sellvio") == "ABC"          # fallback
    assert lp._product_id({"id": 55}, "woocommerce") == "55"
    assert lp._product_id({}, "sellvio") == ""
    ok.append("_product_id: platform-id elsőbbség + sku fallback")

    # --- Sellvio élő ár/készlet ---
    reset()
    ROUTES["/oauth/token"] = {"json": {"access_token": "tok"}}
    ROUTES["/api/v2/products/"] = {"json": {"data": {
        "name": "X", "price": 80600, "stock": 5, "available": True}}}
    live = await lp.fetch_live_price_stock(T("sellvio", "https://teslashop.sellvio.hu"),
                                           C({"sellvio_id": "777", "sku": "TSL1"}))
    assert live and live.price == "80600" and live.qty == 5 and live.available is True
    g = [q for q in REQS if q[0] == "GET"][0]
    assert g[1] == "https://teslashop.sellvio.hu/api/v2/products/777"   # sellvio_id az URL-ben
    ok.append("Sellvio élő: price/qty/available, sellvio_id az URL-ben")

    # --- WooCommerce élő (stock_status + stock_quantity) ---
    reset()
    ROUTES["/wp-json/wc/v3/products/55"] = {"json": {
        "id": 55, "name": "W", "price": "12990", "stock_status": "outofstock", "stock_quantity": 0}}
    live = await lp.fetch_live_price_stock(T("woocommerce", "https://woo.example.hu"),
                                           C({"id": 55, "sku": "S"}))
    assert live and live.price == "12990" and live.qty == 0 and live.available is False
    ok.append("WooCommerce élő: price + stock_status=outofstock -> available False")

    # --- Shoprenter élő (base64 id, price dict-guard nem kell, scalar) ---
    reset()
    ROUTES["oauth.app.shoprenter.net"] = {"json": {"access_token": "srtok"}}
    ROUTES["/products/"] = {"json": {"id": "x", "name": "S", "price": "9990", "stock1": 3}}
    live = await lp.fetch_live_price_stock(T("shoprenter", "https://teslashop.api2.myshoprenter.hu/api"),
                                           C({"shoprenter_id": "12", "sku": "S"}))
    assert live and live.price == "9990" and live.qty == 3 and live.available is True
    import base64
    b64 = base64.b64encode(b"product-product_id=12").decode()
    geturl = [q for q in REQS if q[0] == "GET" and "/products/" in q[1]][0][1]
    assert geturl.endswith("/products/" + b64), geturl
    ok.append("Shoprenter élő: base64 product id, stock1 -> qty")

    # --- Unas élő (login -> getProduct XML) ---
    reset()
    ROUTES["/shop/login"] = {"text": "<Login><Token>ut</Token></Login>"}
    ROUTES["/shop/getProduct"] = {"text":
        "<Products><Product><Name>U</Name><Price>4500</Price><Stock>2</Stock></Product></Products>"}
    live = await lp.fetch_live_price_stock(T("unas"), C({"unas_id": "", "sku": "SKU9"}))
    assert live and live.price == "4500" and live.qty == 2 and live.available is True
    body = [q for q in REQS if "getProduct" in q[1]][0][2]["content"]
    assert "<Sku>SKU9</Sku>" in body                                    # sku fallback a kérésben
    ok.append("Unas élő: login token + getProduct XML Price/Stock")

    # --- price dict-guard: {gross: ...} -> string ---
    reset()
    ROUTES["/oauth/token"] = {"json": {"access_token": "tok"}}
    ROUTES["/api/v2/products/"] = {"json": {"data": {"price": {"gross": 1990}, "stock": 1}}}
    live = await lp.fetch_live_price_stock(T("sellvio"), C({"sellvio_id": "9"}))
    assert live and live.price == "1990"                               # dict->gross, nem stringelt dict
    ok.append("price dict {gross} -> '1990' (nem stringelt dict)")

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

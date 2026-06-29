"""order_status multi-platform teszt — injektált fake httpx + mailer (dev-gépen is fut).
Futtatás: python tests/test_order_status.py

Lefedi: Sellvio (regresszió), WooCommerce, Shoprenter, Unas; matched/mismatch;
ismeretlen platform; hiba-ág. A /chat MINDIG semleges választ kap; matched -> e-mail.
"""
import asyncio
import importlib.util
import sys
import types

ROOT = "/home/folkm/chatbot"
for name in ("app", "app.core", "app.services", "app.models"):
    sys.modules.setdefault(name, types.ModuleType(name)).__path__ = []

# --- fake app.core.mailer ---
SENT = []
fm = types.ModuleType("app.core.mailer")
fm.schedule_email = lambda to, subject, text: SENT.append({"to": to, "subject": subject, "text": text})
sys.modules["app.core.mailer"] = fm

# --- fake httpx: URL-substring router ---
REQS = []
ROUTES = {}      # url-substring -> {"json": obj} | {"text": str} | {"raise": True}
class _Resp:
    def __init__(self, spec): self._spec = spec or {"json": {}}
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
        REQS.append(("POST", url, {"data": data, "json": json,
                                   "content": content.decode() if isinstance(content, bytes) else content,
                                   "headers": headers})); return _match(url)
    async def get(self, url, auth=None, headers=None, **k):
        REQS.append(("GET", url, {"auth": auth, "headers": headers})); return _match(url)
fh = types.ModuleType("httpx"); fh.AsyncClient = _Client; sys.modules["httpx"] = fh

# --- valódi platform_api (faked httpx-szel), app.services.platform_api néven ---
_pa_spec = importlib.util.spec_from_file_location(
    "app.services.platform_api", f"{ROOT}/app/services/platform_api.py")
_pa = importlib.util.module_from_spec(_pa_spec)
sys.modules["app.services.platform_api"] = _pa
_pa_spec.loader.exec_module(_pa)

# --- valódi order_status.py ---
spec = importlib.util.spec_from_file_location("os_under_test", f"{ROOT}/app/services/order_status.py")
osm = importlib.util.module_from_spec(spec); spec.loader.exec_module(osm)
NEUTRAL = osm.ORDER_STATUS_REPLY

class T:
    def __init__(self, platform, base="https://shop.example.hu", bot="Bot"):
        self.client_id="c"; self.platform=platform; self.api_base=base
        self.api_client_id="id"; self.api_client_secret="sec"; self.bot_name=bot
class O:
    def __init__(self, oid="1234", email="vevo@x.hu"): self.order_id=oid; self.order_email=email

def reset(): REQS.clear(); SENT.clear(); ROUTES.clear()


async def main():
    ok = []

    # === Sellvio (regresszió) ===
    reset()
    ROUTES["/oauth/token"] = {"json": {"access_token": "tok"}}
    ROUTES["/api/v2/orders/"] = {"json": {"status": "success", "data": {
        "id": 9, "email": "VEVO@x.hu", "status": {"name": "Feldolgozas alatt"}}}}
    r = await osm.handle_order_status(T("sellvio", "https://teslashop.sellvio.hu/"), O("1234", "vevo@x.hu"))
    assert r == NEUTRAL and len(SENT) == 1, SENT
    assert SENT[0]["subject"] == "Rendelésed állapota – #1234"
    assert "Feldolgozas alatt" in SENT[0]["text"] and SENT[0]["to"] == "vevo@x.hu"
    ok.append("Sellvio matched -> e-mail (regresszió ép)")

    reset()
    ROUTES["/oauth/token"] = {"json": {"access_token": "tok"}}
    ROUTES["/api/v2/orders/"] = {"json": {"status": "success", "data": {"id": 9, "email": "masik@x.hu"}}}
    r = await osm.handle_order_status(T("sellvio"), O("1", "vevo@x.hu"))
    assert r == NEUTRAL and SENT == []
    ok.append("Sellvio email-mismatch -> nincs e-mail")

    # === WooCommerce ===
    reset()
    ROUTES["/wp-json/wc/v3/orders/1234"] = {"json": {
        "id": 1234, "status": "processing", "billing": {"email": "Vevo@x.hu"}}}
    r = await osm.handle_order_status(T("woocommerce", "https://woo.example.hu"), O("1234", "vevo@x.hu"))
    assert r == NEUTRAL and len(SENT) == 1 and "processing" in SENT[0]["text"]
    g = [q for q in REQS if q[0] == "GET"][0]
    assert g[1] == "https://woo.example.hu/wp-json/wc/v3/orders/1234"
    assert g[2]["auth"] == ("id", "sec")
    ok.append("WooCommerce matched -> e-mail (Basic auth, billing.email)")

    reset()
    ROUTES["/wp-json/wc/v3/orders/1234"] = {"json": {
        "id": 1234, "status": "completed", "billing": {"email": "masik@x.hu"}}}
    r = await osm.handle_order_status(T("woocommerce", "https://woo.example.hu"), O("1234", "vevo@x.hu"))
    assert r == NEUTRAL and SENT == []
    ok.append("WooCommerce mismatch -> nincs e-mail")

    # === Shoprenter (OAuth2 + base64 id) ===
    reset()
    ROUTES["oauth.app.shoprenter.net"] = {"json": {"access_token": "srtok"}}
    ROUTES["/orders/"] = {"json": {"id": "X", "statusName": "Teljesitve", "email": "vevo@x.hu"}}
    r = await osm.handle_order_status(
        T("shoprenter", "https://teslashop.api2.myshoprenter.hu/api"), O("18", "vevo@x.hu"))
    assert r == NEUTRAL and len(SENT) == 1 and "Teljesitve" in SENT[0]["text"]
    # token URL a shop-névvel
    tok = [q for q in REQS if "shoprenter.net" in q[1]][0]
    assert tok[1] == "https://oauth.app.shoprenter.net/teslashop/app/token"
    assert tok[2]["json"]["grant_type"] == "client_credentials"
    # base64 order id az URL-ben
    import base64
    b64 = base64.b64encode(b"order-order_id=18").decode()
    geturl = [q for q in REQS if q[0] == "GET" and "/orders/" in q[1]][0][1]
    assert geturl.endswith("/orders/" + b64), geturl
    ok.append("Shoprenter matched -> e-mail (OAuth2 token, base64 id)")

    # === Shoprenter status href-dict -> GUARD: ne dobjon, ne stringelje a dict-et ===
    reset()
    ROUTES["oauth.app.shoprenter.net"] = {"json": {"access_token": "srtok"}}
    ROUTES["/orders/"] = {"json": {"id": "X", "email": "vevo@x.hu",
        "orderStatus": {"href": "http://teslashop.api.myshoprenter.hu/orderStatuses/Yg=="}}}
    r = await osm.handle_order_status(
        T("shoprenter", "https://teslashop.api2.myshoprenter.hu/api"), O("18", "vevo@x.hu"))
    assert r == NEUTRAL and len(SENT) == 1, SENT          # match HELYES (top-level email)
    txt = SENT[0]["text"]
    assert "ismeretlen" in txt                            # generikus, nem a dict
    assert "href" not in txt and "{" not in txt           # a dict NEM lett stringelve
    ok.append("Shoprenter href-dict status -> guard: match ok, generikus, nincs dict-string")

    # === Unas (login->token, XML getOrder) ===
    reset()
    ROUTES["/shop/login"] = {"text": "<Login><Token>utok</Token></Login>"}
    ROUTES["/shop/getOrder"] = {"text":
        "<Orders><Order><Key>1234</Key><Status>Csomagolas</Status>"
        "<Customer><Email>vevo@x.hu</Email></Customer></Order></Orders>"}
    r = await osm.handle_order_status(T("unas"), O("1234", "vevo@x.hu"))
    assert r == NEUTRAL and len(SENT) == 1 and "Csomagolas" in SENT[0]["text"], SENT
    # getOrder Bearer tokennel ment
    go = [q for q in REQS if "getOrder" in q[1]][0]
    assert go[2]["headers"]["Authorization"] == "Bearer utok"
    assert "Contents" not in (go[2]["content"] or "")     # <Contents>full</Contents> törölve
    assert "<Key>1234</Key>" in (go[2]["content"] or "")
    ok.append("Unas matched -> e-mail; getOrder body <Contents> nélkül (Key megvan)")

    reset()
    ROUTES["/shop/login"] = {"text": "<Login><Token>utok</Token></Login>"}
    ROUTES["/shop/getOrder"] = {"text":
        "<Orders><Order><Key>1</Key><Status>X</Status><Email>masik@x.hu</Email></Order></Orders>"}
    r = await osm.handle_order_status(T("unas"), O("1", "vevo@x.hu"))
    assert r == NEUTRAL and SENT == []
    ok.append("Unas mismatch -> nincs e-mail")

    # === ismeretlen platform -> semleges, nincs hívás/e-mail ===
    reset()
    r = await osm.handle_order_status(T("magento"), O())
    assert r == NEUTRAL and SENT == [] and REQS == []
    ok.append("ismeretlen platform -> semleges, nincs e-mail")

    # === hiba-ág (token endpoint raise) -> semleges, nincs e-mail, nincs dobás ===
    reset()
    ROUTES["/oauth/token"] = {"raise": True}
    r = await osm.handle_order_status(T("sellvio"), O())
    assert r == NEUTRAL and SENT == []
    ok.append("platform hiba -> semleges, nincs e-mail, nincs dobás")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

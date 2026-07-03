"""TenantCORSMiddleware teszt — injektált fake starlette/sqlalchemy modulokkal,
hogy a dev-gépen (httpx/starlette nélkül) is fusson. Futtatás: python tests/test_cors.py

Elfogadási kritériumok (a feladatból):
  OPTIONS Origin=https://teslashop.hu        -> 200 + ACAO ugyanaz
  Origin=https://x.mysellvio.com             -> ACAO reflektálva (platform-suffix)
  Origin=https://evil.example.com            -> NINCS ACAO
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])

for name in ("app", "app.core", "app.models"):
    sys.modules.setdefault(name, types.ModuleType(name)).__path__ = []

# --- fake sqlalchemy ---
fake_sa = types.ModuleType("sqlalchemy")
fake_sa.select = lambda *a, **k: object()
sys.modules["sqlalchemy"] = fake_sa

# --- fake starlette.middleware.base / requests / responses ---
for n in ("starlette", "starlette.middleware", "starlette.middleware.base",
          "starlette.requests", "starlette.responses"):
    sys.modules.setdefault(n, types.ModuleType(n))
class BaseHTTPMiddleware:
    def __init__(self, app=None, dispatch=None): self.app = app
sys.modules["starlette.middleware.base"].BaseHTTPMiddleware = BaseHTTPMiddleware
sys.modules["starlette.requests"].Request = object
class Response:
    def __init__(self, status_code=200, headers=None, content=None):
        self.status_code = status_code; self.headers = dict(headers or {})
sys.modules["starlette.responses"].Response = Response

# --- fake app.core.db + models ---
fake_db = types.ModuleType("app.core.db"); fake_db.SessionLocal = None
sys.modules["app.core.db"] = fake_db
fake_models = types.ModuleType("app.models.db_models")
class Tenant: domain = "domain_col"
fake_models.Tenant = Tenant
sys.modules["app.models.db_models"] = fake_models

# --- valódi cors.py ---
spec = importlib.util.spec_from_file_location("cors_under_test", f"{ROOT}/app/core/cors.py")
cors = importlib.util.module_from_spec(spec); spec.loader.exec_module(cors)

# seed az allowlist cache (DB nélkül): a 14 tenant-domén-mintából 2 reprezentatív
cors._ALLOWSET = cors._build_allowset(["teslashop.hu", "www.codexpress.hu"])


class Headers(dict):
    def get(self, k, d=None): return super().get(k.lower(), d)
class _Url:
    def __init__(self, path): self.path = path
class Req:
    def __init__(self, method, origin=None, acrh=None, path="/chat"):
        self.method = method; self.headers = Headers(); self.url = _Url(path)
        if origin is not None: self.headers["origin"] = origin
        if acrh is not None: self.headers["access-control-request-headers"] = acrh

async def call_next(req):  # fake belső válasz
    return Response(200, headers={"content-type": "application/json"})


async def main():
    mw = cors.TenantCORSMiddleware(app=None)
    ok = []

    # --- _build_allowset: apex+www, www->bare ---
    s = cors._build_allowset(["teslashop.hu", "www.codexpress.hu", "  ", None])
    assert "https://teslashop.hu" in s and "https://www.teslashop.hu" in s
    assert "https://codexpress.hu" in s and "https://www.codexpress.hu" in s
    ok.append("_build_allowset: apex+www, www->bare, üres kihagyva")

    # --- TRIM: trailing slash, scheme prefix, path strip ---
    s_trim = cors._build_allowset(["www.fishingoutlet.hu/", "https://example.com/utvonal"])
    assert "https://fishingoutlet.hu" in s_trim and "https://www.fishingoutlet.hu" in s_trim, s_trim
    assert "https://example.com" in s_trim and "https://www.example.com" in s_trim, s_trim
    ok.append("_build_allowset trim: trailing slash + https:// scheme + path stripped")

    # --- _is_allowed ---
    a = cors._ALLOWSET
    assert cors._is_allowed("https://teslashop.hu", a)
    assert cors._is_allowed("https://www.teslashop.hu", a)
    assert cors._is_allowed("https://x.mysellvio.com", a)        # suffix
    assert cors._is_allowed("https://shop.unas.hu", a)           # suffix
    assert cors._is_allowed("https://a.b.myshoprenter.hu", a)    # suffix mély
    assert not cors._is_allowed("https://evil.example.com", a)
    assert not cors._is_allowed("http://teslashop.hu", a)        # http nem allowlistelt
    assert not cors._is_allowed("https://mysellvio.com", a)      # apex (nem aldomén) -> nem
    ok.append("_is_allowed: allowlist + platform-suffix; evil/http/apex block")

    # --- OPTIONS preflight, engedett (teslashop.hu) ---
    r = await mw.dispatch(Req("OPTIONS", "https://teslashop.hu"), call_next)
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == "https://teslashop.hu"
    assert r.headers["Access-Control-Allow-Methods"] == "POST, OPTIONS"
    assert r.headers["Access-Control-Allow-Headers"] == "content-type"   # default
    assert r.headers["Access-Control-Max-Age"] == "600"
    assert r.headers["Vary"] == "Origin"
    ok.append("OPTIONS teslashop.hu -> 200 + ACAO + Methods/Headers/Max-Age/Vary")

    # --- OPTIONS preflight echo-zza a kért headert ---
    r = await mw.dispatch(Req("OPTIONS", "https://teslashop.hu", acrh="content-type, x-foo"), call_next)
    assert r.headers["Access-Control-Allow-Headers"] == "content-type, x-foo"
    ok.append("OPTIONS visszaadja a kért Allow-Headers-t")

    # --- OPTIONS platform-suffix origin reflektálva ---
    r = await mw.dispatch(Req("OPTIONS", "https://x.mysellvio.com"), call_next)
    assert r.headers.get("Access-Control-Allow-Origin") == "https://x.mysellvio.com"
    ok.append("OPTIONS x.mysellvio.com -> ACAO reflektálva")

    # --- OPTIONS nem engedett -> 200, NINCS ACAO ---
    r = await mw.dispatch(Req("OPTIONS", "https://evil.example.com"), call_next)
    assert r.status_code == 200 and "Access-Control-Allow-Origin" not in r.headers
    ok.append("OPTIONS evil.example.com -> 200, NINCS ACAO")

    # --- tényleges POST engedett -> reflektál ---
    r = await mw.dispatch(Req("POST", "https://teslashop.hu"), call_next)
    assert r.headers["Access-Control-Allow-Origin"] == "https://teslashop.hu"
    assert r.headers["Vary"] == "Origin"
    ok.append("POST teslashop.hu -> ACAO + Vary a valós válaszon")

    # --- tényleges POST nem engedett -> nincs ACAO ---
    r = await mw.dispatch(Req("POST", "https://evil.example.com"), call_next)
    assert "Access-Control-Allow-Origin" not in r.headers
    ok.append("POST evil.example.com -> nincs ACAO")

    # --- nincs Origin -> nincs ACAO ---
    r = await mw.dispatch(Req("POST"), call_next)
    assert "Access-Control-Allow-Origin" not in r.headers
    ok.append("nincs Origin -> nincs ACAO")

    # --- /stats PUBLIC: idegen origin is reflektálva (a ?k= a titok) ---
    r = await mw.dispatch(Req("GET", "https://evil.example.com", path="/stats"), call_next)
    assert r.headers.get("Access-Control-Allow-Origin") == "https://evil.example.com"
    r = await mw.dispatch(Req("OPTIONS", "https://barhol.org", path="/stats"), call_next)
    assert r.headers.get("Access-Control-Allow-Origin") == "https://barhol.org"
    assert r.headers.get("Access-Control-Allow-Methods") == "GET, OPTIONS"
    ok.append("/stats PUBLIC -> bármely origin reflektálva (GET, OPTIONS)")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

"""Streamelő adapter/fetch teszt.
Futtatás: python tests/test_stream.py

A) Sellvio 2-menetes stream == teljes build (kereszt-oldal kategória-reláció feloldva).
B) Unas chunkolt stream == teljes build (kereszt-sku reláció feloldva).
C) Shoprenter stream: pass-1 full=0 (könnyű index), pass-2 full=1 (nehéz build); relációk feloldva.
D) A VALÓS shoprenter_list_products: ismert pageCount -> ablakonként PÁRHUZAMOS lapfetch (bounded),
   full paraméter átadva, minden lap lekérve, 429 -> retry.
"""
import asyncio
import base64
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])
for n in ("app", "app.core", "app.sync", "app.services"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


_load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
_load("app.sync.textutil", f"{ROOT}/app/sync/textutil.py")
_load("app.sync.models", f"{ROOT}/app/sync/models.py")
builders = _load("app.sync.builders", f"{ROOT}/app/sync/builders.py")

# fake httpx (adapters importálja; a webdoc ág használná — itt nem)
fh = types.ModuleType("httpx"); fh.AsyncClient = object; sys.modules["httpx"] = fh

# fake settings (adapters get_settings -> SR concurrency)
fs = types.ModuleType("app.core.settings")
fs.get_settings = lambda: types.SimpleNamespace(sync_shoprenter_concurrency=2, sync_include_inactive=False)
sys.modules["app.core.settings"] = fs

# fake platform_api (az adapters ezt hívja)
PAGES = {"sellvio": [], "unas_csv": "", "sr0": [], "sr1": [], "sr_calls": []}
fpa = types.ModuleType("app.services.platform_api")
async def _sellvio_pages(base, cid, sec):
    for pg in PAGES["sellvio"]:
        yield pg
async def _unas_csv(key):
    return PAGES["unas_csv"]
async def _sr_pages(api_base, cid, sec, *, full=1, concurrency=4):
    PAGES["sr_calls"].append(full)
    for pg in (PAGES["sr0"] if full == 0 else PAGES["sr1"]):
        yield pg
fpa.sellvio_list_products = _sellvio_pages
fpa.unas_export_csv = _unas_csv
fpa.shoprenter_list_products = _sr_pages
fpa.woo_list_products = None
sys.modules["app.services.platform_api"] = fpa

adapters = _load("app.sync.adapters", f"{ROOT}/app/sync/adapters.py")


class T:
    def __init__(self, platform):
        self.client_id = "c"; self.platform = platform; self.api_base = "https://x"
        self.api_client_id = "i"; self.api_client_secret = "s"; self.public_url = "https://shop.hu/"


async def _collect(stream):
    return [(sp.text, sp.related_similar, sp.related_additional, sp.content_hash) async for sp in stream]


def _sr_desc(name):
    return [{"id": base64.b64encode(b"product_description-language_id=1").decode(),
             "name": name, "shortDescription": "", "description": "", "parameters": ""}]


async def main():
    ok = []

    # === A) Sellvio kereszt-oldal ===
    p1 = {"id": "1", "name": "Alpha", "code": "A", "pretty_url": "https://shop.hu/a", "is_visible": True,
          "categories": {"10": {"name": "Kat"}}, "price": {"brutto_price": 100}}
    p2 = {"id": "2", "name": "Beta", "code": "B", "pretty_url": "https://shop.hu/b", "is_visible": True,
          "categories": {"10": {"name": "Kat"}}, "price": {"brutto_price": 200}}
    PAGES["sellvio"] = [[p1], [p2]]
    streamed = await _collect(adapters.stream_sellvio(T("sellvio")))
    full = [(s.text, s.related_similar, s.related_additional, s.content_hash) for s in builders.build_sellvio([p1, p2], "c")]
    assert streamed == full
    assert streamed[0][1] == "Beta — https://shop.hu/b" and streamed[1][1] == "Alpha — https://shop.hu/a"
    ok.append("A) Sellvio 2-menetes stream == teljes build (kereszt-oldal reláció)")

    # === B) Unas kereszt-sku ===
    csv = (
        "Cikkszám;Termék Név;Bruttó Ár;Kategória;Rövid Leírás;Tulajdonságok;Termék link;Raktárkészlet;"
        "Kiegészítő Termékek;Hasonló Termékek;Gyártó\n"
        "S1;Egy;100;;;;https://u/1;3;S2;;M\nS2;Kettő;200;;;;https://u/2;5;;S1;M\n"
    )
    PAGES["unas_csv"] = csv
    streamed_u = await _collect(adapters.stream_unas(T("unas")))
    full_u = [(s.text, s.related_similar, s.related_additional, s.content_hash) for s in builders.build_unas(csv, "c", "")]
    assert streamed_u == full_u
    assert streamed_u[0][2] == "Kettő — https://u/2" and streamed_u[1][1] == "Egy — https://u/1"
    ok.append("B) Unas chunkolt stream == teljes build (kereszt-sku reláció)")

    # === C) Shoprenter: full=0 index / full=1 build + reláció ===
    segB = base64.b64encode(b"product-product_id=2").decode()
    A0 = {"innerId": "1", "productDescriptions": _sr_desc("Alpha"), "urlAliases": [{"urlAlias": "a"}]}
    B0 = {"innerId": "2", "productDescriptions": _sr_desc("Beta"), "urlAliases": [{"urlAlias": "b"}]}
    A1 = {**A0, "productPrices": [{"gross": 100}], "stock1": "5", "orderable": "1", "status": "1", "sku": "A",
          "productRelatedProductRelations": [{"relatedProduct": {"href": "https://x/products/" + segB}}]}
    B1 = {**B0, "productPrices": [{"gross": 200}], "stock1": "3", "orderable": "1", "status": "1", "sku": "B"}
    PAGES["sr0"], PAGES["sr1"], PAGES["sr_calls"] = [[A0], [B0]], [[A1], [B1]], []
    streamed_sr = await _collect(adapters.stream_shoprenter(T("shoprenter")))
    ref_sr = [(s.text, s.related_similar, s.related_additional, s.content_hash)
              for s in builders.build_shoprenter([A1, B1], "c", "https://shop.hu/")]
    assert PAGES["sr_calls"] == [0, 1], PAGES["sr_calls"]     # pass-1 full=0, pass-2 full=1
    assert streamed_sr == ref_sr, f"\n stream={streamed_sr}\n ref={ref_sr}"
    assert streamed_sr[0][1] == "Beta — https://shop.hu/b"    # A ajánlja B-t (full=0 index-ből feloldva)
    ok.append("C) Shoprenter: pass-1 full=0 index / pass-2 full=1 build; reláció full=0-ból feloldva")

    # === D) valós shoprenter_list_products: párhuzamos ablak + full átadás + minden lap + 429 retry ===
    real_pa = _load("app.services.platform_api_real", f"{ROOT}/app/services/platform_api.py")

    class _Resp:
        def __init__(self, status=200, body=None, json_ok=True):
            self.status_code = status; self._b = body or {}
            self.headers = {"content-type": "application/json" if json_ok else "text/html"}
            self.content = (b'{"x":1}' if json_ok else b"<html>oops</html>")
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")
        def json(self): return self._b
    class _Client:
        inflight = 0; peak = 0; got = []; hit429 = {"0": 0}
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **k): return _Resp(200, {"access_token": "tok"})
        async def get(self, url, params=None, headers=None, **k):
            page = params["page"]
            if page == 0 and _Client.hit429["0"] == 0:      # egyszer 429 az első lapra -> retry
                _Client.hit429["0"] = 1
                return _Resp(429)
            _Client.inflight += 1
            _Client.peak = max(_Client.peak, _Client.inflight)
            await asyncio.sleep(0.01)
            _Client.inflight -= 1
            _Client.got.append((params["full"], page))
            if page < 3:
                return _Resp(200, {"items": [{"innerId": str(page)}], "pageCount": 3})
            return _Resp(200, {"items": [], "pageCount": 3})
    # a valós modul httpx-ét cseréljük a _Client-re, az asyncio-t shimre (gyors backoff-sleep, valós gather)
    real_pa.httpx.AsyncClient = _Client
    real_pa.asyncio = types.SimpleNamespace(sleep=lambda s: asyncio.sleep(0), gather=asyncio.gather)
    pages_got = []
    async for pg in real_pa.shoprenter_list_products("https://x", "i", "s", full=1, concurrency=2):
        pages_got.append(pg)
    assert {p for _, p in _Client.got} == {0, 1, 2}          # minden lap lekérve
    assert all(f == 1 for f, _ in _Client.got)               # full=1 átadva
    assert _Client.peak == 2                                  # ablak=2 -> 2 párhuzamos in-flight
    assert _Client.hit429["0"] == 1                          # a 429 retry lefutott (nem dobott)
    assert sum(len(pg) for pg in pages_got) == 3
    ok.append("D) valós SR fetch: párhuzamos ablak (peak=2), full átadva, minden lap, 429->retry")

    # === E) nem-JSON oldal -> retry + end-of-pages (üres), a stream NEM dob, a jó oldalak jönnek ===
    class _ClientE:
        tries1 = 0
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **k): return _Resp(200, {"access_token": "tok"})
        async def get(self, url, params=None, headers=None, **k):
            page = params["page"]
            if page == 1:                                    # 1. lap: TARTÓSAN nem-JSON (text/html)
                _ClientE.tries1 += 1
                return _Resp(200, {}, json_ok=False)
            if page < 3:
                return _Resp(200, {"items": [{"innerId": str(page)}], "pageCount": 3})
            return _Resp(200, {"items": []}, )
    real_pa.httpx.AsyncClient = _ClientE
    pages_e = []
    async for pg in real_pa.shoprenter_list_products("https://x", "i", "s", full=1, concurrency=3):
        pages_e.append(pg)                                   # NEM dob -> a stream lefut a végéig
    inner = sorted(it["innerId"] for pg in pages_e for it in pg)
    assert inner == ["0", "2"]                               # a jó oldalak (0,2) jönnek; az 1. kiesik
    assert _ClientE.tries1 == 4                              # a nem-JSON oldalt 4x retry-zte, majd üres
    ok.append("E) nem-JSON oldal -> 4x retry majd üres (end-of-pages); a stream nem dob")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

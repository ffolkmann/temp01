"""Streamelő adapter teszt — a lapozott 2-menetes (index+build) stream a lap-határokon ÁT is
byte-egyező a teljes-lista build-del (relációk feloldva), és az egy-blobos (unas) chunkolt stream is.
Futtatás: python tests/test_stream.py

Ez a memória-korlátos átalakítás elfogadási bizonyítéka: a stream ugyanazt adja, mint a régi
egészben-build, csak oldalanként/chunkonként (nem gyűjti listába a teljes katalógust).
"""
import asyncio
import importlib.util
import sys
import types

ROOT = "/home/folkm/chatbot"
for n in ("app", "app.sync", "app.services"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


# valós builders
_load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
_load("app.sync.textutil", f"{ROOT}/app/sync/textutil.py")
_load("app.sync.models", f"{ROOT}/app/sync/models.py")
builders = _load("app.sync.builders", f"{ROOT}/app/sync/builders.py")

# fake httpx (az adapters importálja; a sellvio/unas ág nem használja — csak webdoc)
sys.modules["httpx"] = types.ModuleType("httpx")
sys.modules["httpx"].AsyncClient = object

# fake platform_api: sellvio_list_products async generátor (2 oldal); unas_export_csv
PAGES = {"sellvio": []}
fpa = types.ModuleType("app.services.platform_api")
async def _sellvio_pages(base, cid, sec):
    for pg in PAGES["sellvio"]:
        yield pg
fpa.sellvio_list_products = _sellvio_pages
fpa.woo_list_products = None
fpa.shoprenter_list_products = None
async def _unas_csv(key): return PAGES.get("unas_csv", "")
fpa.unas_export_csv = _unas_csv
sys.modules["app.services.platform_api"] = fpa

adapters = _load("app.sync.adapters", f"{ROOT}/app/sync/adapters.py")


class T:
    def __init__(self, platform):
        self.client_id = "c"; self.platform = platform; self.api_base = "https://x"
        self.api_client_id = "i"; self.api_client_secret = "s"; self.public_url = "https://shop.hu/"


async def _collect(stream):
    return [(sp.text, sp.related_similar, sp.related_additional, sp.content_hash) async for sp in stream]


async def main():
    ok = []

    # === Sellvio: 2 oldal, KERESZT-oldal kategória-reláció (A az 1. oldalon, B a 2.-on, közös kat) ===
    p1 = {"id": "1", "name": "Alpha", "code": "A", "pretty_url": "https://shop.hu/a", "is_visible": True,
          "categories": {"10": {"name": "Kat"}}, "price": {"brutto_price": 100}}
    p2 = {"id": "2", "name": "Beta", "code": "B", "pretty_url": "https://shop.hu/b", "is_visible": True,
          "categories": {"10": {"name": "Kat"}}, "price": {"brutto_price": 200}}
    PAGES["sellvio"] = [[p1], [p2]]                     # két különálló oldal
    streamed = await _collect(adapters.stream_sellvio(T("sellvio")))
    full = [(sp.text, sp.related_similar, sp.related_additional, sp.content_hash)
            for sp in builders.build_sellvio([p1, p2], "c")]
    assert streamed == full, f"\n stream={streamed}\n full={full}"
    # és a kereszt-oldal reláció TÉNYLEG feloldva (A ajánlja B-t és fordítva)
    assert streamed[0][1] == "Beta — https://shop.hu/b" and streamed[1][1] == "Alpha — https://shop.hu/a"
    ok.append("Sellvio 2-menetes stream == teljes build (kereszt-oldal kategória-reláció feloldva)")

    # === Unas: egy CSV, relációk kereszt-chunk (a builder az egész indexet látja) ===
    csv = (
        "Cikkszám;Termék Név;Bruttó Ár;Kategória;Rövid Leírás;Tulajdonságok;Termék link;Raktárkészlet;"
        "Kiegészítő Termékek;Hasonló Termékek;Gyártó\n"
        "S1;Egy;100;;;;https://u/1;3;S2;;M\n"       # S1 kiegészítője S2
        "S2;Kettő;200;;;;https://u/2;5;;S1;M\n"       # S2 hasonlója S1
    )
    PAGES["unas_csv"] = csv
    streamed_u = await _collect(adapters.stream_unas(T("unas")))
    full_u = [(sp.text, sp.related_similar, sp.related_additional, sp.content_hash)
              for sp in builders.build_unas(csv, "c", "")]
    assert streamed_u == full_u, f"\n stream={streamed_u}\n full={full_u}"
    assert streamed_u[0][2] == "Kettő — https://u/2"   # S1.related_additional -> S2 (kereszt-feloldás)
    assert streamed_u[1][1] == "Egy — https://u/1"      # S2.related_similar -> S1
    ok.append("Unas chunkolt stream == teljes build (kereszt-sku reláció feloldva)")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

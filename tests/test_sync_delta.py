"""Delta + idempotencia + completion-first teszt a (patchelt) engine-en — fake Qdrant STORE-ral.
Futtatás: python3 tests/test_sync_delta.py

Esetek:
  1) cold-start: 3 termék -> 3 embed + 3 pont a store-ban
  2) VÁLTOZATLAN re-run -> 0 embed (A BUG FIXE: nem embeddeli újra a ~46k terméket)
  3) 1 változott content_hash -> pontosan 1 embed
  4) idempotens: re-run után store=3, a pont-id-k determinisztikusak, nincs duplikáció
  5) completion-first: embed-hiba -> failed=2, DE a stream lefut és a purge megtörténik
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])
for n in ("app", "app.core", "app.sync", "app.services", "app.models"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


hashing = _load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
models = _load("app.sync.models", f"{ROOT}/app/sync/models.py")
SP = models.SourceProduct

_settings = types.SimpleNamespace(
    qdrant_sync_collection="cx_chatbot_v2", embed_dim=4, sync_embed_batch=2, sync_upsert_batch=200)
fs = types.ModuleType("app.core.settings")
fs.get_settings = lambda: _settings
sys.modules["app.core.settings"] = fs

EMBED = {"calls": [], "fail": 0}


async def _embed(texts):
    EMBED["calls"].append(len(texts))
    if EMBED["fail"] > 0:
        EMBED["fail"] -= 1
        raise RuntimeError("embed 429 — retry kimerült (szimulált)")
    return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


fe = types.ModuleType("app.core.embeddings")
fe.embed_texts = _embed
sys.modules["app.core.embeddings"] = fe

STORE: dict = {}                       # point_id -> point (a "Qdrant")
CAP = {"delete": []}


class FakeQ:
    def __init__(self, url=None, collection=None):
        pass

    async def ensure_collection(self, c, size, distance="Cosine"):
        pass

    async def scroll_products(self, c, cid, fields):
        return [{"id": k, "payload": {f: (v.get("payload") or {}).get(f, "") for f in fields}}
                for k, v in STORE.items()]

    async def upsert(self, c, points):
        for pt in points:
            STORE[str(pt["id"])] = pt

    async def set_payload_batch(self, c, ops):
        pass

    async def delete(self, c, ids):
        CAP["delete"].extend(str(i) for i in ids)
        for i in ids:
            STORE.pop(str(i), None)

    async def count_products(self, c, cid):
        return len(STORE)

    async def aclose(self):
        pass


fq = types.ModuleType("app.core.qdrant")
fq.QdrantClient = FakeQ
sys.modules["app.core.qdrant"] = fq

SRC = {"items": []}


async def _stream(tenant):
    for sp in SRC["items"]:
        yield sp


fa = types.ModuleType("app.sync.adapters")
fa.stream_products = _stream
fa.SUPPORTED_PLATFORMS = frozenset({"shoprenter", "sellvio"})
sys.modules["app.sync.adapters"] = fa

engine = _load("app.sync.engine", f"{ROOT}/app/sync/engine.py")


class T:
    client_id = "fishingoutlet"
    platform = "shoprenter"
    api_base = "https://x.hu"
    api_client_id = "1"
    api_client_secret = "s"


def prod(idk, ch="h1"):
    return SP(id_key=idk, sku=idk, name="N-" + idk, text="text-" + idk,
              content_hash=ch, filename="__shoprenter_products__")


def pid(idk):
    return hashing.point_id("fishingoutlet", idk)


def reset(items=None, fail=0, batch=2):
    STORE.clear()
    CAP.update(delete=[])
    EMBED.update(calls=[], fail=fail)
    SRC["items"] = items or []
    _settings.sync_embed_batch = batch


async def main():
    ok = []

    # 1) cold-start: üres store, 3 termék -> 3 embed (batch=2 -> hívások: [2,1]), 3 pont
    reset(items=[prod("A"), prod("B"), prod("C")])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 3 and sum(EMBED["calls"]) == 3 and EMBED["calls"] == [2, 1], (r, EMBED)
    assert len(STORE) == 3 and r["total"] == 3 and "failed" not in r and CAP["delete"] == []
    ok.append("1) cold-start: 3 embed ([2,1] batch), 3 pont a store-ban")

    # 2) VÁLTOZATLAN re-run -> 0 embed, 0 create-hívás (A BUG FIXE)
    EMBED["calls"].clear()
    r = await engine.sync_tenant(T())
    assert r["embed"] == 0 and EMBED["calls"] == [], (r, EMBED)
    assert len(STORE) == 3 and CAP["delete"] == [] and r["stale"] == 0
    ok.append("2) változatlan re-run: 0 embed (delta content_hash-re skippel) — A BUG FIXE")

    # 3) 1 változott content_hash -> pontosan 1 embed, a pont payloadja frissül
    EMBED["calls"].clear()
    SRC["items"] = [prod("A"), prod("B"), prod("C", ch="h2")]
    r = await engine.sync_tenant(T())
    assert r["embed"] == 1 and EMBED["calls"] == [1], (r, EMBED)
    assert STORE[pid("C")]["payload"]["content_hash"] == "h2" and len(STORE) == 3
    ok.append("3) 1 változott -> 1 embed, payload frissült")

    # 4) idempotens: újrafuttatás -> store marad 3, az id-k determinisztikusak, nincs dup
    EMBED["calls"].clear()
    r = await engine.sync_tenant(T())
    assert r["embed"] == 0 and len(STORE) == 3 and r["total"] == 3
    assert set(STORE.keys()) == {pid("A"), pid("B"), pid("C")}
    ok.append("4) idempotens: store=3, determinisztikus point-id-k, nincs duplikáció")

    # 5) completion-first: embed-hiba az egyetlen batchen -> failed=2, DE purge lefut
    #    - X már létezik RÉGI hash-sel (re-embed bukik -> a régi verzió MEGMARAD, mert seen-ben van)
    #    - S stale (nincs a forrásban) -> a purge TÖRLI (ez maradt ki eddig a crash miatt!)
    reset(items=[prod("X", ch="NEW"), prod("Y")], fail=1, batch=2)
    STORE[pid("X")] = {"id": pid("X"), "payload": {"content_hash": "OLD", "text": "regi-X"}}
    STORE[pid("S")] = {"id": pid("S"), "payload": {"content_hash": "hs"}}
    r = await engine.sync_tenant(T())
    assert "error" not in r, r
    assert r.get("failed") == 2 and r["embed"] == 0, r
    assert r["stale"] == 1 and CAP["delete"] == [pid("S")], (r, CAP)
    assert pid("X") in STORE and STORE[pid("X")]["payload"]["content_hash"] == "OLD"
    assert pid("Y") not in STORE and r["total"] == 1
    ok.append("5) completion-first: embed-hiba -> failed=2, a stream lefut, a purge megtörténik")

    for l in ok:
        print("OK ", l)
    print("\nALL GOOD")


asyncio.run(main())

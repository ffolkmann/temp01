"""Sync-motor teszt — fake qdrant/embeddings/adapters, valós hashing/models.
Futtatás: python tests/test_sync.py

Lefedi: determinisztikus point_id, content/ps hash, payload-kulcsok (chat-séma),
delta-döntések (új/változatlan/ps-csak/content-változott), stale mark-and-sweep,
fail-safe (fetch-hiba/üres -> skip, NINCS purge), dry-run.
"""
import asyncio
import importlib.util
import sys
import types

ROOT = "/home/folkm/chatbot"
for name in ("app", "app.core", "app.sync", "app.services", "app.models"):
    sys.modules.setdefault(name, types.ModuleType(name)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# valós (tiszta) modulok
hashing = _load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
models = _load("app.sync.models", f"{ROOT}/app/sync/models.py")
SourceProduct = models.SourceProduct

# fake settings
_settings = types.SimpleNamespace(
    qdrant_sync_collection="cx_chatbot_v2", embed_dim=4, sync_embed_batch=50, sync_upsert_batch=200)
fs = types.ModuleType("app.core.settings"); fs.get_settings = lambda: _settings
sys.modules["app.core.settings"] = fs

# fake embeddings
fe = types.ModuleType("app.core.embeddings")
async def _embed(texts): return [[0.1, 0.2, 0.3, 0.4] for _ in texts]
fe.embed_texts = _embed
sys.modules["app.core.embeddings"] = fe

# fake qdrant — minden hívást rögzít modul-szintű CAP-be
CAP = {"ensure": [], "upsert": [], "ps": [], "delete": [], "count": 0, "existing": []}
class FakeQ:
    def __init__(self, collection=None): self.collection = collection
    async def ensure_collection(self, c, size, distance="Cosine"): CAP["ensure"].append((c, size, distance))
    async def scroll_products(self, c, cid, fields): return list(CAP["existing"])
    async def upsert(self, c, points): CAP["upsert"].extend(points)
    async def set_payload_batch(self, c, ops): CAP["ps"].extend(ops)
    async def delete(self, c, ids): CAP["delete"].extend(ids)
    async def count_products(self, c, cid): return CAP["count"]
    async def aclose(self): pass
fq = types.ModuleType("app.core.qdrant"); fq.QdrantClient = FakeQ
sys.modules["app.core.qdrant"] = fq

# fake adapters — a PLATFORM_FETCHERS-t a teszt állítja
SOURCES = {"items": [], "fail": False}
async def _fetch(tenant):
    if SOURCES["fail"]:
        raise RuntimeError("fetch fail")
    return list(SOURCES["items"])
fa = types.ModuleType("app.sync.adapters"); fa.PLATFORM_FETCHERS = {"sellvio": _fetch}
sys.modules["app.sync.adapters"] = fa

# valós engine
engine = _load("app.sync.engine", f"{ROOT}/app/sync/engine.py")


class T:
    def __init__(self):
        self.client_id="teslashop"; self.platform="sellvio"; self.api_base="https://x.hu"
        self.api_client_id="1"; self.api_client_secret="s"

def reset(existing=None, items=None, raise_=False):
    CAP.update(ensure=[], upsert=[], ps=[], delete=[], count=len(items or []), existing=existing or [])
    SOURCES.update(items=items or [], fail=raise_)

def existing_point(client_id, p):
    """A meglévő pont payloadja egy SourceProduct-ból (azonos hash-számítással, mint az engine)."""
    return {"id": hashing.point_id(client_id, p.sku), "payload": {
        "sku": p.sku, "content_hash": models.compute_content_hash(p), "ps_hash": models.compute_ps_hash(p)}}


async def main():
    ok = []

    # --- pure: point_id determinizmus + hash ---
    a = hashing.point_id("teslashop", "TSL1", 0)
    assert a == hashing.point_id("teslashop", "TSL1", 0)               # determinisztikus
    assert a != hashing.point_id("teslashop", "TSL1", 1)              # chunk_idx számít
    assert len(a) == 36 and a.count("-") == 4                          # uuid
    assert hashing.fnv1a_32("abc") == hashing.fnv1a_32("abc")
    ok.append("point_id determinisztikus (uuid5) + fnv1a stabil")

    # --- payload tartalmazza a chat által olvasott kulcsokat ---
    p = SourceProduct(sku="TSL1", name="N", url="u", price="100", brand="B",
                      platform_id_field="sellvio_id", platform_id_value="777", available=True)
    pl = models.build_payload("teslashop", p, "__sellvio_products__", models.build_text(p),
                              models.compute_content_hash(p), models.compute_ps_hash(p))
    for k in ("client_id","type","sku","name","text","url","price","brand","content_hash",
              "ps_hash","filename","related_similar","related_additional","sellvio_id","available"):
        assert k in pl, k
    assert pl["type"] == "product" and pl["sellvio_id"] == "777"
    ok.append("payload: minden chat-olvasott kulcs + platform-id (sellvio_id) + available")

    # --- A) friss kollekció: minden termék embed+upsert ---
    p1 = SourceProduct(sku="A1", name="Alpha", price="100", url="a")
    p2 = SourceProduct(sku="A2", name="Beta", price="200", url="b")
    reset(existing=[], items=[p1, p2])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 2 and r["ps_update"] == 0 and r["stale"] == 0
    assert len(CAP["upsert"]) == 2 and CAP["delete"] == []
    assert all("vector" in pt and pt["payload"]["type"] == "product" for pt in CAP["upsert"])
    ok.append("A) friss: 2 embed+upsert, nincs ps/stale")

    # --- B) változatlan: skip (0 embed, 0 ps, 0 upsert) ---
    reset(existing=[existing_point("teslashop", p1), existing_point("teslashop", p2)], items=[p1, p2])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 0 and r["ps_update"] == 0 and r["stale"] == 0
    assert CAP["upsert"] == [] and CAP["ps"] == [] and CAP["delete"] == []
    ok.append("B) változatlan content+ps -> skip (nincs embed/ps/upsert)")

    # --- C) csak ár/készlet változott: set_payload, NINCS embed ---
    p1b = SourceProduct(sku="A1", name="Alpha", price="150", url="a")   # csak ár más
    reset(existing=[existing_point("teslashop", p1)], items=[p1b])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 0 and r["ps_update"] == 1
    assert CAP["upsert"] == [] and len(CAP["ps"]) == 1
    sub, pid = CAP["ps"][0]
    assert sub["price"] == "150" and "ps_hash" in sub and pid == hashing.point_id("teslashop", "A1")
    ok.append("C) csak ps változott -> set_payload (ár 150), nincs embed/upsert")

    # --- D) szemantika változott: re-embed + upsert ---
    p1c = SourceProduct(sku="A1", name="Alpha PRO", price="100", url="a")  # név más -> content_hash más
    reset(existing=[existing_point("teslashop", p1)], items=[p1c])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 1 and r["ps_update"] == 0 and len(CAP["upsert"]) == 1
    ok.append("D) content változott -> re-embed + upsert")

    # --- E) stale: forrásból eltűnt sku -> delete (mark-and-sweep) ---
    reset(existing=[existing_point("teslashop", p1), existing_point("teslashop", p2)], items=[p1])
    r = await engine.sync_tenant(T())
    assert r["stale"] == 1 and CAP["delete"] == [hashing.point_id("teslashop", "A2")]
    ok.append("E) stale: a forrásból hiányzó sku törölve")

    # --- F) dry-run: számol, de SEMMIT nem ír ---
    reset(existing=[], items=[p1, p2])
    r = await engine.sync_tenant(T(), dry_run=True)
    assert r["dry_run"] and r["embed"] == 2
    assert CAP["upsert"] == [] and CAP["ps"] == [] and CAP["delete"] == [] and CAP["ensure"] == []
    ok.append("F) dry-run: count ok, nincs upsert/ps/delete/ensure")

    # --- G) fetch-hiba -> skip, NINCS purge ---
    reset(existing=[existing_point("teslashop", p1)], items=[], raise_=True)
    r = await engine.sync_tenant(T())
    assert "error" in r and CAP["delete"] == [] and CAP["upsert"] == []
    ok.append("G) fetch-hiba -> error skip, NINCS purge/upsert")

    # --- H) üres forrás -> skip, NINCS purge ---
    reset(existing=[existing_point("teslashop", p1)], items=[])
    r = await engine.sync_tenant(T())
    assert r.get("skipped") and CAP["delete"] == []
    ok.append("H) üres forrás -> skip, NINCS purge")

    # --- I) nincs cred / nem portolt platform -> skip ---
    t = T(); t.api_base = ""
    reset(existing=[], items=[p1])
    r = await engine.sync_tenant(t)
    assert r.get("skipped") == "nincs cred"
    t2 = T(); t2.platform = "magento"
    r = await engine.sync_tenant(t2)
    assert "nincs portolva" in r.get("skipped", "")
    ok.append("I) nincs cred / ismeretlen platform -> skip")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

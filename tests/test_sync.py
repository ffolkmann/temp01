"""Sync-motor teszt — fake qdrant/embeddings/adapters, valós hashing/models.
Futtatás: python tests/test_sync.py

Content-only delta (point_id-re kulcsolva): új/változott -> embed+upsert, változatlan -> skip,
forrásból eltűnt -> stale delete. Fail-safe (fetch-hiba/üres -> skip, NINCS purge), dry-run.
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


hashing = _load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
models = _load("app.sync.models", f"{ROOT}/app/sync/models.py")
SP = models.SourceProduct

_settings = types.SimpleNamespace(
    qdrant_sync_collection="cx_chatbot_v2", embed_dim=4, sync_embed_batch=50, sync_upsert_batch=200)
fs = types.ModuleType("app.core.settings"); fs.get_settings = lambda: _settings
sys.modules["app.core.settings"] = fs

fe = types.ModuleType("app.core.embeddings")
async def _embed(texts): return [[0.1, 0.2, 0.3, 0.4] for _ in texts]
fe.embed_texts = _embed
sys.modules["app.core.embeddings"] = fe

CAP = {"ensure": [], "upsert": [], "delete": [], "ps": [], "count": 0, "existing": []}
class FakeQ:
    def __init__(self, collection=None): self.collection = collection
    async def ensure_collection(self, c, size, distance="Cosine"): CAP["ensure"].append((c, size))
    async def scroll_products(self, c, cid, fields): return list(CAP["existing"])
    async def upsert(self, c, points): CAP["upsert"].extend(points)
    async def set_payload_batch(self, c, ops): CAP["ps"].extend(ops)
    async def delete(self, c, ids): CAP["delete"].extend(ids)
    async def count_products(self, c, cid): return CAP["count"]
    async def aclose(self): pass
fq = types.ModuleType("app.core.qdrant"); fq.QdrantClient = FakeQ
sys.modules["app.core.qdrant"] = fq

SOURCES = {"items": [], "fail": False}
async def _fetch(tenant):
    if SOURCES["fail"]:
        raise RuntimeError("fetch fail")
    return list(SOURCES["items"])
fa = types.ModuleType("app.sync.adapters"); fa.PLATFORM_FETCHERS = {"sellvio": _fetch}
sys.modules["app.sync.adapters"] = fa

engine = _load("app.sync.engine", f"{ROOT}/app/sync/engine.py")


class T:
    def __init__(self):
        self.client_id="teslashop"; self.platform="sellvio"; self.api_base="https://x.hu"
        self.api_client_id="1"; self.api_client_secret="s"

def reset(existing=None, items=None, fail=False):
    CAP.update(ensure=[], upsert=[], delete=[], ps=[], count=len(items or []), existing=existing or [])
    SOURCES.update(items=items or [], fail=fail)

def prod(id_key, name="N", ch="h1"):
    return SP(id_key=id_key, sku=id_key, name=name, text=f"text-{id_key}", content_hash=ch,
             platform_id_field="sellvio_id", platform_id_value=id_key, filename="__sellvio_products__")

def existing_pt(client_id, id_key, ch):
    return {"id": hashing.point_id(client_id, id_key), "payload": {"content_hash": ch}}


async def main():
    ok = []

    # --- pont-id determinizmus + payload kulcsok ---
    a = hashing.point_id("teslashop", "K1")
    assert a == hashing.point_id("teslashop", "K1") and len(a) == 36
    pl = models.build_payload("teslashop", prod("K1"))
    for k in ("client_id","filename","type","text","name","price","url","sku","brand",
              "related_similar","related_additional","content_hash","sellvio_id"):
        assert k in pl, k
    assert pl["type"] == "product" and pl["sellvio_id"] == "K1" and "stock" not in pl
    ok.append("point_id determinisztikus + payload kulcsok (sellvio_id, nincs stock)")

    # --- A) friss: minden embed+upsert ---
    reset(existing=[], items=[prod("A1"), prod("A2")])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 2 and r["stale"] == 0 and len(CAP["upsert"]) == 2 and CAP["delete"] == []
    assert all("vector" in pt and pt["payload"]["type"] == "product" for pt in CAP["upsert"])
    ok.append("A) friss: 2 embed+upsert")

    # --- B) változatlan content_hash -> skip ---
    reset(existing=[existing_pt("teslashop", "A1", "h1"), existing_pt("teslashop", "A2", "h1")],
          items=[prod("A1", ch="h1"), prod("A2", ch="h1")])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 0 and r["stale"] == 0 and CAP["upsert"] == [] and CAP["delete"] == []
    ok.append("B) változatlan content_hash -> skip (nincs embed/upsert)")

    # --- C) content_hash változott -> re-embed+upsert ---
    reset(existing=[existing_pt("teslashop", "A1", "OLD")], items=[prod("A1", ch="NEW")])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 1 and len(CAP["upsert"]) == 1
    ok.append("C) content változott -> re-embed+upsert")

    # --- D) stale: forrásból eltűnt -> delete ---
    reset(existing=[existing_pt("teslashop", "A1", "h1"), existing_pt("teslashop", "A2", "h1")],
          items=[prod("A1", ch="h1")])
    r = await engine.sync_tenant(T())
    assert r["stale"] == 1 and CAP["delete"] == [hashing.point_id("teslashop", "A2")]
    ok.append("D) stale: eltűnt id törölve")

    # --- E) dedup: két forrás azonos id_key -> egy pont ---
    reset(existing=[], items=[prod("A1", ch="h1"), prod("A1", ch="h1")])
    r = await engine.sync_tenant(T())
    assert r["embed"] == 1 and len(CAP["upsert"]) == 1
    ok.append("E) dedup: azonos id_key -> egy pont")

    # --- F) dry-run: semmit nem ír ---
    reset(existing=[], items=[prod("A1"), prod("A2")])
    r = await engine.sync_tenant(T(), dry_run=True)
    assert r["dry_run"] and r["embed"] == 2
    assert CAP["upsert"] == [] and CAP["delete"] == [] and CAP["ensure"] == []
    ok.append("F) dry-run: nincs ensure/upsert/delete")

    # --- G) fetch-hiba -> skip, NINCS purge ---
    reset(existing=[existing_pt("teslashop", "A1", "h1")], items=[], fail=True)
    r = await engine.sync_tenant(T())
    assert "error" in r and CAP["delete"] == [] and CAP["upsert"] == []
    ok.append("G) fetch-hiba -> skip, NINCS purge")

    # --- H) üres forrás -> skip, NINCS purge ---
    reset(existing=[existing_pt("teslashop", "A1", "h1")], items=[])
    r = await engine.sync_tenant(T())
    assert r.get("skipped") and CAP["delete"] == []
    ok.append("H) üres forrás -> skip, NINCS purge")

    # --- I) nincs cred / ismeretlen platform -> skip ---
    t = T(); t.api_base = ""
    reset(existing=[], items=[prod("A1")])
    assert (await engine.sync_tenant(t)).get("skipped") == "nincs cred"
    t2 = T(); t2.platform = "magento"
    assert "nincs portolva" in (await engine.sync_tenant(t2)).get("skipped", "")
    ok.append("I) nincs cred / ismeretlen platform -> skip")

    # --- J) _has_creds platformfüggő szabályok ---
    def tn(platform, base="", secret="", cid=""):
        x = T(); x.platform = platform; x.api_base = base; x.api_client_secret = secret; x.api_client_id = cid
        return x
    assert engine._has_creds(tn("sellvio", base="b", secret="s"))
    assert not engine._has_creds(tn("sellvio", base="", secret="s"))     # base kell
    assert not engine._has_creds(tn("sellvio", base="b"))                # secret/cid kell
    assert engine._has_creds(tn("unas", base="", secret="k"))            # Unas: base NEM kell
    assert not engine._has_creds(tn("unas", base="b"))                   # de ApiKey kell
    assert engine._has_creds(tn("webdoc", base="https://feed"))          # Webdoc: csak feed URL
    assert not engine._has_creds(tn("webdoc", base="", secret="x"))      # base kell
    ok.append("J) _has_creds: unas=ApiKey, webdoc=api_base, egyéb=base+key")

    # === --pricestock (Build PS / PS Delta / Set Payload, embed nélkül) ===
    def wprod(id_key, ps, available=True, price="100"):
        return SP(id_key=id_key, sku=id_key, name="N", text=f"text-{id_key}-{ps}", content_hash="c",
                  price=price, available=available, ps_hash_str=ps,
                  platform_id_field="webdoc_id", platform_id_value=id_key, filename="__webdoc_products__")
    def existing_ps(client_id, id_key, ps):
        return {"id": hashing.point_id(client_id, id_key), "payload": {"ps_hash": ps}}

    def wt():  # webdoc tenant
        x = T(); x.platform = "webdoc"; return x
    fa.PLATFORM_FETCHERS["webdoc"] = _fetch   # a fake fetchert hasznaljuk webdoc-ra is

    # K) ps változott -> set_payload {price/available/text/ps_hash}, NINCS embed/upsert/delete/ensure
    reset(existing=[existing_ps("teslashop", "W1", "OLD")], items=[wprod("W1", "NEW", available=False, price="990")])
    r = await engine.pricestock_tenant(wt())
    assert r["ps_update"] == 1 and CAP["upsert"] == [] and CAP["delete"] == [] and CAP["ensure"] == []
    sub, pid = CAP["ps"][0]
    assert pid == hashing.point_id("teslashop", "W1")
    assert sub == {"price": "990", "text": "text-W1-NEW", "ps_hash": "NEW", "available": False}
    ok.append("K) pricestock: ps változott -> set_payload {price/available/text/ps_hash}, nincs embed")

    # L) ps változatlan -> skip
    reset(existing=[existing_ps("teslashop", "W1", "SAME")], items=[wprod("W1", "SAME")])
    r = await engine.pricestock_tenant(wt())
    assert r["ps_update"] == 0 and CAP["ps"] == []
    ok.append("L) pricestock: ps változatlan -> skip")

    # M) új termék (nincs a kollekcióban) -> NEM hoz létre (a teljes sync embeddeli)
    reset(existing=[], items=[wprod("W2", "X")])
    r = await engine.pricestock_tenant(wt())
    assert r["ps_update"] == 0 and CAP["ps"] == [] and CAP["upsert"] == []
    ok.append("M) pricestock: új termék -> nem hoz létre")

    # N) dry-run -> nem ír
    reset(existing=[existing_ps("teslashop", "W1", "OLD")], items=[wprod("W1", "NEW")])
    r = await engine.pricestock_tenant(wt(), dry_run=True)
    assert r["dry_run"] and r["ps_update"] == 1 and CAP["ps"] == []
    ok.append("N) pricestock dry-run: számol, nem ír")

    # O) fetch-hiba -> skip
    reset(existing=[existing_ps("teslashop", "W1", "OLD")], items=[], fail=True)
    r = await engine.pricestock_tenant(wt())
    assert "error" in r and CAP["ps"] == []
    ok.append("O) pricestock fetch-hiba -> skip")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

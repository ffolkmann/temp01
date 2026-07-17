"""Sync-motor: STREAMELŐ forrás -> embedding -> upsert a v2 Qdrant kollekcióba, delta + stale purge.

Memória-korlátos: a forrás oldalanként/chunkonként érkezik (app.sync.adapters.stream_products),
embed-batch-enként (≤sync_embed_batch) upsertelünk és elengedünk. Memóriában csak KÖNNYŰ halmazok
maradnak: a meglévő pontok content_hash-e (delta) + a látott point-id-k (stale-purge). A purge az
összes oldal feldolgozása UTÁN fut, a begyűjtött id-halmaz alapján.

Paritás: delta content_hash-re (változatlan -> nincs re-embed); mark-and-sweep purge; determinisztikus
point_id -> idempotens upsert. BIZTONSÁG: kizárólag a settings.qdrant_sync_collection-be írunk.
Hiba (fetch/stream) VAGY üres forrás -> tenant skip, NINCS purge.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.embeddings import embed_texts
from app.core.qdrant import QdrantClient
from app.core.settings import get_settings
from app.sync.adapters import SUPPORTED_PLATFORMS, stream_products
from app.sync.hashing import point_id
from app.sync.models import build_payload

if TYPE_CHECKING:
    from app.models.db_models import Tenant

logger = logging.getLogger("cx.sync")


def _has_creds(tenant: "Tenant") -> bool:
    """Platformfüggő cred-követelmény:
      - unas:   csak ApiKey (api_client_secret VAGY _id) — a base hardcoded api.unas.eu, api_base nem kell.
      - webdoc: csak api_base (publikus feed URL; nincs auth).
      - egyéb (Sellvio/Shoprenter/Woo): api_base ÉS (api_client_secret VAGY _id).
    """
    platform = str(tenant.platform or "").strip().lower()
    base = bool(str(tenant.api_base or "").strip())
    secret_or_id = bool(
        str(tenant.api_client_secret or "").strip() or str(tenant.api_client_id or "").strip()
    )
    if platform == "unas":
        return secret_or_id
    if platform == "webdoc":
        return base
    return base and secret_or_id


async def _existing_hashes(q, coll, client_id, field) -> dict[str, str]:
    """point_id -> <field> (content_hash vagy ps_hash). Új/hiányzó kollekció -> üres."""
    try:
        rows = await q.scroll_products(coll, client_id, [field])
    except Exception:  # noqa: BLE001 — kollekció még nincs / átmeneti -> üres bázis
        logger.warning("SYNC[%s] scroll sikertelen (új kollekció?) — üres bázis", client_id)
        return {}
    return {str(pt.get("id")): str((pt.get("payload") or {}).get(field) or "") for pt in rows}


async def sync_tenant(tenant: "Tenant", *, dry_run: bool = False) -> dict:
    """Egy tenant teljes (streamelő) szinkronja a v2 kollekcióba."""
    client_id = tenant.client_id
    platform = str(tenant.platform or "").strip().lower()
    res: dict = {"client_id": client_id, "platform": platform}
    if platform not in SUPPORTED_PLATFORMS:
        res["skipped"] = f"platform '{platform}' nincs portolva"
        return res
    if not _has_creds(tenant):
        res["skipped"] = "nincs cred"
        return res

    settings = get_settings()
    coll = settings.qdrant_sync_collection
    eb, ub = settings.sync_embed_batch, settings.sync_upsert_batch
    q = QdrantClient(collection=coll)
    try:
        ex = await _existing_hashes(q, coll, client_id, "content_hash")
        ex_ps = await _existing_hashes(q, coll, client_id, "ps_hash")

        seen: set[str] = set()
        buf: list[tuple[str, str, dict]] = []   # (text, point_id, payload) — ≤ eb, aztán flush+ürít
        ps_ops: list[tuple[dict, str]] = []     # ár/készlet payload-merge (m22, EMBED nélkül)
        embedded = 0
        failed = 0
        ps_updated = 0
        ensured = False

        async def flush() -> None:
            nonlocal embedded, failed, ensured
            if not buf:
                return
            if dry_run:
                embedded += len(buf)
                buf.clear()
                return
            # completion-first: egy batch embed/upsert hibája NE törje meg a streamet (a purge fusson).
            # A batch termékei már a `seen`-ben vannak -> a purge NEM törli őket (megmarad a korábbi verzió).
            try:
                if not ensured:
                    await q.ensure_collection(coll, settings.embed_dim, "Cosine")
                    ensured = True
                vectors = await embed_texts([t for t, _, _ in buf])
                points = [{"id": pid, "vector": vec, "payload": pl}
                          for (t, pid, pl), vec in zip(buf, vectors)]
                for j in range(0, len(points), ub):
                    await q.upsert(coll, points[j:j + ub])
                embedded += len(buf)
            except Exception:  # noqa: BLE001 — batch-hiba (embed retry kimerült / Qdrant) -> kihagyás, tovább
                logger.exception("SYNC[%s] embed/upsert batch hiba (%d db) -> kihagyva", client_id, len(buf))
                failed += len(buf)
            buf.clear()

        async def ps_flush() -> None:
            # fail-safe: a set_payload hiba NE törje a streamet/purge-öt
            nonlocal ps_updated
            if not ps_ops:
                return
            if dry_run:
                ps_updated += len(ps_ops)
                ps_ops.clear()
                return
            try:
                await q.set_payload_batch(coll, ps_ops)
                ps_updated += len(ps_ops)
            except Exception:  # noqa: BLE001
                logger.exception("SYNC[%s] ps set_payload batch hiba (%d db) -> kihagyva",
                                 client_id, len(ps_ops))
            ps_ops.clear()

        src_count = 0
        try:
            async for p in stream_products(tenant):
                src_count += 1
                if not p.id_key:
                    continue
                pid = point_id(client_id, p.id_key)
                if pid in seen:
                    continue
                seen.add(pid)
                if p.content_hash and ex.get(pid) == p.content_hash:
                    # tartalom változatlan -> nincs újra-embed; DE ár/készlet-delta ->
                    # payload-merge (m22): price/text/ps_hash frissül embedding nélkül
                    if p.ps_hash_str and ex_ps.get(pid) != p.ps_hash_str:
                        ps_ops.append((_ps_payload(p), pid))
                        if len(ps_ops) >= ub:
                            await ps_flush()
                    continue
                buf.append((p.text, pid, build_payload(client_id, p)))
                if len(buf) >= eb:
                    await flush()
            await flush()
            await ps_flush()
        except Exception as e:  # noqa: BLE001 — stream/fetch hiba -> skip, NINCS purge
            logger.exception("SYNC[%s] stream hiba", client_id)
            res["error"] = f"stream: {e}"
            return res

        if src_count == 0:
            res["skipped"] = "0 forrás termék — purge kihagyva"
            return res

        stale_ids = [pid for pid in ex if pid not in seen]
        res.update(collection=coll, source=src_count, embed=embedded, stale=len(stale_ids))
        if ps_updated:
            res["ps_update"] = ps_updated
        if failed:
            res["failed"] = failed
        if dry_run:
            res["dry_run"] = True
            return res

        if stale_ids:
            await q.delete(coll, stale_ids)
        res["total"] = await q.count_products(coll, client_id)
        return res
    finally:
        await q.aclose()


def _ps_payload(p) -> dict:
    """A PriceStock Fast set_payload MERGE mezői: csak price/available/text/ps_hash (vektor érintetlen)."""
    payload = {"price": p.price, "text": p.text, "ps_hash": p.ps_hash_str}
    if p.available is not None:
        payload["available"] = p.available
    if p.stock_str != "":
        payload["stock"] = p.stock_str  # m58: SR/Unas stock a PS-merge-ben is (eddig kimaradt -> elavulhatott)
    return payload


async def pricestock_tenant(tenant: "Tenant", *, dry_run: bool = False) -> dict:
    """--pricestock (streamelő): Build PS / PS Delta / Set Payload tükre — EMBED NÉLKÜL.

    A forrásból újraépíti a ps_hash/price/available/text mezőket, és CSAK a már létező pontok közül
    a változott ps_hash-úakon frissít (set_payload merge). Új terméket NEM hoz létre, NEM purge-öl.
    """
    client_id = tenant.client_id
    platform = str(tenant.platform or "").strip().lower()
    res: dict = {"client_id": client_id, "platform": platform, "mode": "pricestock"}
    if platform not in SUPPORTED_PLATFORMS:
        res["skipped"] = f"platform '{platform}' nincs portolva"
        return res
    if not _has_creds(tenant):
        res["skipped"] = "nincs cred"
        return res

    settings = get_settings()
    coll = settings.qdrant_sync_collection
    ub = settings.sync_upsert_batch
    q = QdrantClient(collection=coll)
    try:
        ex = await _existing_hashes(q, coll, client_id, "ps_hash")

        seen: set[str] = set()
        ops: list[tuple[dict, str]] = []
        updated = 0

        async def flush() -> None:
            nonlocal updated
            if not ops:
                return
            if not dry_run:
                await q.set_payload_batch(coll, ops)
            updated += len(ops)
            ops.clear()

        src_count = 0
        try:
            async for p in stream_products(tenant):
                src_count += 1
                if not p.id_key:
                    continue
                pid = point_id(client_id, p.id_key)
                if pid in seen:
                    continue
                seen.add(pid)
                if pid not in ex:                    # új termék -> a teljes sync hozza létre, nem itt
                    continue
                if ex[pid] == p.ps_hash_str:         # ár/készlet változatlan
                    continue
                ops.append((_ps_payload(p), pid))
                if len(ops) >= ub:
                    await flush()
            await flush()
        except Exception as e:  # noqa: BLE001
            logger.exception("PRICESTOCK[%s] stream hiba", client_id)
            res["error"] = f"stream: {e}"
            return res

        if src_count == 0:
            res["skipped"] = "0 forrás termék"
            return res
        res.update(collection=coll, source=src_count, existing=len(ex), ps_update=updated)
        if dry_run:
            res["dry_run"] = True
        return res
    finally:
        await q.aclose()

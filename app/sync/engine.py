"""Sync-motor: forrás-termékek -> embedding -> upsert a v2 Qdrant kollekcióba, delta + stale purge.

Paritás az n8n sync-kel:
 - delta-embed: content_hash változatlan -> NEM embeddelünk újra (csak ps_hash-eltérésnél set_payload),
   változott/új -> embed + upsert.
 - stale purge: mark-and-sweep — a teljes pass után töröljük a pontokat, amiknek a sku-ja már nincs
   a forrásban.
 - determinisztikus point ID -> idempotens upsert (újrafuttatás konvergál).

BIZTONSÁG: KIZÁRÓLAG a settings.qdrant_sync_collection-be (cx_chatbot_v2) írunk; az élő chat
read-kollekcióját (cx_chatbot) NEM érintjük. A fetch hibája/üres forrása -> tenant skip, NINCS purge
(nehogy egy átmeneti hiba kiürítse a kollekciót).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.embeddings import embed_texts
from app.core.qdrant import QdrantClient
from app.core.settings import get_settings
from app.sync.adapters import PLATFORM_FETCHERS
from app.sync.models import build_payload, build_text, compute_content_hash, compute_ps_hash, ps_payload

if TYPE_CHECKING:
    from app.models.db_models import Tenant

logger = logging.getLogger("cx.sync")


def _has_creds(tenant: "Tenant") -> bool:
    # minden portolt platform legalább api_base + (client_secret VAGY client_id) kell
    return bool(str(tenant.api_base or "").strip()) and bool(
        str(tenant.api_client_secret or "").strip() or str(tenant.api_client_id or "").strip()
    )


async def sync_tenant(tenant: "Tenant", *, dry_run: bool = False) -> dict:
    """Egy tenant teljes szinkronja a v2 kollekcióba. Visszaad egy összegző dict-et."""
    client_id = tenant.client_id
    platform = str(tenant.platform or "").strip().lower()
    res: dict = {"client_id": client_id, "platform": platform}

    fetcher = PLATFORM_FETCHERS.get(platform)
    if fetcher is None:
        res["skipped"] = f"platform '{platform}' nincs portolva"
        return res
    if not _has_creds(tenant):
        res["skipped"] = "nincs cred"
        return res

    # --- forrás-fetch (hiba -> skip, NINCS purge) ---
    try:
        sources = await fetcher(tenant)
    except Exception as e:  # noqa: BLE001
        logger.exception("SYNC[%s] fetch hiba", client_id)
        res["error"] = f"fetch: {e}"
        return res
    if not sources:
        res["skipped"] = "0 forrás termék — purge kihagyva"
        return res

    settings = get_settings()
    coll = settings.qdrant_sync_collection
    filename = f"__{platform}_products__"
    q = QdrantClient(collection=coll)
    try:
        # meglévő pontok (sku -> {id, content_hash, ps_hash}); új kollekciónál üres bázis
        try:
            existing = await q.scroll_products(coll, client_id, ["sku", "content_hash", "ps_hash"])
        except Exception:  # noqa: BLE001 — kollekció még nincs / átmeneti -> üres bázis (delta mindent újként kezel)
            logger.warning("SYNC[%s] scroll sikertelen (új kollekció?) — üres bázis", client_id)
            existing = []
        ex: dict[str, dict] = {}
        for pt in existing:
            pl = pt.get("payload", {}) or {}
            sku = str(pl.get("sku") or "")
            if sku:
                ex[sku] = {"id": pt.get("id"), "content_hash": pl.get("content_hash"), "ps_hash": pl.get("ps_hash")}

        seen: set[str] = set()
        to_embed: list[tuple[str, str, dict]] = []   # (text, point_id, payload)
        ps_ops: list[tuple[dict, str]] = []           # (payload_subset, point_id)

        for p in sources:
            if not p.sku or p.sku in seen:
                continue
            seen.add(p.sku)
            text = build_text(p)
            ch = compute_content_hash(p)
            ph = compute_ps_hash(p)
            pid = _point_id(client_id, p.sku)
            prev = ex.get(p.sku)
            if prev and prev.get("content_hash") == ch:
                # szemantika változatlan -> max. ár/készlet frissítés (nincs embed)
                if prev.get("ps_hash") != ph:
                    ps_ops.append((ps_payload(p, ph), pid))
                continue
            # új vagy szemantikailag változott -> embed + full upsert
            to_embed.append((text, pid, build_payload(client_id, p, filename, text, ch, ph)))

        stale_ids = [v["id"] for sku, v in ex.items() if sku not in seen and v.get("id") is not None]

        res.update(
            collection=coll, source=len(sources), embed=len(to_embed),
            ps_update=len(ps_ops), stale=len(stale_ids),
        )
        if dry_run:
            res["dry_run"] = True
            return res

        # csak valós futásnál hozzuk létre a kollekciót, az írás előtt (dry-run nem ír semmit)
        await q.ensure_collection(coll, settings.embed_dim, "Cosine")

        # embed + upsert kötegelve
        eb, ub = settings.sync_embed_batch, settings.sync_upsert_batch
        for i in range(0, len(to_embed), eb):
            chunk = to_embed[i:i + eb]
            vectors = await embed_texts([t for t, _, _ in chunk])
            points = [
                {"id": pid, "vector": vec, "payload": pl}
                for (t, pid, pl), vec in zip(chunk, vectors)
            ]
            for j in range(0, len(points), ub):
                await q.upsert(coll, points[j:j + ub])

        if ps_ops:
            await q.set_payload_batch(coll, ps_ops)
        if stale_ids:
            await q.delete(coll, stale_ids)

        res["total"] = await q.count_products(coll, client_id)
        return res
    finally:
        await q.aclose()


def _point_id(client_id: str, sku: str, chunk_idx: int = 0) -> str:
    from app.sync.hashing import point_id
    return point_id(client_id, sku, chunk_idx)

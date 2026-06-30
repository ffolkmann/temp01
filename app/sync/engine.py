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
from app.sync.hashing import point_id
from app.sync.models import build_payload

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
    q = QdrantClient(collection=coll)
    try:
        # meglévő pontok (point_id -> content_hash); új kollekciónál üres bázis
        try:
            existing = await q.scroll_products(coll, client_id, ["content_hash"])
        except Exception:  # noqa: BLE001 — kollekció még nincs / átmeneti -> üres bázis (mindent újként kezel)
            logger.warning("SYNC[%s] scroll sikertelen (új kollekció?) — üres bázis", client_id)
            existing = []
        ex: dict[str, str] = {
            str(pt.get("id")): str((pt.get("payload") or {}).get("content_hash") or "")
            for pt in existing
        }

        # delta: content_hash (content-only); változatlan -> skip, új/változott -> embed+upsert.
        # Az ár/készlet NEM triggerel re-embedet (azt az élő lookup adja).
        seen: set[str] = set()
        to_embed: list[tuple[str, str, dict]] = []   # (text, point_id, payload)
        for p in sources:
            if not p.id_key:
                continue
            pid = point_id(client_id, p.id_key)
            if pid in seen:
                continue
            seen.add(pid)
            if p.content_hash and ex.get(pid) == p.content_hash:
                continue  # tartalom változatlan -> nincs újra-embed
            to_embed.append((p.text, pid, build_payload(client_id, p)))

        stale_ids = [pid for pid in ex if pid not in seen]

        res.update(collection=coll, source=len(sources), embed=len(to_embed), stale=len(stale_ids))
        if dry_run:
            res["dry_run"] = True
            return res

        # csak valós futásnál hozzuk létre a kollekciót, az írás előtt (dry-run nem ír semmit)
        await q.ensure_collection(coll, settings.embed_dim, "Cosine")

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

        if stale_ids:
            await q.delete(coll, stale_ids)

        res["total"] = await q.count_products(coll, client_id)
        return res
    finally:
        await q.aclose()

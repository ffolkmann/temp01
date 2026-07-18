"""Qdrant kliens — read-only retrieval a lokális dev kollekcióból.

Pont-ID séma és payload a CLAUDE.md 4. pontja szerint. Itt CSAK olvasunk
(search / scroll); a sync (Fázis 3) külön jön.
"""

from typing import Any

import httpx

from app.core.settings import get_settings

_settings = get_settings()

# m67: a chat-út (search / find_by_url) szűrt payload-mezői — index nélkül a
# filter/scroll full-scan (m66 incidens: url-scroll ~180k ponton minden
# termékoldal-betöltésnél). Új/újraépített kollekció ezekből automatikusan kap.
_PAYLOAD_INDEXES: dict[str, str] = {
    "client_id": "keyword",
    "url": "keyword",
    "type": "keyword",
    "sku": "keyword",
    "available": "bool",
}


class QdrantClient:
    def __init__(self, url: str | None = None, collection: str | None = None) -> None:
        self.url = (url or _settings.qdrant_url).rstrip("/")
        self.collection = collection or _settings.qdrant_collection
        self._client = httpx.AsyncClient(base_url=self.url, timeout=30)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(
        self,
        vector: list[float],
        client_id: str,
        limit: int = 30,
        product_only: bool = True,
        available_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Dense keresés client_id payload-szűréssel."""
        must: list[dict[str, Any]] = [{"key": "client_id", "match": {"value": client_id}}]
        if product_only:
            must.append({"key": "type", "match": {"value": "product"}})
        if available_only:  # m60: keszlet-szurt dense pool (webdoc/Woo available bool payload)
            must.append({"key": "available", "match": {"value": True}})
        body = {
            "vector": vector,
            "filter": {"must": must},
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        r = await self._client.post(
            f"/collections/{self.collection}/points/search", json=body
        )
        r.raise_for_status()
        return r.json().get("result", [])

    async def find_by_url(self, client_id: str, url: str) -> dict[str, Any] | None:
        """Aktuális termék keresése a page_url_norm alapján (exact match).

        A prod `Get Current Product` szűrője: client_id + type=product + url.
        """
        body = {
            "filter": {
                "must": [
                    {"key": "client_id", "match": {"value": client_id}},
                    {"key": "type", "match": {"value": "product"}},
                    {"key": "url", "match": {"value": url}},
                ]
            },
            "limit": 1,
            "with_payload": True,
            "with_vector": False,
        }
        try:
            r = await self._client.post(
                f"/collections/{self.collection}/points/scroll", json=body
            )
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001 — m66: qdrant-kieses/timeout ne 500-azza a popup/chat utat
            import logging as _logging
            _logging.getLogger("cx.qdrant").warning("find_by_url qdrant hiba: %r", e)
            return None
        points = r.json().get("result", {}).get("points", [])
        return points[0] if points else None

    # --- sync írás/admin (Fázis 3) — KÜLÖN kollekcióra (cx_chatbot_v2); a chat read-útját
    #     (search/find_by_url, self.collection) nem érinti. A `collection` mindig explicit. ---
    async def ensure_collection(self, collection: str, size: int, distance: str = "Cosine") -> None:
        """Létrehozza a kollekciót, ha nincs, és garantálja a payload-indexeket (idempotens)."""
        r = await self._client.get(f"/collections/{collection}")
        if r.status_code != 200:
            r = await self._client.put(
                f"/collections/{collection}",
                json={"vectors": {"size": size, "distance": distance}},
            )
            r.raise_for_status()
        await self.ensure_payload_indexes(collection)

    async def ensure_payload_indexes(self, collection: str) -> None:
        """m67: payload-indexek idempotens létrehozása (csak a hiányzókat teszi fel).

        A payload_schema-ból nézi, mi van már meg; létrehozás:
        PUT /collections/{coll}/index?wait=true, body {"field_name","field_schema"}.
        """
        r = await self._client.get(f"/collections/{collection}")
        r.raise_for_status()
        schema = (r.json().get("result") or {}).get("payload_schema") or {}
        for field, ftype in _PAYLOAD_INDEXES.items():
            if field in schema:
                continue
            rr = await self._client.put(
                f"/collections/{collection}/index?wait=true",
                json={"field_name": field, "field_schema": ftype},
            )
            rr.raise_for_status()

    async def scroll_products(
        self, collection: str, client_id: str, fields: list[str]
    ) -> list[dict[str, Any]]:
        """Egy tenant összes type=product pontja (lapozva) — a delta/stale passhoz."""
        out: list[dict[str, Any]] = []
        offset = None
        while True:
            body: dict[str, Any] = {
                "filter": {"must": [
                    {"key": "client_id", "match": {"value": client_id}},
                    {"key": "type", "match": {"value": "product"}},
                ]},
                "limit": 1000,
                "with_payload": fields,
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            r = await self._client.post(f"/collections/{collection}/points/scroll", json=body)
            r.raise_for_status()
            res = r.json().get("result", {})
            pts = res.get("points", [])
            out.extend(pts)
            offset = res.get("next_page_offset")
            if not offset or not pts:
                break
        return out

    async def upsert(self, collection: str, points: list[dict[str, Any]]) -> None:
        if not points:
            return
        r = await self._client.put(
            f"/collections/{collection}/points?wait=true", json={"points": points}
        )
        r.raise_for_status()

    async def set_payload_batch(
        self, collection: str, ops: list[tuple[dict[str, Any], str]]
    ) -> None:
        """Csak-payload frissítés (ár/készlet) — pontonként más payload, egy batch-hívásban.

        ops: [(payload_subset, point_id), ...]. set_payload MERGE: csak a megadott mezők íródnak,
        a vektor és a szemantikus mezők érintetlenek.
        """
        operations = [{"set_payload": {"payload": pl, "points": [pid]}} for pl, pid in ops]
        if not operations:
            return
        r = await self._client.post(
            f"/collections/{collection}/points/batch?wait=true", json={"operations": operations}
        )
        r.raise_for_status()

    async def delete(self, collection: str, ids: list[str]) -> None:
        if not ids:
            return
        r = await self._client.post(
            f"/collections/{collection}/points/delete?wait=true", json={"points": ids}
        )
        r.raise_for_status()

    async def count_products(self, collection: str, client_id: str) -> int:
        body = {"exact": True, "filter": {"must": [
            {"key": "client_id", "match": {"value": client_id}},
            {"key": "type", "match": {"value": "product"}},
        ]}}
        r = await self._client.post(f"/collections/{collection}/points/count", json=body)
        r.raise_for_status()
        return r.json().get("result", {}).get("count", 0)

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"/collections/{self.collection}")
            return r.status_code == 200
        except httpx.HTTPError:
            return False


_qdrant: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient()
    return _qdrant

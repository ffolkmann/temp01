"""Qdrant kliens — read-only retrieval a lokális dev kollekcióból.

Pont-ID séma és payload a CLAUDE.md 4. pontja szerint. Itt CSAK olvasunk
(search / scroll); a sync (Fázis 3) külön jön.
"""

from typing import Any

import httpx

from app.core.settings import get_settings

_settings = get_settings()


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
    ) -> list[dict[str, Any]]:
        """Dense keresés client_id payload-szűréssel."""
        must: list[dict[str, Any]] = [{"key": "client_id", "match": {"value": client_id}}]
        if product_only:
            must.append({"key": "type", "match": {"value": "product"}})
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
        r = await self._client.post(
            f"/collections/{self.collection}/points/scroll", json=body
        )
        r.raise_for_status()
        points = r.json().get("result", {}).get("points", [])
        return points[0] if points else None

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

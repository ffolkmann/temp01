"""OpenAI text-embedding-3-small a kérdés vektorizálásához (1536 dim)."""

from openai import AsyncOpenAI

from app.core.settings import get_settings

_settings = get_settings()
_client = AsyncOpenAI(api_key=_settings.openai_api_key)


async def embed_query(text: str) -> list[float]:
    text = (text or " ").strip() or " "
    resp = await _client.embeddings.create(model=_settings.embed_model, input=text)
    return resp.data[0].embedding


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch embedding a synchez — UGYANAZ a modell, mint a query-embedding (parity).

    A Qdrant query-vektoroknak egyezniük kell az indexelt vektorokkal, ezért NEM vezetünk
    be új modellt: az _settings.embed_model (text-embedding-3-small, 1536-dim) megy itt is.
    """
    clean = [(t or " ").strip() or " " for t in texts]
    if not clean:
        return []
    resp = await _client.embeddings.create(model=_settings.embed_model, input=clean)
    return [d.embedding for d in resp.data]

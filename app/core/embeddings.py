"""OpenAI text-embedding-3-small a kérdés vektorizálásához (1536 dim)."""

from openai import AsyncOpenAI

from app.core.settings import get_settings

_settings = get_settings()
_client = AsyncOpenAI(api_key=_settings.openai_api_key)


async def embed_query(text: str) -> list[float]:
    text = (text or " ").strip() or " "
    resp = await _client.embeddings.create(model=_settings.embed_model, input=text)
    return resp.data[0].embedding

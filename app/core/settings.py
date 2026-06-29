from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DB / queue
    database_url: str = "postgresql+asyncpg://cx:cx@localhost:5432/cx"
    redis_url: str = "redis://localhost:6379/0"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "cx_chatbot"

    # LLM / embedding
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    chat_model: str = "claude-haiku-4-5-20251001"
    embed_model: str = "text-embedding-3-small"
    max_tokens: int = 1024

    # admin
    admin_token: str = "dev"

    # retrieval tuning (prod parity: Search KB limit 24, Hybrid Rerank top 8)
    retrieval_top_k: int = 24
    context_top_n: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()

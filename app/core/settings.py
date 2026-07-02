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
    admin_panel_token: str = ""

    # Mailgun (EU) — háttér e-mail értesítők (handoff / lead / order-status).
    # Üres vagy CHANGEME api_key -> nem küld, csak logol (a /chat megy tovább).
    mailgun_api_key: str = ""
    mailgun_domain: str = "codexpress.hu"
    mailgun_from: str = "noreply@codexpress.hu"
    mailgun_base_url: str = "https://api.eu.mailgun.net"

    # retrieval tuning (prod parity: Search KB limit 24, Hybrid Rerank top 8)
    retrieval_top_k: int = 24
    context_top_n: int = 8

    # sync (Fázis 3) — KÜLÖN cél-kollekció; a chat read-collection (qdrant_collection) érintetlen,
    # amíg a validálás után át nem állítjuk a QDRANT_COLLECTION-t a v2-re.
    qdrant_sync_collection: str = "cx_chatbot_v2"
    embed_dim: int = 1536               # text-embedding-3-small (mint cx_chatbot)
    sync_embed_batch: int = 50          # OpenAI embed batch (n8n Chunk Texts SIZE=50)
    sync_upsert_batch: int = 200        # Qdrant upsert batch (n8n PUT batch ~200)
    sync_shoprenter_concurrency: int = 4  # SR oldal-lekérés párhuzamosság (latency-kötött; óvatos rate-limit)
    embed_tpm_limit: int = 1_000_000      # text-embedding-3-small TPM — a throttle 85%-áig pace-el
    embed_max_retries: int = 8            # embed 429/APIError retry (exp backoff + retry-after)
    sync_include_inactive: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()

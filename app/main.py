"""FastAPI belépő — Fázis 1 chat-szerviz (lokális dev)."""

import logging

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.stats import router as stats_router
from app.api.config import router as config_router
from app.api.ingest import router as ingest_router
from app.api.operator import router as operator_router
from app.core.cors import TenantCORSMiddleware
from app.core.qdrant import get_qdrant

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)

app = FastAPI(title="CodeXpress AI Chatbot — Fázis 1", version="0.1.0")
# per-tenant CORS allowlist (a régi allow_origins=["*"] helyett)
app.add_middleware(TenantCORSMiddleware)
app.include_router(chat_router)
app.include_router(stats_router)
app.include_router(config_router)
app.include_router(ingest_router)
app.include_router(operator_router)


@app.get("/health")
async def health() -> dict:
    qdrant_ok = await get_qdrant().health()
    return {"status": "ok", "qdrant": qdrant_ok}

"""FastAPI belépő — Fázis 1 chat-szerviz (lokális dev)."""

import logging

from fastapi import Depends, FastAPI, Request, Response

from app.api.chat import router as chat_router
from app.core.cors import (
    CORS_ALLOW_HEADERS,
    CORS_ALLOW_METHODS,
    CORS_MAX_AGE,
    cors_headers,
)
from app.core.qdrant import get_qdrant

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)

app = FastAPI(title="CodeXpress AI Chatbot — Fázis 1", version="0.1.0")


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    """Per-tenant CORS (B.6.2): preflight kezelés + Vary minden válaszon.

    A /health CORS nélkül megy. A preflight (OPTIONS) reflektálja az Origint
    (a body ott nem elérhető); az érdemi POST ACAO-ját a cors_headers dependency
    állítja tenant-domén alapján. Nincs globális '*' — saját, tenant-tudatos logika.
    """
    origin = request.headers.get("origin")
    if request.url.path == "/health" or not origin:
        return await call_next(request)

    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": CORS_ALLOW_METHODS,
                "Access-Control-Allow-Headers": CORS_ALLOW_HEADERS,
                "Access-Control-Max-Age": CORS_MAX_AGE,
                "Vary": "Origin",
            },
        )

    response = await call_next(request)
    response.headers.setdefault("Vary", "Origin")
    return response


# a böngésző-POST végpontok (chat) tenant-tudatos ACAO-t kapnak; /health kimarad
app.include_router(chat_router, dependencies=[Depends(cors_headers)])


@app.get("/health")
async def health() -> dict:
    qdrant_ok = await get_qdrant().health()
    return {"status": "ok", "qdrant": qdrant_ok}

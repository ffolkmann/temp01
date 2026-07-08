"""Operátor-felület API (m28) — élő ügyintéző-átvétel.

Token-védett (ADMIN_PANEL_TOKEN, ugyanaz mint az admin-panel; az `operator` mező
csak megjelenítendő név / claimed_by címke, önbevallás — MVP kis csapatra).

Végpontok:
  GET  /operator/queue         -> requested + operator állapotú sessionök
  GET  /operator/conversation  -> egy session teljes üzenetlistája + állapot
  POST /operator/claim         -> ATOMI átvétel (requested -> operator)
  POST /operator/send          -> operátor-üzenet a látogatónak
  POST /operator/close         -> session lezárása
"""

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.services.live_agent import (
    claim_session,
    close_session,
    get_conversation,
    list_queue,
    operator_send,
)

router = APIRouter()


def _auth(token: str) -> None:
    if not token or token != os.environ.get("ADMIN_PANEL_TOKEN", ""):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/operator/queue")
async def operator_queue(
    token: str = Query(...),
    client_id: str = Query(""),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _auth(token)
    return {"items": await list_queue(session, client_id or None)}


@router.get("/operator/conversation")
async def operator_conversation(
    token: str = Query(...),
    session_id: str = Query(...),
    after: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _auth(token)
    return await get_conversation(session, session_id, after)


@router.post("/operator/claim")
async def operator_claim(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    b = await request.json()
    _auth(str(b.get("token") or ""))
    ok = await claim_session(
        session, str(b.get("session_id") or ""), str(b.get("operator") or "operator")
    )
    return {"ok": True, "claimed": ok}


@router.post("/operator/send")
async def operator_send_ep(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    b = await request.json()
    _auth(str(b.get("token") or ""))
    text = str(b.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty_text"}, status_code=400)
    mid = await operator_send(
        session, str(b.get("session_id") or ""), str(b.get("operator") or "operator"), text
    )
    if mid is None:
        return JSONResponse({"error": "not_operator_state"}, status_code=409)
    return {"ok": True, "id": mid}


@router.post("/operator/close")
async def operator_close(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    b = await request.json()
    _auth(str(b.get("token") or ""))
    await close_session(session, str(b.get("session_id") or ""))
    return {"ok": True}

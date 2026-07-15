"""Operátor-felület API (m28, m30) — élő ügyintéző-átvétel.

HATÓKÖR (m30):
  - `ADMIN_PANEL_TOKEN`      -> MASTER: minden tenant sorai (a `client_id` query
    paraméterrel szűkíthető).
  - `tenants.operator_token` -> CSAK az adott tenant sorai. A session_id-t minden
    művelet előtt ellenőrizzük: ha nem a tenanté, 404 (nem áruljuk el, hogy létezik).

Korábban minden végpont az ADMIN_PANEL_TOKEN-t fogadta el, és a várólista MINDEN
tenant beszélgetését visszaadta. Külső ügyfélnek átadva ez adatvédelmi incidens.

Az `operator` mező továbbra is csak megjelenítendő név / claimed_by címke (önbevallás).

Végpontok:
  GET  /operator/queue         -> requested + operator állapotú sessionök (hatókörön belül)
  GET  /operator/conversation  -> egy session teljes üzenetlistája + állapot
  POST /operator/claim         -> ATOMI átvétel (requested -> operator)
  POST /operator/send          -> operátor-üzenet a látogatónak
  POST /operator/close         -> session lezárása
  GET  /operator/status        -> a SAJÁT pult online-állapota + a hatókör
  POST /operator/status        -> online kapcsoló + heartbeat (operator.html)
  GET  /operator/live          -> m46: MINDEN aktív beszélgetés (messages-napló, ~30 perc)
  POST /operator/takeover      -> m46: proaktív átvétel bármely sessionre (-> operator)
"""

import logging
import os
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.redis import get_redis
from app.models.db_models import ChatMessage, ChatSession, Tenant
from app.services.conversations import format_transcript, get_transcript
from app.services.live_agent import (
    add_message as la_add_message,
    claim_session,
    clear_takeover,
    close_session,
    get_conversation,
    list_live,
    list_queue,
    mark_takeover,
    operator_send,
    resolve_client_id,
    takeover_session,
)
from app.services.operator_presence import (
    set_offline,
    set_online,
    status as presence_status,
)

router = APIRouter()
logger = logging.getLogger("cx.operator")

_MIN_TOKEN_LEN = 16  # a generált tokenek 32 hexa; rövid tokent ne is keressünk a DB-ben


async def _scope(db: AsyncSession, token: str) -> str | None:
    """Token -> hatókör. `None` = MASTER (minden tenant). Egyébként a tenant client_id-ja.

    Rossz/üres token -> 403. Konstans-idejű összehasonlítás a master tokenre.
    """
    t = (token or "").strip()
    if len(t) < _MIN_TOKEN_LEN:
        raise HTTPException(status_code=403, detail="forbidden")
    master = os.environ.get("ADMIN_PANEL_TOKEN", "")
    if master and secrets.compare_digest(t, master):
        return None
    cid = (
        await db.execute(select(Tenant.client_id).where(Tenant.operator_token == t))
    ).scalar_one_or_none()
    if not cid:
        raise HTTPException(status_code=403, detail="forbidden")
    return str(cid)


async def _assert_in_scope(db: AsyncSession, session_id: str, scope: str | None) -> None:
    """A session a hatókörbe esik-e. Master -> mindig igen. Idegen/nemlétező -> 404."""
    if scope is None:
        return
    cid = (
        await db.execute(
            select(ChatSession.client_id).where(ChatSession.session_id == session_id)
        )
    ).scalar_one_or_none()
    if cid != scope:
        raise HTTPException(status_code=404, detail="not_found")


async def _assert_in_scope_live(db: AsyncSession, session_id: str, scope: str | None) -> str | None:
    """m46: mint _assert_in_scope, de bot-only (csak messages-naplós) sessionre is jó.

    Vissza: a session client_id-ja (master + ismeretlen session -> None).
    Tenant-token + idegen VAGY ismeretlen session -> 404 (nem áruljuk el, létezik-e)."""
    cid = await resolve_client_id(db, session_id)
    if scope is not None and cid != scope:
        raise HTTPException(status_code=404, detail="not_found")
    return cid


@router.get("/operator/queue")
async def operator_queue(
    token: str = Query(...),
    client_id: str = Query(""),
    session: AsyncSession = Depends(get_session),
) -> dict:
    scope = await _scope(session, token)
    # tenant-token: a query-param NEM tágíthat, csak a saját client_id megy
    cid = scope if scope is not None else (client_id or None)
    return {"items": await list_queue(session, cid), "scope": scope}


@router.get("/operator/conversation")
async def operator_conversation(
    token: str = Query(...),
    session_id: str = Query(...),
    after: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> dict:
    scope = await _scope(session, token)
    cid = await _assert_in_scope_live(session, session_id, scope)
    return await get_conversation(session, session_id, after, client_id=cid)


@router.post("/operator/claim")
async def operator_claim(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    b = await request.json()
    scope = await _scope(session, str(b.get("token") or ""))
    sid = str(b.get("session_id") or "")
    await _assert_in_scope(session, sid, scope)
    ok = await claim_session(session, sid, str(b.get("operator") or "operator"))
    if ok:
        # m47: atvetel-flag a Redisbe -> a widget state-pollja azonnal latja
        await mark_takeover(get_redis(), sid, str(b.get("operator") or "operator"))
    return {"ok": True, "claimed": ok}


@router.post("/operator/send")
async def operator_send_ep(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    b = await request.json()
    scope = await _scope(session, str(b.get("token") or ""))
    sid = str(b.get("session_id") or "")
    await _assert_in_scope(session, sid, scope)
    text = str(b.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty_text"}, status_code=400)
    mid = await operator_send(session, sid, str(b.get("operator") or "operator"), text)
    if mid is None:
        return JSONResponse({"error": "not_operator_state"}, status_code=409)
    return {"ok": True, "id": mid}


@router.post("/operator/close")
async def operator_close(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    b = await request.json()
    scope = await _scope(session, str(b.get("token") or ""))
    sid = str(b.get("session_id") or "")
    await _assert_in_scope(session, sid, scope)
    await close_session(session, sid)
    await clear_takeover(get_redis(), sid)
    return {"ok": True}


@router.get("/operator/live")
async def operator_live(
    token: str = Query(...),
    client_id: str = Query(""),
    minutes: int = Query(30),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """m46/A: MINDEN aktív beszélgetés (forrás: `messages` napló, ~30 perc).

    Listanézet: metaadat + utolsó turn; a teljes átirat kattintásra jön
    (/operator/conversation, m46 log-fallback). Hatókör: mint a /operator/queue."""
    scope = await _scope(session, token)
    cid = scope if scope is not None else (client_id or None)
    mins = max(1, min(int(minutes or 30), 240))
    return {"items": await list_live(session, cid, mins), "scope": scope}


@router.post("/operator/takeover")
async def operator_takeover(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    """m46/B: proaktív átvétel bármely folyó beszélgetésre (-> operator).

    409: másik operátor aktív claimje. 400: a tenantnál nincs élő átvétel.
    Sikernél a bot-előzményt (messages napló) system-üzenetként egyszer
    becsatoljuk a chat_messages-be — a meglévő operátor-nézet mutatja."""
    b = await request.json()
    scope = await _scope(session, str(b.get("token") or ""))
    sid = str(b.get("session_id") or "")
    if not sid:
        return JSONResponse({"error": "missing_session_id"}, status_code=400)
    cid = await _assert_in_scope_live(session, sid, scope)
    if cid is None:
        raise HTTPException(status_code=404, detail="not_found")
    trow = (
        await session.execute(
            select(Tenant.live_agent_enabled, Tenant.bot_name).where(Tenant.client_id == cid)
        )
    ).first()
    if trow is None or not bool(trow[0]):
        return JSONResponse({"error": "live_agent_disabled"}, status_code=400)
    operator = str(b.get("operator") or "operator")
    outcome = await takeover_session(session, cid, sid, operator)
    if outcome == "conflict":
        return JSONResponse({"error": "claimed_by_other"}, status_code=409)
    await mark_takeover(get_redis(), sid, operator)
    # bot-előzmény becsatolása (csak ha még nincs live-agent üzenet a sessionben)
    try:
        has_any = (
            await session.execute(
                select(ChatMessage.id).where(ChatMessage.session_id == sid).limit(1)
            )
        ).scalar_one_or_none()
        if has_any is None:
            turns = await get_transcript(session, cid, sid)
            if turns:
                ctx_txt = format_transcript(turns, str(trow[1] or "Bot"))
                await la_add_message(
                    session, cid, sid, "system", "[Beszélgetés előzménye]\n" + ctx_txt
                )
    except Exception:  # noqa: BLE001 - az elozmeny-becsatolas hibaja ne torje az atvetelt
        logger.exception("takeover: elozmeny-becsatolas hiba (%s)", sid)
    return {"ok": True, "state": "operator", "client_id": cid, "claimed_by": operator}


@router.get("/operator/status")
async def operator_status(
    token: str = Query(...), session: AsyncSession = Depends(get_session)
) -> dict:
    """A SAJÁT pult jelenléte + a hatókör (a konzol ebből tudja, mit mutasson)."""
    scope = await _scope(session, token)
    st = await presence_status(scope)
    st["scope"] = scope
    return st


@router.post("/operator/status")
async def operator_status_set(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Any:
    """Online/offline kapcsoló + heartbeat. Body: {token, online: bool, operator?: str}.

    online=true  -> presence-kulcs beállítása/frissítése (TTL 150s);
    online=false -> azonnali offline (kulcs törlése).
    A kulcs a hatókörhöz tartozik: master -> `__all__`, tenant-token -> a saját client_id.
    """
    b = await request.json()
    scope = await _scope(session, str(b.get("token") or ""))
    online = bool(b.get("online"))
    if online:
        await set_online(str(b.get("operator") or "operator"), scope)
    else:
        await set_offline(scope)
    return {"ok": True, "online": online, "scope": scope}

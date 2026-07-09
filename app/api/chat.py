"""POST /chat — a CLAUDE.md C.rész szerződése + a prod Chat workflow (7ZtoREZGxJUxLYFU) parity.

A `type` mező multiplexál:
  - nincs type      -> ÜZENET: intent-kaszkád -> retrieval+rerank+current-product+LLM -> {reply, action, configurator}
  - "feedback"      -> 👍/👎 tárolás (válasz ignorálva a widgetben)
  - "lead"          -> lead tárolás + handoff e-mail (stub)

Az ÜZENET-ág a prod sorrendjét követi (lásd seed/prod_retrieval.txt):
  order-status -> configurator -> handoff -> (egyik sem) -> RAG + LLM.

A widget kompatibilitás miatt a route a /webhook/chat útvonalon IS elérhető.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.llm import generate_reply
from app.core.redis import get_redis
from app.models.db_models import Plan, Tenant
from app.models.schemas import ChatRequest, ChatResponse, ConfiguratorRef, EventAck
from app.services.conversations import format_transcript, get_transcript, log_turn
from app.services.events import WIDGET_KINDS, count_product_links, log_event
from app.services.coupons import active_coupons
from app.services.current_product import get_current_product, normalize_url
from app.services.feedback import store_feedback
from app.services.handoff import HANDOFF_REPLY, send_handoff_email
from app.services.intent import detect_configurator, detect_handoff, detect_order_intent
from app.services.leads import store_lead
from app.services.live_agent import (
    LIVE_AGENT_WAIT_REPLY,
    add_message as la_add_message,
    get_session_state,
    poll_messages,
    request_operator,
)
from app.services.live_product import fetch_live_price_stock
from app.services.operator_hours import operators_available
from app.services.operator_presence import is_operator_online
from app.services.operator_notify import notify_operators
from app.services.order_status import handle_order_status
from app.services.parse_reply import parse_reply
from app.services.prompt import PromptContext, build_system_prompt
from app.services.retrieval import retrieve
from urllib.parse import quote_plus

from app.services.shop_search import SEARCH_FB_THRESHOLD, _build_queries, shop_front_search
from app.services.prompt import _shop_search_url
from app.services.unanswered import log_unanswered
from app.services.usage import record_usage

logger = logging.getLogger("cx.chat")
router = APIRouter()

_FALLBACK = "Elnézést, most nem tudok válaszolni."


async def _get_tenant(session: AsyncSession, client_id: str) -> Tenant | None:
    return (
        await session.execute(select(Tenant).where(Tenant.client_id == client_id))
    ).scalar_one_or_none()


async def _plan_live_api(session: AsyncSession, plan: str | None) -> bool:
    if not plan:
        return False
    row = (
        await session.execute(select(Plan).where(Plan.plan == plan))
    ).scalar_one_or_none()
    return bool(row and row.live_api)


async def _plan_search_fallback(session: AsyncSession, plan: str | None) -> bool:
    if not plan:
        return False
    row = (
        await session.execute(select(Plan).where(Plan.plan == plan))
    ).scalar_one_or_none()
    return bool(row and getattr(row, "search_fallback", False))


async def _handle_message(req: ChatRequest, session: AsyncSession) -> ChatResponse:
    tenant = await _get_tenant(session, req.client_id)
    if tenant is None:
        logger.warning("ismeretlen tenant: %s", req.client_id)
        return ChatResponse(reply=_FALLBACK)

    message = (req.message or "").strip()
    if not message:
        return ChatResponse(reply=tenant.welcome_message or _FALLBACK)

    # --- Élő operátor-átvétel (m28): ha a session már requested/operator, a bot
    #     elnémul (handoff_bot_silent), a látogató üzenete a chat_messages-be kerül,
    #     a widget a válaszokat /chat/poll-lal olvassa. Fail-safe: hiba -> normál bot.
    if getattr(tenant, "live_agent_enabled", False) and req.session_id:
        try:
            la_state = await get_session_state(session, req.client_id, req.session_id)
        except Exception:  # noqa: BLE001
            la_state = "bot"
        if la_state in ("requested", "operator"):
            try:
                await la_add_message(session, req.client_id, req.session_id, "user", message)
            except Exception:  # noqa: BLE001
                logger.exception("live-agent: user-üzenet mentés hiba")
            if la_state == "operator" or bool(getattr(tenant, "handoff_bot_silent", True)):
                return ChatResponse(reply="", action="operator_wait")
            # requested + handoff_bot_silent=False -> a bot tovább válaszol (fall through)

    # usage-accounting: minden bejövő USER üzenet (message +1; conversation ha új session/period)
    await record_usage(session, get_redis(), req.client_id, req.session_id)

    pc = req.page_context
    ctx = PromptContext(
        page_is_product=bool(pc and pc.is_product),
        page_product_name=str(pc.product_name or "") if pc else "",
        page_url=str(pc.url or "") if pc else "",
        page_url_norm=normalize_url(pc.url if pc else ""),
    )

    # --- Pre-LLM intent kaszkád (a prod sorrendjében) ---
    live_api = await _plan_live_api(session, tenant.plan)

    # 1) order-status: a prod élő order-lekérést végez, majd "Send Status Email"-t küld
    #    a vevőnek; a /chat ettől függetlenül SEMLEGES választ ad (adat-szivárgás ellen).
    #    Platform szerinti dispatch (Sellvio/Shoprenter/Unas/WooCommerce) a service-ben.
    order = detect_order_intent(message, tenant, live_api)
    if order.is_order_status:
        reply = await handle_order_status(tenant, order)
        await log_turn(session, req.client_id, req.session_id, message, reply)
        await log_event(session, req.client_id, req.session_id, "order_lookup",
                        {"order_id": order.order_id})
        return ChatResponse(reply=reply, action=None)

    # 2) configurator (csak configurator_shop tenantnál)
    cfg = detect_configurator(message, tenant)
    if cfg.is_configurator and cfg.cfg:
        cfg_reply = (
            "Szívesen segítek kiszámolni a klíma telepítés becsült díját! "
            "Kérlek, töltsd ki az alábbi pár kérdést."
        )
        await log_turn(
            session, req.client_id, req.session_id, message, cfg_reply, "quote_configurator"
        )
        await log_event(session, req.client_id, req.session_id, "configurator", None)
        return ChatResponse(
            reply=cfg_reply,
            action="quote_configurator",
            configurator=ConfiguratorRef(**cfg.cfg),
        )

    # 3) handoff
    ho = detect_handoff(message, tenant, req.history, ctx.page_url)
    if ho.is_handoff:
        # m28: élő operátor-átvétel (ha be van kapcsolva ÉS van session) -> várólistára;
        #      a bot elnémul, a látogató a /chat/poll-on kapja az operátor válaszait.
        #      Fail-safe: bármi hiba -> a régi e-mailes handoff ág (lentebb).
        if (
            getattr(tenant, "live_agent_enabled", False)
            and req.session_id
            and operators_available(tenant)  # m28 fázis6: van Telegram-címzett ÉS nyitvatartás
            and await is_operator_online()   # m28+: operátor ONLINE (operator.html kapcsoló)
        ):
            try:
                # az eddigi (bot-)átirat mint kontextus az operátornak (system-üzenet)
                turns = await get_transcript(session, req.client_id, req.session_id)
                if turns:
                    ctx_txt = format_transcript(turns, tenant.bot_name or "Bot")
                    await la_add_message(
                        session, req.client_id, req.session_id, "system",
                        f"[Beszélgetés előzménye]\n{ctx_txt}",
                    )
                await request_operator(session, req.client_id, req.session_id)
                await la_add_message(session, req.client_id, req.session_id, "user", message)
                await log_turn(
                    session, req.client_id, req.session_id, message,
                    LIVE_AGENT_WAIT_REPLY, "operator_wait",
                )
                await log_event(
                    session, req.client_id, req.session_id, "handoff",
                    {"page": ho.page, "mode": "live"},
                )
                # m28 fázis5: Telegram-ping az operátor(ok)nak — fail-safe (a Telegram-
                #   hiba NE okozzon e-mail-fallbacket, ezért külön try/except).
                try:
                    await notify_operators(tenant, message)
                except Exception:  # noqa: BLE001
                    logger.exception("live-agent: Telegram-ping hiba (nem kritikus)")
                return ChatResponse(reply=LIVE_AGENT_WAIT_REPLY, action="operator_wait")
            except Exception:  # noqa: BLE001 — élő átvétel hiba -> essünk vissza e-mailre
                logger.exception("live-agent: átvétel-kérés hiba, e-mail handoff fallback")
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001
                    pass

        # e-mailes handoff (eredeti viselkedés / fallback)
        # előbb logolunk, hogy az aktuális kérés IS benne legyen a teljes átiratban
        await log_turn(
            session, req.client_id, req.session_id, message, HANDOFF_REPLY, "collect_lead"
        )
        turns = await get_transcript(session, req.client_id, req.session_id)
        transcript = format_transcript(turns, tenant.bot_name or "Bot") if turns else None
        await send_handoff_email(req.client_id, ho, transcript=transcript)
        await log_event(session, req.client_id, req.session_id, "handoff", {"page": ho.page})
        return ChatResponse(reply=HANDOFF_REPLY, action="collect_lead")

    # --- RAG + LLM ---
    # embed-input: termékoldalon a termék neve + üzenet, különben csak az üzenet.
    # m24: rövid follow-upnál ("bojlik érdekelnek") a téma/márka kiesne a kereső-
    # queryből -> az előző user-üzenetet prepend-eljük az embed-inputhoz. A rerank
    # `message` paramétere VÁLTOZATLANUL az eredeti üzenet (parity).
    embed_input = (
        f"{ctx.page_product_name}. {message}"
        if ctx.page_is_product and ctx.page_product_name
        else message
    )
    if len(message) <= 48 and not (ctx.page_is_product and ctx.page_product_name):
        try:
            prev_turns = await get_transcript(session, req.client_id, req.session_id)
            prev_q = str(prev_turns[-1].question or "").strip() if prev_turns else ""
            if prev_q and prev_q.lower() not in message.lower():
                embed_input = f"{prev_q[:120]}. {message}"
        except Exception:  # noqa: BLE001 — kontextus-dúsítás hibája ne törje a chatet
            pass
    hits, top_score = await retrieve(
        embed_input, message, req.client_id, ctx.page_url, ctx.page_url_norm
    )
    current = await get_current_product(req.client_id, ctx.page_url_norm)
    # élő ár/készlet a megnyitott termékre (plan.live_api-gated, csak termékoldalon);
    # FAIL-SAFE: hiba/None -> a synced adatlap marad
    live = None
    if ctx.page_is_product and live_api and current is not None:
        live = await fetch_live_price_stock(tenant, current)
    # webshop-kereso fallback (m25): gyenge score-nal a bolt sajat keresoje ad jelolteket
    shop_hits: list[dict] | None = None
    if top_score < SEARCH_FB_THRESHOLD and bool(getattr(tenant, "search_fallback", False)):
        try:
            if await _plan_search_fallback(session, tenant.plan):
                shop_hits = await shop_front_search(tenant, message)
                if shop_hits:
                    await log_event(session, req.client_id, req.session_id, "search_fallback",
                                    {"q": message[:80], "n": len(shop_hits)})
        except Exception:  # noqa: BLE001 — a fallback hibaja ne torje a chatet
            logger.exception("search_fallback hiba")
            shop_hits = None
    coupons = await active_coupons(session, req.client_id)
    system_prompt = build_system_prompt(tenant, hits, current, coupons, ctx, live=live, shop_search=shop_hits)

    try:
        raw = await generate_reply(system_prompt, req.history, message)
    except Exception:  # noqa: BLE001 — a widget mindig kapjon választ
        logger.exception("LLM hívás hiba")
        await log_turn(session, req.client_id, req.session_id, message, _FALLBACK)
        return ChatResponse(reply=_FALLBACK)

    parsed = parse_reply(raw)
    # m25: search_fallback zaro-link determinisztikusan (az LLM nem mindig teszi be magatol)
    if shop_hits:
        _su = _shop_search_url(tenant)
        if _su and _su not in parsed.reply and "További találatok a webáruházban" not in parsed.reply:
            _q = quote_plus((_build_queries(message) or [message[:60]])[0])
            _newreply = parsed.reply.rstrip() + "\n\n[További találatok a webáruházban](" + _su + _q + ")"
            try:
                parsed.reply = _newreply
            except Exception:  # noqa: BLE001 — frozen dataclass eseten
                from dataclasses import replace as _dc_replace
                parsed = _dc_replace(parsed, reply=_newreply)
    # megválaszolatlan-naplózás (Eval Unanswered): low_score / collect_lead / order_form
    await log_unanswered(session, req.client_id, req.session_id, message, top_score, parsed.action)
    # beszélgetés-napló (m22): a stat.html visszanéző + e-mail átiratok forrása
    await log_turn(session, req.client_id, req.session_id, message, parsed.reply, parsed.action)
    # termékajánlás-számláló (m22): a válaszban linkelt webshop-termékek
    rec_n = count_product_links(parsed.reply, tenant)
    if rec_n:
        await log_event(session, req.client_id, req.session_id, "product_rec", {"count": rec_n})
    return ChatResponse(reply=parsed.reply, action=parsed.action, configurator=None)


@router.post("/chat", response_model=None)
@router.post("/webhook/chat", response_model=None)
async def chat(req: ChatRequest, session: AsyncSession = Depends(get_session)):
    t = (req.type or "").strip().lower()

    if t == "feedback":
        await store_feedback(session, req)
        return EventAck(stored="feedback")

    if t == "lead":
        await store_lead(session, req)
        return EventAck(stored="lead")

    if t == "event":
        # widget-esemény (m22): csak whitelistelt fajta; ismeretlen -> csendes ack
        kind = (req.event or "").strip().lower()
        if kind in WIDGET_KINDS:
            await log_event(session, req.client_id, req.session_id, kind,
                            {"url": (req.url or "")[:500], "title": (req.title or "")[:200]})
        return EventAck(stored="event")

    # nincs type -> üzenet
    return await _handle_message(req, session)


@router.get("/chat/poll")
async def chat_poll(
    client_id: str = Query(...),
    session_id: str = Query(...),
    after: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Widget-polling (m28): operátor-mód üzenetei.

    Vissza: {state, messages:[{id,sender,text,ts}]}. Csak az OPERÁTOR-üzeneteket adja
    (a látogató a sajátjait már látja); `after` = a widget által utoljára látott id.
    """
    state = await get_session_state(session, client_id, session_id)
    messages = await poll_messages(session, session_id, after, senders=("operator",))
    return {"state": state, "messages": messages}

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

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.llm import generate_reply
from app.models.db_models import Plan, Tenant
from app.models.schemas import ChatRequest, ChatResponse, ConfiguratorRef, EventAck
from app.services.coupons import active_coupons
from app.services.current_product import get_current_product, normalize_url
from app.services.feedback import store_feedback
from app.services.handoff import HANDOFF_REPLY, send_handoff_email
from app.services.intent import detect_configurator, detect_handoff, detect_order_intent
from app.services.leads import store_lead
from app.services.order_status import handle_order_status
from app.services.parse_reply import parse_reply
from app.services.prompt import PromptContext, build_system_prompt
from app.services.retrieval import retrieve

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


async def _handle_message(req: ChatRequest, session: AsyncSession) -> ChatResponse:
    tenant = await _get_tenant(session, req.client_id)
    if tenant is None:
        logger.warning("ismeretlen tenant: %s", req.client_id)
        return ChatResponse(reply=_FALLBACK)

    message = (req.message or "").strip()
    if not message:
        return ChatResponse(reply=tenant.welcome_message or _FALLBACK)

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
    #    MOST csak a Sellvio platform van portolva (teslashop); SR/Unas/WC később.
    order = detect_order_intent(message, tenant, live_api)
    if order.is_order_status and order.platform == "sellvio":
        reply = await handle_order_status(tenant, order)
        return ChatResponse(reply=reply, action=None)
    if order.is_order_status:
        # SR/Unas/WC: detektálva, de a platform order-lekérés MÉG NINCS portolva -> RAG-fallback
        logger.info(
            "ORDER-STATUS[%s] platform=%s még nincs portolva — RAG-fallback",
            req.client_id, order.platform,
        )
    else:
        # 2) configurator (csak configurator_shop tenantnál)
        cfg = detect_configurator(message, tenant)
        if cfg.is_configurator and cfg.cfg:
            return ChatResponse(
                reply="Szívesen segítek kiszámolni a klíma telepítés becsült díját! "
                "Kérlek, töltsd ki az alábbi pár kérdést.",
                action="quote_configurator",
                configurator=ConfiguratorRef(**cfg.cfg),
            )

        # 3) handoff
        ho = detect_handoff(message, tenant, req.history, ctx.page_url)
        if ho.is_handoff:
            await send_handoff_email(req.client_id, ho)
            return ChatResponse(reply=HANDOFF_REPLY, action="collect_lead")

    # --- RAG + LLM ---
    # embed-input: termékoldalon a termék neve + üzenet, különben csak az üzenet
    embed_input = (
        f"{ctx.page_product_name}. {message}"
        if ctx.page_is_product and ctx.page_product_name
        else message
    )
    hits = await retrieve(
        embed_input, message, req.client_id, ctx.page_url, ctx.page_url_norm
    )
    current = await get_current_product(req.client_id, ctx.page_url_norm)
    coupons = await active_coupons(session, req.client_id)
    system_prompt = build_system_prompt(tenant, hits, current, coupons, ctx)

    try:
        raw = await generate_reply(system_prompt, req.history, message)
    except Exception:  # noqa: BLE001 — a widget mindig kapjon választ
        logger.exception("LLM hívás hiba")
        return ChatResponse(reply=_FALLBACK)

    parsed = parse_reply(raw)
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

    # nincs type -> üzenet
    return await _handle_message(req, session)

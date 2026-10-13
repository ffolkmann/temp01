"""Lead-modul — lead tárolás + értesítő e-mail (CLAUDE.md C.4).

A tárolás éles (Postgres); az értesítő Mailgunon (EU) megy, HÁTTÉRBEN (a /chat
latencyt nem növeli). Ugyanez fut a konfigurátor-leadnél is (source="configurator").
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mailer import safe_reply_to, schedule_email
from app.services.conversations import get_transcript
from app.services.leadmail import build_lead_email  # m115
from app.models.db_models import Lead, Tenant
from app.models.schemas import ChatRequest

logger = logging.getLogger("cx.leads")


async def store_lead(session: AsyncSession, req: ChatRequest) -> None:
    lead = Lead(
        client_id=req.client_id,
        session_id=req.session_id,
        name=req.name,
        email=req.email,
        phone=req.phone,
        message=req.message,
        source=req.source,
        history=[h.model_dump() for h in req.history] if req.history else None,
    )
    session.add(lead)
    await session.commit()

    # értesítő e-mail a partnernek (Mailgun, háttérben)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.client_id == req.client_id))
    ).scalar_one_or_none()
    lead_email = (tenant.lead_email if tenant else None) or ""

    # teljes beszélgetés (m22): DB-napló session szerint; fallback a widget history
    turns = await get_transcript(session, req.client_id, req.session_id)
    bot_name = (tenant.bot_name if tenant else None) or "Bot"
    # m115: fordulo-parok a formazott levelhez (DB-naplo; fallback a widget history)
    if turns:
        pairs = [(t.question, t.answer) for t in turns]
    else:
        pairs = []
        for h in req.history or []:
            role = getattr(h, "role", None) or (h.get("role") if isinstance(h, dict) else "")
            content = getattr(h, "content", None) or (h.get("content") if isinstance(h, dict) else "")
            if content:
                pairs.append((content, None) if role == "user" else (None, content))

    reply_to = safe_reply_to(req.email)  # m113: a bolt valasza kozvetlenul a latogatohoz menjen
    subject, text, html_body = build_lead_email(
        client_id=req.client_id, name=req.name, email=req.email, phone=req.phone,
        message=req.message, source=req.source, reply_to=reply_to, turns=pairs,
        bot_name=bot_name,
    )
    logger.info(
        "LEAD[%s] -> e-mail to=%s email=%s phone=%s source=%s",
        req.client_id, lead_email, req.email, req.phone, req.source,
    )
    logger.info("m113 lead reply-to: %d client=%s", 1 if reply_to else 0, req.client_id)
    schedule_email(lead_email, subject, text, reply_to=reply_to, html=html_body)

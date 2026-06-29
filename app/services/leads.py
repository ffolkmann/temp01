"""Lead-modul — lead tárolás + értesítő e-mail (CLAUDE.md C.4).

A tárolás éles (Postgres); az értesítő Mailgunon (EU) megy, HÁTTÉRBEN (a /chat
latencyt nem növeli). Ugyanez fut a konfigurátor-leadnél is (source="configurator").
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mailer import schedule_email
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

    subject = f"Uj erdeklodo - {req.client_id} chatbot"
    text = (
        "Uj erdeklodo erkezett.\n\n"
        f"Nev: {req.name or ''}\nEmail: {req.email or ''}\n"
        f"Telefon: {req.phone or ''}\nUzenet: {req.message or ''}"
    )
    logger.info(
        "LEAD[%s] -> e-mail to=%s email=%s phone=%s source=%s",
        req.client_id, lead_email, req.email, req.phone, req.source,
    )
    schedule_email(lead_email, subject, text)

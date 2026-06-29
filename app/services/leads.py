"""Lead-modul — lead tárolás + handoff e-mail (CLAUDE.md C.4).

Fázis 1: a tárolás éles (Postgres), az e-mail-küldés STUB (csak logol).
A valódi SMTP/connector a Fázis 3/5-ben (n8n marad email-glue-nak).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    # handoff e-mail (STUB)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.client_id == req.client_id))
    ).scalar_one_or_none()
    lead_email = tenant.lead_email if tenant else None
    logger.info(
        "LEAD[%s] -> handoff e-mail (stub) to=%s email=%s phone=%s source=%s",
        req.client_id, lead_email, req.email, req.phone, req.source,
    )

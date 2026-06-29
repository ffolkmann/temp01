"""Feedback-modul — 👍/👎 tárolás (CLAUDE.md C.4). Fázis 1: csak DB-be írunk."""

from app.models.db_models import Feedback
from app.models.schemas import ChatRequest
from sqlalchemy.ext.asyncio import AsyncSession


async def store_feedback(session: AsyncSession, req: ChatRequest) -> None:
    fb = Feedback(
        client_id=req.client_id,
        session_id=req.session_id,
        rating=req.rating,
        question=req.question,
        answer=req.answer,
        page_context=req.page_context.model_dump() if req.page_context else None,
    )
    session.add(fb)
    await session.commit()

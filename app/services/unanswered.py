"""Megválaszolatlan-naplózás — a prod `Eval Unanswered` portja.

A RAG-ág után: topScore = Search KB top dense score; lowScore = topScore < 0.45.
reasons ⊆ {low_score, collect_lead, order_form} (az action-ből). Ha van reason -> log.
A score + reasons az unanswered táblába megy (a /stats questions[].score/reasons forrása).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Unanswered

logger = logging.getLogger("cx.unanswered")

THRESHOLD = 0.45


def eval_reasons(top_score: float, action: str | None) -> list[str]:
    reasons: list[str] = []
    if top_score < THRESHOLD:
        reasons.append("low_score")
    if action == "order_status_form":
        reasons.append("order_form")
    elif action == "collect_lead":
        reasons.append("collect_lead")
    return reasons


async def log_unanswered(
    session: AsyncSession, client_id: str, session_id: str | None,
    question: str, top_score: float, action: str | None,
) -> None:
    """Ha van reason, naplózza a kérdést score+reasons-szel. Fail-safe: nem töri a /chat-et."""
    reasons = eval_reasons(top_score, action)
    if not reasons:
        return
    try:
        session.add(Unanswered(
            client_id=client_id, session_id=session_id, question=question,
            score=top_score, reasons=reasons,
        ))
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("unanswered: log hiba (%s)", client_id)
        await session.rollback()

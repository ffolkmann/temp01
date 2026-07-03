"""Beszélgetés-napló (messages tábla) — m22.

Minden /chat üzenet-turn (kérdés+válasz) naplózása session szerint. Forrása:
- a stat.html "teljes beszélgetés" nézetének (GET /stats/conversation),
- a handoff- és lead-értesítő e-mailek teljes átiratának.

Fail-safe: hiba esetén logol, a /chat-et SOHA nem töri. Retention: 30 nap
(scripts/purge_messages.py — a cx-sync.service ExecStartPost futtatja nightly).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Message

logger = logging.getLogger("cx.conversations")


async def log_turn(
    session: AsyncSession,
    client_id: str,
    session_id: str | None,
    question: str,
    answer: str,
    action: str | None = None,
) -> None:
    """Egy turn (kérdés+válasz) naplózása. Fail-safe."""
    try:
        session.add(Message(
            client_id=client_id, session_id=session_id,
            question=question, answer=answer, action=action,
        ))
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("messages: log hiba (%s)", client_id)
        await session.rollback()


async def get_transcript(
    session: AsyncSession, client_id: str, session_id: str | None,
) -> list[Message]:
    """A session teljes turn-listája időrendben. Hibánál/session nélkül üres lista."""
    if not session_id:
        return []
    try:
        rows = (await session.execute(
            select(Message)
            .where(Message.client_id == client_id, Message.session_id == session_id)
            .order_by(Message.created_at, Message.id)
        )).scalars().all()
        return list(rows)
    except Exception:  # noqa: BLE001
        logger.exception("messages: transcript hiba (%s)", client_id)
        return []


def format_transcript(turns: list[Message], bot_name: str = "Bot") -> str:
    """E-mail szövegtörzsbe illeszthető teljes átirat."""
    lines: list[str] = []
    for t in turns:
        if t.question:
            lines.append(f"Latogato: {t.question}")
        if t.answer:
            lines.append(f"{bot_name}: {t.answer}")
    return "\n".join(lines)


def format_history(history: list | None) -> str:
    """Fallback: a widget-küldött history formázása (ha nincs DB-napló)."""
    lines: list[str] = []
    for h in history or []:
        role = getattr(h, "role", None) or (h.get("role") if isinstance(h, dict) else "")
        content = getattr(h, "content", None) or (h.get("content") if isinstance(h, dict) else "")
        if not content:
            continue
        lines.append(("Latogato: " if role == "user" else "Bot: ") + str(content))
    return "\n".join(lines)

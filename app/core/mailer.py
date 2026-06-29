"""Mailgun (EU) háttér e-mail küldés.

A prod n8n SMTP-vel küld; a kód-magban Mailgun (EU endpoint) váltja ki.
A /chat válasz-latencyt NEM növeli: a tényleges HTTP POST háttérben fut
(`schedule_email` -> asyncio.create_task, fire-and-forget).

Guardrail: ha nincs konfigurált API-kulcs (üres vagy CHANGEME), nem küld —
csak logol. Hiba esetén logol, SOHA nem dob (a /chat mindig fusson tovább).
"""

import asyncio
import logging

import httpx

from app.core.settings import get_settings

logger = logging.getLogger("cx.mailer")

# kulcs-értékek, amik "nincs konfigurálva"-t jelentenek
_DISABLED_KEYS = {"", "changeme"}

# erős referencia a háttér-taskokra (különben a GC eldobhatja őket futás közben)
_bg_tasks: set[asyncio.Task] = set()


def _enabled(settings) -> bool:
    return (settings.mailgun_api_key or "").strip().lower() not in _DISABLED_KEYS


async def send_email(to: str, subject: str, text: str) -> bool:
    """Egy e-mail küldése Mailgunon át. True = elküldve, False = kihagyva/hiba.

    Soha nem dob kivételt — a hívó ágnak (chat) tovább kell futnia.
    """
    settings = get_settings()
    if not _enabled(settings):
        logger.info("MAILGUN kikapcsolva (nincs API kulcs) — nem küldök. to=%s subj=%r", to, subject)
        return False
    if not (to or "").strip():
        logger.warning("MAILGUN: üres címzett — kihagyva. subj=%r", subject)
        return False

    url = f"{settings.mailgun_base_url.rstrip('/')}/v3/{settings.mailgun_domain}/messages"
    data = {"from": settings.mailgun_from, "to": to, "subject": subject, "text": text}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, auth=("api", settings.mailgun_api_key), data=data)
            resp.raise_for_status()
        logger.info("MAILGUN elküldve to=%s subj=%r", to, subject)
        return True
    except Exception:  # noqa: BLE001 — e-mail hiba SOHA ne törje meg a /chat-et
        logger.exception("MAILGUN küldés hiba to=%s subj=%r", to, subject)
        return False


def schedule_email(to: str, subject: str, text: str) -> None:
    """Fire-and-forget e-mail: azonnal visszatér, a küldés háttérben fut.

    Async request-handlerből hívandó (futó event loop kell). A taskra erős
    referenciát tartunk a GC ellen, a done-callback törli.
    """
    task = asyncio.create_task(send_email(to, subject, text))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

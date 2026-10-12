"""Mailgun (EU) háttér e-mail küldés.

A prod n8n SMTP-vel küld; a kód-magban Mailgun (EU endpoint) váltja ki.
A /chat válasz-latencyt NEM növeli: a tényleges HTTP POST háttérben fut
(`schedule_email` -> asyncio.create_task, fire-and-forget).

Guardrail: ha nincs konfigurált API-kulcs (üres vagy CHANGEME), nem küld —
csak logol. Hiba esetén logol, SOHA nem dob (a /chat mindig fusson tovább).
"""

import asyncio
import logging
import re

import httpx

from app.core.settings import get_settings

logger = logging.getLogger("cx.mailer")

# kulcs-értékek, amik "nincs konfigurálva"-t jelentenek
_DISABLED_KEYS = {"", "changeme"}

# erős referencia a háttér-taskokra (különben a GC eldobhatja őket futás közben)
_bg_tasks: set[asyncio.Task] = set()


def _enabled(settings) -> bool:
    return (settings.mailgun_api_key or "").strip().lower() not in _DISABLED_KEYS


def format_from(from_addr: str, name: str = "") -> str:
    """m112: feladó megjelenő névvel — '"Bolt neve" <noreply@...>'. A cím marad a mienk
    (SPF/DKIM a codexpress.hu-n), csak a megjelenő név változik. Üres név -> változatlan.
    A névből a fejléc-törő karakterek (idézőjel, <>, sortörés) kimaradnak."""
    addr = (from_addr or "").strip()
    if "<" in addr and ">" in addr:
        addr = addr[addr.index("<") + 1:addr.index(">")].strip()
    clean = " ".join(
        "".join(" " if ch in '"<>\\\r\n' else ch for ch in str(name or "")).split()
    )[:60]
    return f'"{clean}" <{addr}>' if clean else (from_addr or "")


_REPLY_RE = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[a-z]{2,}$", re.I)


def safe_reply_to(email) -> str:
    """m113: egyetlen, ervenyes e-mail-cim Reply-To-nak (pl. a latogato cime a lead-ertesitoben).
    Ervenytelen / tobb cim / fejlec-toro karakter -> '' (nincs Reply-To)."""
    e = str(email or "").strip()
    return e if (len(e) <= 254 and _REPLY_RE.match(e)) else ""


async def send_email(to: str, subject: str, text: str, reply_to: str = "", from_name: str = "") -> bool:
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
    data = {"from": format_from(settings.mailgun_from, from_name), "to": to, "subject": subject, "text": text}
    if (reply_to or "").strip():
        # m112: a vevő válasza a bolthoz menjen, ne a noreply-ra
        data["h:Reply-To"] = reply_to.strip()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, auth=("api", settings.mailgun_api_key), data=data)
            resp.raise_for_status()
        logger.info("MAILGUN elküldve to=%s subj=%r", to, subject)
        return True
    except Exception:  # noqa: BLE001 — e-mail hiba SOHA ne törje meg a /chat-et
        logger.exception("MAILGUN küldés hiba to=%s subj=%r", to, subject)
        return False


def schedule_email(to: str, subject: str, text: str, reply_to: str = "", from_name: str = "") -> None:
    """Fire-and-forget e-mail: azonnal visszatér, a küldés háttérben fut.

    Async request-handlerből hívandó (futó event loop kell). A taskra erős
    referenciát tartunk a GC ellen, a done-callback törli.
    """
    task = asyncio.create_task(send_email(to, subject, text, reply_to=reply_to, from_name=from_name))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

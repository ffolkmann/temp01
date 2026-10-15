"""Handoff-modul — élő segítségkérés: e-mail a lead_email-re + kanned válasz (collect_lead).

A prod `Handoff Email` + `Respond Handoff` node portja. Az e-mail Mailgunon (EU) megy,
HÁTTÉRBEN (a /chat válasz-latencyt nem növeli); a kanned válasz éles.
"""

import logging
from datetime import datetime, timezone

from app.core.mailer import schedule_email
from app.services.intent import HandoffIntent

logger = logging.getLogger("cx.handoff")

# a prod Respond Handoff válasza; m107: semleges címzett (nem minden tenant webshop)
HANDOFF_REPLY = (
    "Természetesen! 📨 Továbbítottam a beszélgetésünket a kollégáinknak. "
    "Kérlek, add meg az e-mail-címed (és ha szeretnéd, a telefonszámod), hogy mielőbb "
    "fel tudják venni veled a kapcsolatot."
)


async def send_handoff_email(
    client_id: str, intent: HandoffIntent, transcript: str | None = None,
    turns: list | None = None, bot_name: str = "Bot",
) -> None:
    """Élő segítségkérés értesítő a partnernek — Mailgunon, háttérben.

    `transcript`: a TELJES beszélgetés a messages naplóból (m22); ha nincs
    (üres session / DB-hiba), fallback a widget-küldött intent.transcript.
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    subject = f"Elo segitsegkeres - {client_id} chatbot"
    body_transcript = transcript or intent.transcript
    text = (
        "Egy latogato elo segitseget / munkatarsat kert a chatbotban.\n\n"
        f"Webshop: {client_id}\nOldal: {intent.page}\nIdopont: {now_iso}\n\n"
        f"--- TELJES BESZELGETES ---\n{body_transcript}\n\n"
        "Ha a latogato megadja az elerhetoseget, kulon lead-ertesitot is kuldunk."
    )
    # m118: ekezetes szoveg + formazott HTML (latogato/bot buborekok) - hiba eseten a regi sima level
    html_body = ""
    try:
        from app.services.leadmail import build_handoff_email
        pairs = [(getattr(t, "question", None), getattr(t, "answer", None)) for t in (turns or [])]
        subject, text, html_body = build_handoff_email(
            client_id=client_id, page=intent.page, when=datetime.now(timezone.utc),
            turns=pairs, bot_name=bot_name, transcript=body_transcript,
        )
    except Exception:  # noqa: BLE001
        logger.exception("m118 handoff-level formazas hiba, sima szoveg megy")
    logger.info("HANDOFF[%s] -> e-mail to=%s page=%s", client_id, intent.to, intent.page)
    logger.info("m118 handoff html: %d client=%s", 1 if html_body else 0, client_id)
    schedule_email(intent.to, subject, text, html=html_body)

"""Handoff-modul — élő segítségkérés: e-mail a lead_email-re + kanned válasz (collect_lead).

A prod `Handoff Email` + `Respond Handoff` node portja. Az e-mail Mailgunon (EU) megy,
HÁTTÉRBEN (a /chat válasz-latencyt nem növeli); a kanned válasz éles.
"""

import logging
from datetime import datetime, timezone

from app.core.mailer import schedule_email
from app.services.intent import HandoffIntent

logger = logging.getLogger("cx.handoff")

# a prod Respond Handoff válasza (bitre azonos)
HANDOFF_REPLY = (
    "Természetesen! 📨 Továbbítottam a beszélgetésünket a webshop munkatársának. "
    "Kérlek, add meg az e-mail-címed (és ha szeretnéd, a telefonszámod), hogy mielőbb "
    "fel tudják venni veled a kapcsolatot."
)


async def send_handoff_email(client_id: str, intent: HandoffIntent) -> None:
    """Élő segítségkérés értesítő a partnernek — Mailgunon, háttérben."""
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    subject = f"Elo segitsegkeres - {client_id} chatbot"
    text = (
        "Egy latogato elo segitseget / munkatarsat kert a chatbotban.\n\n"
        f"Webshop: {client_id}\nOldal: {intent.page}\nIdopont: {now_iso}\n\n"
        f"--- BESZELGETES ---\n{intent.transcript}\n\n"
        "Ha a latogato megadja az elerhetoseget, kulon lead-ertesitot is kuldunk."
    )
    logger.info("HANDOFF[%s] -> e-mail to=%s page=%s", client_id, intent.to, intent.page)
    schedule_email(intent.to, subject, text)

"""Handoff-modul — élő segítségkérés: e-mail a lead_email-re + kanned válasz (collect_lead).

A prod `Handoff Email` + `Respond Handoff` node portja. Fázis 1: az e-mail-küldés STUB
(csak logol), a kanned válasz éles. A valódi SMTP/connector a Fázis 3/5-ben (n8n marad
email-glue-nak), ahogy a leads modulnál is.
"""

import logging

from app.services.intent import HandoffIntent

logger = logging.getLogger("cx.handoff")

# a prod Respond Handoff válasza (bitre azonos)
HANDOFF_REPLY = (
    "Természetesen! 📨 Továbbítottam a beszélgetésünket a webshop munkatársának. "
    "Kérlek, add meg az e-mail-címed (és ha szeretnéd, a telefonszámod), hogy mielőbb "
    "fel tudják venni veled a kapcsolatot."
)


async def send_handoff_email(client_id: str, intent: HandoffIntent) -> None:
    """Élő segítségkérés értesítő a partnernek (STUB — logol)."""
    logger.info(
        "HANDOFF[%s] -> e-mail (stub) to=%s page=%s\n--- transcript ---\n%s",
        client_id, intent.to, intent.page, intent.transcript,
    )

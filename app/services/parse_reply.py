"""Parse Reply — a prod `Parse Reply` Code node 1:1 portja (lásd seed/prod_chat_logic.txt).

A modell egy JSON envelope-pal válaszol: {"reply": "...", "collect_lead": bool, "order_form": bool}.
Az első {...} blokkot parszoljuk; az `order_form` -> action='order_status_form' (prioritás),
különben `collect_lead` -> action='collect_lead'. Üres reply -> fallback + collect_lead.
"""

import json
import re
from dataclasses import dataclass

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_FALLBACK = (
    "Elnezest, most nem tudok valaszolni. Hagyd meg az e-mail-cimed, es egy kollegank "
    "hamarosan jelentkezik."
)


@dataclass
class ParsedReply:
    reply: str
    action: str | None = None


def parse_reply(text: str) -> ParsedReply:
    text = text or ""
    reply = text
    collect = False
    order_form = False

    m = _JSON_RE.search(text)
    if m:
        try:
            o = json.loads(m.group(0))
            if isinstance(o, dict):
                if o.get("reply"):
                    reply = o["reply"]
                if isinstance(o.get("collect_lead"), bool):
                    collect = o["collect_lead"]
                if isinstance(o.get("order_form"), bool):
                    order_form = o["order_form"]
        except (ValueError, TypeError):
            pass

    if not reply or not str(reply).strip():
        reply = _FALLBACK
        collect = True

    action: str | None = None
    if order_form:
        action = "order_status_form"
    elif collect:
        action = "collect_lead"
    return ParsedReply(reply=str(reply), action=action)

"""Parse Reply — a prod `Parse Reply` Code node portja + m24 keményítés.

A modell egy JSON envelope-pal válaszol: {"reply": "...", "collect_lead": bool, "order_form": bool}.
m24: a modell néha (a) markdown fence-be teszi a JSON-t, (b) plain-text bevezetőt ír elé,
(c) a max_tokens limiten CSONKOLVA hagyja (nincs záró " és }) — ilyenkor korábban a NYERS
szöveg ment ki a widgetbe (FO incidens, messages #64). Rétegzett kinyerés:
  1) első {...} blokk json.loads-szal (strict=False: a stringen belüli nyers újsor is átmegy);
  2) ha nem parszolható: a "reply" string-érték mentése regex-szel (csonka végű stringre is),
     a collect_lead/order_form flag-ek külön regex-szel;
  3) ha JSON-szerű scaffolding sincs: a teljes szöveg a reply (plain-text válasz).
Üres reply -> fallback + collect_lead.
"""

import json
import re
from dataclasses import dataclass

_JSON_RE = re.compile(r"\{[\s\S]*\}")
# "reply": "<escaped-string>" — a záró idézőjel OPCIONÁLIS (csonkolt kimenet)
_REPLY_RE = re.compile(r'"reply"\s*:\s*"((?:[^"\\]|\\[\s\S])*)')
_FLAG_RES = {
    "collect_lead": re.compile(r'"collect_lead"\s*:\s*(true|false)', re.I),
    "order_form": re.compile(r'"order_form"\s*:\s*(true|false)', re.I),
}

_FALLBACK = (
    "Elnezest, most nem tudok valaszolni. Hagyd meg az e-mail-cimed, es egy kollegank "
    "hamarosan jelentkezik."
)


@dataclass
class ParsedReply:
    reply: str
    action: str | None = None


def _unescape(s: str) -> str:
    """Escape-elt JSON-string tartalom -> szöveg; csonka escape a végén levágva."""
    while s.endswith("\\") and not s.endswith("\\\\"):
        s = s[:-1]
    try:
        return json.loads('"' + s + '"', strict=False)
    except ValueError:
        return s


def parse_reply(text: str) -> ParsedReply:
    text = text or ""
    reply = text
    collect = False
    order_form = False
    parsed = False

    m = _JSON_RE.search(text)
    if m:
        try:
            o = json.loads(m.group(0), strict=False)
            if isinstance(o, dict):
                parsed = True
                # parsolt envelope-nal a reply KIZAROLAG az envelope-bol jon; ures ->
                # a lenti fallback (korabban a nyers JSON ment ki - latens bug).
                reply = str(o.get("reply") or "")
                if isinstance(o.get("collect_lead"), bool):
                    collect = o["collect_lead"]
                if isinstance(o.get("order_form"), bool):
                    order_form = o["order_form"]
        except (ValueError, TypeError):
            pass

    if not parsed:
        # csonkolt / fence-elt / hibrid kimenet: a "reply" string mentése
        rm = _REPLY_RE.search(text)
        if rm:
            salvaged = _unescape(rm.group(1)).strip()
            if salvaged:
                reply = salvaged
                fm = _FLAG_RES["collect_lead"].search(text)
                if fm:
                    collect = fm.group(1).lower() == "true"
                fm = _FLAG_RES["order_form"].search(text)
                if fm:
                    order_form = fm.group(1).lower() == "true"

    if not reply or not str(reply).strip():
        reply = _FALLBACK
        collect = True

    action: str | None = None
    if order_form:
        action = "order_status_form"
    elif collect:
        action = "collect_lead"
    return ParsedReply(reply=str(reply), action=action)

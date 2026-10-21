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

# m114: a JSON-blokkon KIVULI szoveg mentese, ha az envelope reply-ja ures
_FENCE_RE = re.compile(r"```(?:json)?", re.I)

# m129 (K5): a modell a magyar „idezet" zaro straight-quote-jat NEM escape-eli, igy a
# json.loads elhasal, es a lusta _REPLY_RE az elso nyers "-nel elvagta a valaszt
# („Windows 11 Professional -> vege; 30 nap: 3 eset). Moho mentes a kovetkezo flag-kulcsig,
# ill. a zaro }-ig; csak ha ezek nincsenek (max_tokens-csonka), marad a lusta regex.
_REPLY_GREEDY_RE = re.compile(r'"reply"\s*:\s*"([\s\S]*?)"\s*,\s*"(?:collect_lead|order_form)"\s*:')
_REPLY_END_RE = re.compile(r'"reply"\s*:\s*"([\s\S]*?)"\s*\}\s*(?:```)?\s*$')
# m129: sima szoveg + JSON-farok ('...info@x.hu", "collect_lead": true, "order_form": false}')
_TAIL_RE = re.compile(
    r'"?\s*,\s*"(?:collect_lead|order_form)"\s*:\s*(?:true|false)'
    r'(?:\s*,\s*"(?:collect_lead|order_form)"\s*:\s*(?:true|false))?\s*\}?\s*(?:```)?\s*$', re.I)
# m129: max_tokens-nel elvagott markdown-link a valasz VEGEN ('- [Lenovo T23i](https://notebookstore.hu/lenovo-t23i-...')
_DANGLING_RE = re.compile(r'\[[^\]\n]*(?:\]\([^)\n]*)?$')
_UNQUOTED_RE = re.compile(r'(?<!\\)"')


def trim_dangling_link(text: str) -> tuple[str, bool]:
    """m129: ha a valasz egy felbehagyott markdown-linkkel ([nev](url-csonk) vegzodik, levagjuk
    a csonkot az utolso mondathatarig (. ! ? vagy ujsor). Ha nincs hatar, vagy 20 karakternel
    rovidebb maradna, valtozatlan. (max_tokens 2048; 30 nap: ~10 ilyen valasz, mind lista-vegi link.)"""
    t = (text or "").rstrip()
    m = _DANGLING_RE.search(t)
    if not m:
        return text, False
    head = t[:m.start()]
    cut = max(head.rfind(ch) for ch in (".", "!", "?", "\n"))
    if cut < 0:
        return text, False
    keep = head[:cut + 1].rstrip() if head[cut] != "\n" else head[:cut].rstrip()
    if len(keep) < 20:
        return text, False
    return keep, True
_M114_MIN_ALPHA = 15


def _outside_text(text: str, start: int, end: int) -> str:
    """A JSON-blokkon kivuli resz (fence-ek nelkul), vagy '' ha nem ertelmes szoveg."""
    rest = _FENCE_RE.sub("", (text[:start] + text[end:])).strip()
    if sum(1 for c in rest if c.isalpha()) < _M114_MIN_ALPHA:
        return ""
    return rest


_FALLBACK = (
    "Elnezest, most nem tudok valaszolni. Hagyd meg az e-mail-cimed, es egy kollegank "
    "hamarosan jelentkezik."
)


@dataclass
class ParsedReply:
    reply: str
    action: str | None = None
    note: str | None = None  # m114: "m114" = a JSON-on kivuli szoveg lett a valasz


def _unescape(s: str) -> str:
    """Escape-elt JSON-string tartalom -> szöveg; csonka escape a végén levágva."""
    while s.endswith("\\") and not s.endswith("\\\\"):
        s = s[:-1]
    try:
        return json.loads('"' + s + '"', strict=False)
    except ValueError:
        # m129: nem escape-elt " a stringben (magyar „idezet" zarasa) -> escape-elve ujra
        try:
            return json.loads('"' + _UNQUOTED_RE.sub('\\\\"', s) + '"', strict=False)
        except ValueError:
            return s


def parse_reply(text: str) -> ParsedReply:
    text = text or ""
    reply = text
    collect = False
    order_form = False
    parsed = False
    note = None

    m = _JSON_RE.search(text)
    if m:
        try:
            o = json.loads(m.group(0), strict=False)
            if isinstance(o, dict):
                parsed = True
                # parsolt envelope-nal a reply KIZAROLAG az envelope-bol jon; ures ->
                # a lenti fallback (korabban a nyers JSON ment ki - latens bug).
                reply = str(o.get("reply") or "")
                if not reply.strip():
                    # m99: a modell neha mas kulcs ala teszi a valaszt -> mentes
                    for _k in ("answer", "message", "response", "text", "valasz"):
                        _v = o.get(_k)
                        if isinstance(_v, str) and _v.strip():
                            reply = _v
                            break
                if not reply.strip():
                    # m114: a modell sima szovegben valaszolt, es UTANA (vagy elotte)
                    # egy ures reply-u / csak flag-es JSON-t is irt -> eddig a jo
                    # szoveg elveszett es a tartalek-valasz ment ki (7 nap: 6 eset,
                    # mind hibatlan termek-valasz). A blokkon kivuli szoveg a valasz.
                    _out = _outside_text(text, m.start(), m.end())
                    if _out:
                        reply = _out
                        note = "m114"
                if isinstance(o.get("collect_lead"), bool):
                    collect = o["collect_lead"]
                if isinstance(o.get("order_form"), bool):
                    order_form = o["order_form"]
        except (ValueError, TypeError):
            pass

    if not parsed:
        # csonkolt / fence-elt / hibrid kimenet: a "reply" string mentése
        # m129: eloszor moho mentes (a kovetkezo flag-kulcsig / zaro }-ig), csak utana lusta
        rm = _REPLY_GREEDY_RE.search(text) or _REPLY_END_RE.search(text)
        if rm:
            note = "m129q"
        else:
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
            else:
                note = None
        elif '"reply"' not in text:
            # m129: sima szoveg, amit a modell JSON-farokkal zart le, vagy JSON-escape-pel irt
            tm = _TAIL_RE.search(text)
            if tm and text[:tm.start()].strip():
                reply = text[:tm.start()].strip()
                note = "m129t"
                fm = _FLAG_RES["collect_lead"].search(text)
                if fm:
                    collect = fm.group(1).lower() == "true"
                fm = _FLAG_RES["order_form"].search(text)
                if fm:
                    order_form = fm.group(1).lower() == "true"
            elif '\\"' in text:
                reply = text.replace('\\"', '"')
                note = "m129e"

    if not reply or not str(reply).strip():
        reply = _FALLBACK
        collect = True

    action: str | None = None
    if order_form:
        action = "order_status_form"
    elif collect:
        action = "collect_lead"
    return ParsedReply(reply=str(reply), action=action, note=note)

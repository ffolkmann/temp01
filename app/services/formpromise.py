# -*- coding: utf-8 -*-
"""m116: urlap-igeret felismerese a bot valaszaban (stdlib-only, tiszta fuggvenyek).

Lelet (d13b, 30 nap, 3821 valasz): a prompt kifejezetten kiiratja a modellel, hogy
"a megjeleno urlapon add meg a rendelesszamot ...", es kozben order_form=true-t ker.
A modell neha a mondatot megirja, a flaget nem -> az urlap NEM jelenik meg, a latogato
egy nem letezo urlapot keres (7 eset, ahol a sessionben urlap sosem volt). A kod-szintu
osszhang-or: ha a valasz IGERI az urlapot, az urlap jelenjen meg.

Csak a JOVOBE mutato, KONKRET igeret szamit ("a megjeleno / alabbi / lenti urlapon").
Nem szamit: feltételes ajanlat ("szolj, es megjelenitek egy urlapot"), visszautalas a mar
latott urlapra ("a fenti urlapon"), a bolt sajat urlap-oldala linkkel ([...urlap...](url)).
"""

import re

_PROMISE_RE = re.compile(
    r"\b(megjelen[őo]|al[áa]bbi|lenti|felugr[óo])\s+(?:\S+\s+){0,1}[űu]rlap", re.I)
_LINKTEXT_RE = re.compile(r"\[[^\]\n]*\]\([^)\s]*\)")
_ORDER_RE = re.compile(r"rendel[ée]s\s*sz[áa]m|rendel[ée]s(?:ed|e)?\s+[áa]llapot|rendel[ée]s", re.I)
_LEAD_RE = re.compile(r"el[ée]rhet[őo]s[ée]g|e-?mail|telefon|kapcsolat", re.I)


# m130 (K6): a bot SZOVEGBEN keri az elerhetoseget ("add meg az e-mail-cimedet es a
# telefonszamodat, es egy kollega felveszi veled a kapcsolatot"), de collect_lead flag nelkul
# -> nem jelenik meg az urlap. Meres (d21g/k6_scan.py, 30 nap, 3538 valasz): 219 ilyen keres,
# ebbol 100 urlap NELKUL (46%); 11-nel a latogato a chatbe gepelte az e-mailt (m100 fogta),
# a tobbi elveszett. Felszolito ("add meg / ird meg / hagyd meg|itt / kuldd el / adj meg") es
# felteteles ("ha megadod / ha szeretned, add meg") alak; a targy e-mail-CIM / telefonszam /
# elerhetoseg (a puszta "e-mailben" nem, mert az a bolt sajat cimere utal). Nem szamit:
# tiltas ("ne add meg"), link-szoveg, a bolt sajat cime.
_CONTACT_OBJ = (r"(?:az?\s+)?(?:e-?mail[\s-]*c[ií]m\w*|email[\s-]*c[ií]m\w*|telefonsz[áa]m\w*|"
                r"el[ée]rhet[őo]s[ée]g\w*|kapcsolati\s+adat\w*)")
_CONTACT_IMP_RE = re.compile(
    r"\b(?:add\s+meg|[ií]rd\s+meg|[ií]rd\s+be|hagyd\s+(?:meg|itt)|k[üu]ldd\s+el|oszd\s+meg|adj\s+meg)"
    r"\s+(?:nek[üu]nk\s+|itt\s+|k[ée]rlek\s+|nekem\s+)?(?:egy\s+)?" + _CONTACT_OBJ, re.I)
_CONTACT_COND_RE = re.compile(
    r"\bha\s+(?:megadod|megadsz|le[ií]rod|[ií]rsz|hagysz|hagyod|k[üu]ld(?:esz|ed)|"
    r"szeretn[ée]d,?\s+(?:add|[ií]rd)\s+meg)\s+(?:nek[üu]nk\s+|itt\s+)?(?:egy\s+)?" + _CONTACT_OBJ, re.I)
_CONTACT_NEG_RE = re.compile(r"\b(?:ne|nem|sose|soha)\s*$", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def requested_contact(reply: str) -> bool:
    """m130: True, ha a valasz a LATOGATOTOL keri az e-mail-cimet / telefonszamat / elerhetoseget."""
    s = _LINKTEXT_RE.sub(" ", str(reply or ""))
    s = _EMAIL_RE.sub(" ", s)
    for rx in (_CONTACT_IMP_RE, _CONTACT_COND_RE):
        for m in rx.finditer(s):
            before = s[max(0, m.start() - 12): m.start()]
            if _CONTACT_NEG_RE.search(before):
                continue
            return True
    return False


def promised_form(reply: str) -> str | None:
    """'order' | 'lead' | None - milyen urlapot igér a valasz."""
    s = _LINKTEXT_RE.sub(" ", str(reply or ""))
    m = _PROMISE_RE.search(s)
    if not m:
        return None
    win = s[max(0, m.start() - 200): m.end() + 200]
    if _ORDER_RE.search(win):
        return "order"
    if _LEAD_RE.search(win):
        return "lead"
    return None

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

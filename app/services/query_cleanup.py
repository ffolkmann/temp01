"""Termek-query tisztitas a BEAGYAZAS elott (m36). PURE modul.

Eles eset (fishingoutlet): "Szia , shimano bojlit keresek" -> a dense top-30
szemetbe fullad (napszemuveg, zsinoralafutasgatlo), a Shimano bojlik kiesnek;
ugyanez "szia shimano bojli" alakban 8/8 talalat. A koszones, a lebego irasjelek
es a toltelekigek ("keresek", "szeretnek") zajt visznek az embeddingbe.

Ez a modul CSAK a beagyazando szoveget tisztitja: a latogato uzenete valtozatlanul
megy az LLM-nek es a lexikai reranknak. Konzervativ: kis, fix stoplista; ha a
tisztitas utan tul rovid a szoveg, az eredetit adja vissza.
"""

from __future__ import annotations

import re
import unicodedata

# koszonesek — csak az uzenet ELEJEN (elso nehany token)
_GREET = {
    "szia", "sziasztok", "szevasz", "szervusz", "szerbusz", "hello", "hallo", "helo",
    "hali", "hey", "hi", "udv", "udvozlom", "jo", "napot", "reggelt", "estet",
    "kivanok", "kedves",
}
# toltelekigek / udvariassagi kifejezesek — barhol
_FILLER = {
    "keresek", "keresnek", "keresem", "keresnem", "szeretnek", "szeretnem",
    "kerek", "kernek", "kerem", "kellene", "kene", "vennem", "vennek",
    "vasarolnek", "erdekelne", "erdekelnenek",
}

_PUNCT_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)


def _fold(s: str) -> str:
    s = str(s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def product_query_cleanup(text: str) -> str:
    """Koszones (elol), toltelekigek es maganyos irasjel-tokenek eltavolitasa.

    A kimeneti tokenek az EREDETI alakjukban maradnak (ekezettel, raggal) —
    csak a zaj-tokenek esnek ki. Ha a maradek tul rovid, az eredeti jon vissza.
    """
    raw = str(text or "")
    tokens = raw.split()
    if not tokens:
        return raw

    out: list[str] = []
    at_start = True
    for tok in tokens:
        if _PUNCT_ONLY.match(tok):
            continue  # maganyos "," "!" "?" token: mindig zaj
        f = _fold(tok).strip(".,;:!?")
        if at_start and f in _GREET:
            continue  # koszones az elejen
        at_start = False
        if f in _FILLER:
            continue
        out.append(tok)

    cleaned = " ".join(out)
    # tul agressziv tisztitas eseten (pl. az uzenet CSAK koszones) az eredeti marad
    if len(cleaned) < 3:
        return raw
    return cleaned

"""m79c: parameter-kinyeres (Qdrant payload) + kerdes-oldali megkotes-detektor.

Stdlib-only, fajlbol betoltheto (minta: selfrepeat/linkterm). Pilot:
notebookstore/webdoc taska-attributumok (colmeret/tipus/szin) + kategoria-nev.
Konzervativ elv: csak egyertelmu jelre adunk megkotest, es a kerdes-oldali
Qdrant-szures CSAK taska-temaju kerdesnel aktiv (bag-gate) -- "fekete pentek"
ne szurjon szinre. Ures szurt eredmenyre a hivo (retrieval) szuretlen
fallbackot ad.

m79b-nb: notebook-temaju kerdesnel LINK-oldali megkotesek (kijelzo_meret_gte,
usage) -- ezeket a build_filter_conditions szandekosan NEM forditja
Qdrant-feltetelle (nincs hozzajuk payload-mezo), csak a linkfacet hasznalja
a fasetta/SEO zaro-linkhez.
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["extract_params", "detect_constraints", "build_filter_conditions"]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


# --- sync-oldali kinyeres (termeknev + text) ---

# webdoc nev-minta: 'Maximum 17.3" meretu notebookokhoz' (fold utan)
_RE_MERET_NAME = re.compile(r"maximum\s+(\d{1,2}(?:[.,]\d)?)\s*[\"\u2033']?\s*meretu")
# text-minta: 'Kategoria: Kiegeszitok > Notebook taska, hatizsak.' (eredeti, ekezetes)
_RE_CATEGORY = re.compile(r"kateg[o\u00f3]ria:[ \t]*([^\n]+)", re.IGNORECASE)

_COLORS = (
    "fekete", "feher", "szurke", "acelszurke", "kek", "zold", "piros", "sarga",
    "barna", "lila", "rozsaszin", "pink", "narancssarga", "narancs", "bordo",
    "bezs", "arany", "ezust", "turkiz",
)


def _parse_num(whole: str, frac: str | None = None) -> float:
    if frac is not None:
        return float(f"{whole}.{frac}")
    return float(whole.replace(",", "."))


def extract_params(name: str, text: str = "") -> dict:
    """Uj payload-mezok a termeknevbol/textbol. Csak a biztosan kinyert kulcsok."""
    out: dict = {}
    fn = _fold(name)

    m = _RE_MERET_NAME.search(fn)
    if m:
        out["p_max_meret"] = _parse_num(m.group(1))

    if "hatizsak" in fn or "backpack" in fn:
        out["p_tipus"] = "hatizsak"
    elif "sleeve" in fn or re.search(r"\btok\b", fn):
        out["p_tipus"] = "tok"
    elif "taska" in fn:
        out["p_tipus"] = "valltaska"

    # szin: az utolso ' ... szinben' szegmens szavai (tobbszavas szin is: 'acelszurke',
    # 'tie dye batikolt mintas'); szeparator: kotojel vagy vesszo
    if "szinben" in fn:
        seg = re.split(r"[-,]", fn)
        for part in reversed(seg):
            if "szinben" in part:
                words = part.split("szinben")[0].split()
                if words:
                    out["p_szin"] = " ".join(words[-4:]).strip()
                break

    if text:
        mc = _RE_CATEGORY.search(text)
        if mc:
            cat = mc.group(1)
            # m79b: a text egysoros -> a kategoria-nev az elso '. ' hatarig tart
            cut = cat.find(". ")
            if cut != -1:
                cat = cat[:cut]
            out["category"] = cat.strip().rstrip(".").strip()
    return out


# --- kerdes-oldali megkotes-detektor (determinisztikus, konzervativ) ---

_RE_BAG_TOPIC = re.compile(r"taska|hatizsak|\btok\b|sleeve")
# m79b-nb: notebook/laptop tema -- csak link-oldali megkotesekhez
_RE_NB_TOPIC = re.compile(r"notebook|laptop|ultrabook")
# '17', '17,3', '17.3' + egyertelmu egyseg/rag: '"', col/colos, inch, huvelyk, -os/-es
_RE_MERET_Q = re.compile(
    r"\b(1[0-8])(?:[.,](\d))?\s*(?:[\"\u2033']|col\w*|inch\w*|huvelyk\w*|-?os\b|-?es\b)"
)
# m79b-nb: linkfacet 'felhasznalas-jellege' ertekei (a superlative.detect_usage
# parja, itt duplikalva az importfuggetlenseg miatt)
_USAGE_WORDS = (
    ("uzleti", "uzleti"), ("otthoni", "otthoni"), ("gamer", "gamer"),
    ("gaming", "gamer"), ("grafikus", "grafikus"), ("atalakithato", "atalakithato"),
)


def _meret_from_q(fm: str) -> float | None:
    """Colmeret a kerdesbol; a 'windows 11-es' szoftver-verzio NEM meret."""
    for m in _RE_MERET_Q.finditer(fm):
        pre = fm[max(0, m.start() - 9):m.start()]
        if "windows" in pre:
            continue
        return _parse_num(m.group(1), m.group(2))
    return None


def detect_constraints(message: str) -> dict:
    """Egyertelmu megkotesek a kerdesbol.

    Taska-temanal (bag-gate, elsobbseg): p_max_meret_gte / p_tipus / p_szin --
    ezek a Qdrant-szurest IS hajtjak (build_filter_conditions).
    Notebook-temanal (m79b-nb): kijelzo_meret_gte / usage -- CSAK a zaro
    fasetta-linkhez (linkfacet), Qdrant-szures nincs beloluk.
    """
    fm = _fold(message)
    if _RE_BAG_TOPIC.search(fm):
        out: dict = {}
        v = _meret_from_q(fm)
        if v is not None:
            out["p_max_meret_gte"] = v

        if "hatizsak" in fm or "backpack" in fm:
            out["p_tipus"] = "hatizsak"
        elif "valltaska" in fm:
            out["p_tipus"] = "valltaska"
        elif "sleeve" in fm or re.search(r"\btok\b", fm):
            out["p_tipus"] = "tok"
        # generikus 'taska' -> NINCS tipus-szures (a hatizsak is taska)

        for c in _COLORS:
            if re.search(r"\b" + c + r"\b", fm):
                out["p_szin"] = c
                break
        return out

    if _RE_NB_TOPIC.search(fm):
        out = {}
        v = _meret_from_q(fm)
        if v is not None:
            out["kijelzo_meret_gte"] = v
        for word, val in _USAGE_WORDS:
            if re.search(r"\b" + word, fm):
                out["usage"] = val
                break
        return out

    return {}


def build_filter_conditions(cons: dict) -> list[dict]:
    """Qdrant must-feltetelek a detect_constraints kimenetebol. Ures dict -> ures lista.

    Csak a p_* kulcsokbol epit feltetelt -- a notebook-agi kulcsok
    (kijelzo_meret_gte, usage) szandekosan kimaradnak (nincs payload-mezojuk).
    """
    must: list[dict] = []
    if not cons:
        return must
    v = cons.get("p_max_meret_gte")
    if isinstance(v, (int, float)):
        must.append({"key": "p_max_meret", "range": {"gte": float(v)}})
    if cons.get("p_tipus"):
        must.append({"key": "p_tipus", "match": {"value": cons["p_tipus"]}})
    if cons.get("p_szin"):
        must.append({"key": "p_szin", "match": {"value": cons["p_szin"]}})
    return must

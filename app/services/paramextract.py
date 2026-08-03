"""m79c: parameter-kinyeres (Qdrant payload) + kerdes-oldali megkotes-detektor.

Stdlib-only, fajlbol betoltheto (minta: selfrepeat/linkterm). Pilot:
notebookstore/webdoc taska-attributumok (colmeret/tipus/szin) + kategoria-nev.
Konzervativ elv: csak egyertelmu jelre adunk megkotest, es a kerdes-oldali
szures CSAK taska-temaju kerdesnel aktiv (bag-gate) -- "fekete pentek" ne
szurjon szinre. Ures szurt eredmenyre a hivo (retrieval) szuretlen fallbackot ad.
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
# '17', '17,3', '17.3' + egyertelmu egyseg/rag: '"', col/colos, inch, huvelyk, -os/-es
_RE_MERET_Q = re.compile(
    r"\b(1[0-8])(?:[.,](\d))?\s*(?:[\"\u2033']|col\w*|inch\w*|huvelyk\w*|-?os\b|-?es\b)"
)


def detect_constraints(message: str) -> dict:
    """Egyertelmu megkotesek a kerdesbol. CSAK taska-temanal (bag-gate) ad vissza barmit.

    Kulcsok: p_max_meret_gte (float), p_tipus (str), p_szin (str).
    """
    fm = _fold(message)
    if not _RE_BAG_TOPIC.search(fm):
        return {}
    out: dict = {}

    m = _RE_MERET_Q.search(fm)
    if m:
        out["p_max_meret_gte"] = _parse_num(m.group(1), m.group(2))

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


def build_filter_conditions(cons: dict) -> list[dict]:
    """Qdrant must-feltetelek a detect_constraints kimenetebol. Ures dict -> ures lista."""
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

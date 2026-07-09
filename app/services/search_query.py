"""Bolti kereső query-építés — PURE modul (nincs app-függősége, így önállóan tesztelhető).

A bolti keresők AND-elik a szavakat, ezért a nyers üzenet ("szeretnék venni egy ... kezdőként")
tipikusan 0 találat. Query-kaszkád:
  q1: stopszó-szűrt + tárgyrag-vágott tartalomszavak (max 4)
  q2: ugyanaz szűretlenül (ha eltér)
  q3: a leghosszabb szó önmagában — VÉGSŐ mentsvár

A q3 (egyetlen szó) platformfüggően káros: a WebDoc frontend-kereső részstringre illeszt a
termék NEVÉBEN, így a "laptop" szóra notebooktáskákat ad vissza ("... Laptop Casual
Toploader Notebooktáska"). Ezért webdocnál a q3-at elhagyjuk — inkább ne legyen találat,
mint zaj a promptban. (Ha az üzenetben eleve csak EGY tartalomszó van, az az egy marad.)
"""

import re

_STOPWORDS = {
    "a", "az", "egy", "es", "és", "de", "hogy", "ha", "el", "is", "mar", "már", "meg", "még",
    "szeretnek", "szeretnék", "szeretnem", "szeretném", "keresek", "kerdeznem", "kérdeznem",
    "venni", "vennék", "vennek", "vasarolni", "vásárolni", "erdekelne", "érdekelne", "erdekel", "érdekel",
    "ajanlasz", "ajánlasz", "ajanl", "ajánl", "ajanlani", "mit", "mi", "milyen", "melyik", "hol",
    "van", "vane", "van-e", "lenne", "kellene", "kene", "kéne", "kell", "tudsz", "tudnal", "tudnál",
    "kezdo", "kezdő", "kezdokent", "kezdőként", "kezdoknek", "kezdőknek", "vagyok", "vagyunk",
    "nekem", "nekunk", "nekünk", "hozzam", "hozzám", "valami", "valamit", "olcso", "olcsó",
    "jo", "jó", "legjobb", "szerintetek", "szerinted", "koszi", "köszi", "koszonom", "köszönöm",
}

# Ezeknél a platformoknál NEM megy ki az egyszavas végső mentsvár query (m29 fázis 2).
NO_SINGLE_WORD_FALLBACK = {"webdoc"}


def _stem(w: str) -> str:
    """Minimal magyar targyrag-vagas a bolti LIKE-kereso kedveert (botot -> bot, halot -> halo)."""
    if len(w) > 4:
        for suf in ("okat", "eket", "akat", "öket"):
            if w.endswith(suf):
                return w[: -len(suf)]
        for suf in ("ot", "et", "at", "öt"):
            if w.endswith(suf):
                return w[: -len(suf)]
        # mgh+t es msh+t targyrag is (hálót -> háló, halat mar fent);
        # dupla-t (szett, watt) NEM rag, marad
        if w.endswith("t") and not w.endswith("tt"):
            return w[:-1]
    return w


def build_queries(message: str) -> list[str]:
    words = re.findall(r"[\w\-]+", (message or "").lower())
    content = [w for w in words if w not in _STOPWORDS and len(w) > 2 and not w.isdigit()]
    # szammal kezdodo tagok ("45-ös", "8-as") gyilkos AND-feltetelek a bolti keresoben
    # -> a fo query-kbol kihagyjuk, csak a szoveges torzs megy
    core = [w for w in content if not w[0].isdigit()]
    base = core or content
    out: list[str] = []
    if base:
        q1 = " ".join(_stem(w) for w in base[:4])
        out.append(q1)
        q2 = " ".join(base[:4])
        if q2 not in out:
            out.append(q2)
        if len(base) > 1:
            q3 = _stem(sorted(base, key=len, reverse=True)[0])
            if q3 and q3 not in out:
                out.append(q3)
    if not out:
        out.append((message or "").strip()[:120])
    return out[:3]


def search_queries(platform: str, message: str) -> list[str]:
    """A bolti keresonek kikuldendo query-kaszkad, platformfuggoen szurve."""
    qs = build_queries(message)
    plat = (platform or "").strip().lower()
    if plat in NO_SINGLE_WORD_FALLBACK and len(qs) > 1:
        multi = [q for q in qs if len(q.split()) > 1]
        qs = multi or qs[:1]
    return qs

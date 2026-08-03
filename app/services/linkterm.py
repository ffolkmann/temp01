"""m79a: rovid, determinisztikus kereso-term a zaro linkhez.

Elsodleges forras: a kontextus-talalatok termeknevei (a bolt sajat
elnevezese -> garantalt talalat a bolt keresojeben). A nevek
leggyakoribb tartalmas tokenje nyer, ha a nevek legalabb feleben
szerepel. Fallback: a kerdes toltelekszo-mentes, max 2 tartalmas
szava. Csak stdlib — tesztbol kozvetlenul fajl-betoltheto.
"""
import re
import unicodedata
from collections import Counter

_FILLER = {
    "olyan", "amibe", "amihez", "amire", "amiben", "ami", "aki", "egy",
    "is", "es", "meg", "hogy", "bele", "belefer", "illik", "valo", "jo",
    "kell", "kene", "lehet", "van", "hozza", "neki", "ala", "melyik",
    "milyen", "mennyi", "the",
}
_NAME_STOP = {
    "maximum", "meretu", "notebookokhoz", "laptopokhoz", "szinben",
    "szinu", "colos", "tipusu", "darab",
}


def _fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c))


def _tokens(s):
    return re.findall(r"\w+", str(s or ""), flags=re.UNICODE)


def _name_term(names, brands=None):
    bstop = {_fold(b) for b in (brands or []) if b}
    cnt = Counter()
    best_form = {}
    n_names = 0
    for nm in (names or [])[:6]:
        n_names += 1
        seen = set()
        for tok in _tokens(nm):
            f = _fold(tok)
            if len(f) < 4 or f in _NAME_STOP or f in bstop:
                continue
            if any(ch.isdigit() for ch in f):
                continue
            if f in seen:
                continue
            seen.add(f)
            cnt[f] += 1
            best_form.setdefault(f, tok)
    if not cnt or not n_names:
        return ""
    f, c = max(cnt.items(), key=lambda kv: (kv[1], len(kv[0])))
    if c * 2 >= n_names:
        return best_form[f]
    return ""


def _topic_term(message):
    out = []
    for tok in _tokens(message):
        f = _fold(tok)
        if len(f) < 3 or f in _FILLER or f.startswith("leg"):
            continue
        if any(ch.isdigit() for ch in f):
            continue
        out.append(tok)
        if len(out) == 2:
            break
    return " ".join(out)


def link_search_term(message, hit_names=None, brands=None):
    t = _name_term(hit_names or [], brands)
    if t:
        return t
    return _topic_term(message)

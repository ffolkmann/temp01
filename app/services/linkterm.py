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
    # m95: kerdes-keret es udvarias-frazis szavak — a fallback topic-term ne
    # ezekbol epuljon (a keresoben ertelmetlen "term" lenne)
    "szeretnek", "szeretnem", "szeretne", "szeretnank", "hogyan", "tudom",
    "tudok", "tudsz", "tudna", "tudnal", "koszonom", "koszi", "erdeklodnek",
    "erdeklodom", "erdeklodni", "erdekelne", "rendelni", "rendelem",
    "megrendelni", "megrendelem", "kerdeznem", "kerdezni", "kerdesem",
    "kerdes", "udvozlom", "udv", "szia", "sziasztok", "hello", "helo",
    "hali", "jonapot", "napot", "kivanok", "elore", "kerem", "kerek",
    "mikor", "mennyibe", "ugye", "azt", "ezt", "itt", "ott", "akarok",
    "akarom", "csak",
}
_NAME_STOP = {
    "maximum", "meretu", "notebookokhoz", "laptopokhoz", "szinben",
    "szinu", "colos", "tipusu", "darab",
    # m79b: notebook-nevek gyakori zaj-tokenjei ("Magyar billentyuzettel",
    # "3 ev garanciaval") ne nyerjenek keresotermkent
    "billentyuzet", "billentyuzettel", "magyar", "garancia", "garanciaval",
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


def _derivable(term, text):
    """m95: a term legalabb egy (>=3 betus) tokenje resz-szo egyezessel
    szerepel-e a szovegben (a latogato altal irt szavakban)."""
    tt = [t for t in _tokens(_fold(term)) if len(t) >= 3]
    qt = [t for t in _tokens(_fold(text)) if len(t) >= 3]
    for a in tt:
        for b in qt:
            if a in b or b in a:
                return True
    return not tt


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


def link_search_term(message, hit_names=None, brands=None, context=None):
    """m95: ha `context` adott (a latogato aktualis + korabbi uzenetei), a
    nev-alapu term csak akkor ervenyes, ha abbol levezetheto — kulonben a
    pool zajanak tekintjuk (pl. "jelgenerator" kerdesre a forrasztopakas
    talalatnevek), es a kerdes-alapu topicra esunk vissza. Ures visszateres
    = a hivo NE tegyen ki zaro-linket. context=None: regi viselkedes."""
    t = _name_term(hit_names or [], brands)
    if t and (context is None or _derivable(t, context)):
        return t
    return _topic_term(message)

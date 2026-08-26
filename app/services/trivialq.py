"""m94: „nem valódi kérdés" felismerés a megválaszolatlan-listához.

Miért: a megválaszolatlan riportba bekerülnek az udvariassági fordulatok, a
szolgáltatás-parancsok és a lead-űrlap törmelékei is („szia", „köszönöm szépen",
„/clear", „54861", e-mail cím), ezért a szám felhígul, és az ügyfél nem tudja,
hol van VALÓDI tudáshiány. Ezek nem tudásbázis-hiányok, hanem a beszélgetés zaja.

Tervezési elvek:
  * TISZTA modul (stdlib), a hívó adja be a szöveget -> ugyanaz a logika fut
    írás- és olvasás-oldalon, nem drifthetnek szét.
  * KONZERVATÍV: kétes esetben MARADJON a listán. Inkább legyen benne pár
    udvariassági sor, mint hogy egy valódi tudáshiány eltűnjön.
  * Az `ertem` szándékosan NINCS a token-listában: a „nem értem" valódi jelzés
    arról, hogy a válasz nem volt érthető — az maradjon látható.
  * Az `es`/`meg`/`is` szándékosan NINCS a token-listában: az ÉLES adaton az
    „és még?" (valódi folytatás-kérdés) rájuk esett volna ki.
"""

import re
import unicodedata

# egész üzenetként semmitmondó, normalizált alakok
_EXACT = {
    # köszönés
    "szia", "sziasztok", "szevasz", "hello", "hellosztok", "helo", "hali",
    "csa", "csao", "csumi", "udv", "udvozlom", "udvozletem", "udvozlet",
    "jo napot", "jo napot kivanok", "jo reggelt", "jo estet", "jo ejszakat",
    "szep napot", "szep estet", "kellemes napot",
    # köszönet
    "koszonom", "koszonom szepen", "koszi", "koszi szepen", "kosz", "koszonjuk",
    "koszonom a segitseget", "koszonom a valaszt", "koszonom szepen a segitseget",
    "nagyon szepen koszonom", "halas koszonet",
    # nyugtázás
    "ok", "oke", "okay", "okes", "rendben", "rendben van", "rendben koszonom",
    "igen", "nem", "jo", "jol van", "aha", "ertem", "remek", "szuper", "tokeletes",
    "nagyszeru", "erdekes", "vilagos",
    # elköszönés
    "viszlat", "viszontlatasra", "minden jot", "szia koszonom", "ciao", "bye",
    # angol
    "hi", "hey", "thanks", "thank you", "thx", "ty", "ok thanks", "good morning",
    "good evening", "goodbye", "yes", "no", "okay thanks",
    # teszt-zaj (a sajat probaink)
    "teszt", "test", "proba", "tesztelek", "testing",
}

# ha az üzenet KIZÁRÓLAG ezekből a szavakból áll, szintén nem tudáshiány
_TOKENS = {
    "szia", "sziasztok", "hello", "helo", "hi", "hey", "udv", "udvozlom", "udvozletem",
    "koszonom", "koszonjuk", "koszi", "kosz", "koszonet", "szepen", "nagyon", "halas",
    "thanks", "thank", "you", "thx",
    "a", "az",
    "segitseget", "segitseg", "valaszt", "valasz",
    "viszlat", "viszontlatasra", "ciao", "bye", "minden", "jot",
    "jo", "szep", "kellemes", "napot", "reggelt", "estet", "ejszakat", "kivanok",
    "rendben", "ok", "oke", "okay", "igen", "nem", "remek", "szuper", "tokeletes",
    "nagyszeru", "aha", "hmm",
}

_MAX_TOKENS = 5          # ennél hosszabb mondatot már nem minősítünk zajnak
_NOT_A_LETTER = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_HAS_ALPHA = re.compile(r"[^\W\d_]", re.UNICODE)


def normalize(q: str) -> str:
    """Kisbetűs, ékezet nélküli, központozás nélküli alak — csak összehasonlításra."""
    s = unicodedata.normalize("NFKD", str(q or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _NOT_A_LETTER.sub(" ", s.lower())
    return _WS.sub(" ", s).strip()


def is_command(q: str) -> bool:
    """Szolgáltatás-parancs (`/clear`, `/reset`) — sosem tudáshiány."""
    return str(q or "").strip().startswith("/")


def is_trivial(q: str) -> bool:
    """True, ha az üzenet NEM valódi kérdés (udvariasság, nyugtázás, parancs, űrlap-törmelék)."""
    raw = str(q or "").strip()
    if not raw:
        return True
    if is_command(raw):
        return True
    if _EMAIL.match(raw):          # lead-urlap: e-mail cim
        return True
    n = normalize(raw)
    if not n:                      # csak emoji / központozás / szimbólum
        return True
    if len(n) <= 1:                # egyetlen karakter ("M", "W") — sosem kérdés
        return True
    if not _HAS_ALPHA.search(n):   # csak szám: rendelésszám, telefonszám, irányítószám
        return True
    if n in _EXACT:
        return True
    toks = n.split()
    if len(toks) <= _MAX_TOKENS and all(t in _TOKENS for t in toks):
        return True
    return False

"""CX SmartSearch — AI-valasz a keresoben: tiszta mag (S6).

A widget MAR megtalalta a top talalatokat a kliens-oldali indexbol, ezert itt NEM
kereses van, hanem "valaszd ki es indokold": a jelolt termekeket a widget kuldi fel,
az LLM csak valogat kozuluk es ir 2-3 mondat indoklast.

Ebbol kovetkezik a ket legfontosabb szabaly:
  1. A valasz-szovegben NEM lehet ar/szam — az arat es a keszletet a widget rajzolja
     ki az indexbol. Ha az LLM megis arazna, azt a mondatot kidobjuk (strip_prices).
     Elavult ar kimondasa bizalmi es jogi kockazat; promptban kerni nem garancia.
  2. Csak olyan termek kerulhet a valaszba, amit a widget kuldott ES raktaron van
     (a pid-ek feherlistara mennek) — igy hallucinalt termek nem jelenhet meg.

"Good enough" kuszob: ha nem marad legalabb 1 ervenyes termek, NINCS valasz-sav
(inkabb semmi, mint altalanos okoskodas).

STDLIB ONLY — fajlbol betoltve tesztelheto, mint a searchcfg/searchstats.
"""

import json
import re
import unicodedata

MAX_CANDIDATES = 12
MAX_PICKS = 3
MAX_ANSWER_CHARS = 320
MAX_SENTENCES = 3
MIN_QUESTION_WORDS = 3

# Kerdo- es tanacskero szavak. Csak 3+ szavas beirasnal szamit (a "mi" onmagaban
# marka-toredek is lehet), es a ragozas miatt tovekent illesztunk.
QUESTION_STEMS = (
    "mi", "mit", "mik", "milyen", "melyik", "mennyi", "mekkora", "hany", "hány",
    "hogyan", "hol", "mikor", "kinek", "miert", "miért", "mire", "mihez", "mivel",
    "kell", "lehet", "erdemes", "érdemes", "ajanl", "ajánl", "javasol", "keres",
    "szeretn", "tudtok", "tudsz", "illik", "passzol", "kompatibilis", "alkalmas",
    "jobb", "legjobb", "kulonbseg", "különbség", "valaszt", "választ", "bir", "bír",
)


def _fold(text):
    """Kisbetus, ekezet nelkuli alak (a tovek igy egyszeruen illeszthetok)."""
    s = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def words(text):
    return [w for w in re.split(r"[^0-9a-z]+", _fold(text)) if w]


def is_question(q):
    """Kerdes- vagy tanacskero-jellegu beiras (konzervativ: 3+ szo vagy kerdojel)."""
    s = str(q or "").strip()
    if not s:
        return False
    if "?" in s:
        return True
    w = words(s)
    if len(w) < MIN_QUESTION_WORDS:
        return False
    stems = tuple(_fold(x) for x in QUESTION_STEMS)
    return any(word.startswith(stems) for word in w)


def needs_answer(q, total, force=False):
    """Fusson-e AI-valasz: kerdes-jellegu VAGY nincs jo talalat (0). force = demo-kapcsolo."""
    if force:
        return bool(str(q or "").strip())
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return bool(str(q or "").strip()) and (is_question(q) or total <= 0)


def norm_q(q):
    """Cache-kulcs: kisbetus, ekezet nelkuli, tomoritett szokoz."""
    return " ".join(words(q))[:120]


# --------------------------------------------------------------------------- #
# jeloltek (a widget kuldi fel az indexbol)
# --------------------------------------------------------------------------- #
def clean_candidates(items, only_available=True):
    """Nyers jelolt-lista -> tisztitott, korlatozott lista.

    Egy jelolt: {"i": pid, "n": nev, "a": keszlet, "c": kategoria, "b": marka,
    "x": rovid parameter-szoveg}. Az arat NEM adjuk az LLM-nek: nem kell hozza,
    es igy nem is tud vele hibazni.
    """
    out = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        pid = str(it.get("i") or it.get("pid") or "").strip()
        name = " ".join(str(it.get("n") or it.get("name") or "").split())[:120]
        if not pid or not name:
            continue
        avail = it.get("a", it.get("available", 1))
        if only_available and not (avail in (1, True, "1", "true") or avail is None):
            continue
        out.append({
            "i": pid,
            "n": name,
            "c": " ".join(str(it.get("c") or "").split())[:60],
            "b": " ".join(str(it.get("b") or "").split())[:40],
            "x": " ".join(str(it.get("x") or "").split())[:160],
        })
        if len(out) >= MAX_CANDIDATES:
            break
    return out


# --------------------------------------------------------------------------- #
# prompt
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = (
    "Egy magyar webaruhaz kereso-asszisztense vagy. A vasarlo beirt valamit a keresobe, "
    "es te a MEGADOTT termeklistabol valasztasz neki.\n"
    "SZABALYOK:\n"
    "- Csak a listaban szereplo termekeket ajanlhatod, a pontos azonositojukkal.\n"
    "- Legfeljebb 3 terméket valassz, a legjobban illeszkedot elore.\n"
    "- Az indoklas OSSZESEN legfeljebb 3 rovid mondat, magyarul, tegezodve.\n"
    "- SOHA ne irj arat, szamot, keszletet, szallitasi idot — azt a webshop jeleniti meg.\n"
    "- Ne igerj olyat, ami a listabol nem derul ki. Ha egyik termek sem illik a kereshez, "
    "ures listat adj vissza.\n"
    "- A valasz KIZAROLAG egy JSON objektum, semmi mas:\n"
    '  {"a": "az indoklas szovege", "pids": ["azonosito1", "azonosito2"]}'
)


def build_user_prompt(q, candidates):
    sorok = []
    for c in candidates:
        extra = " | ".join(x for x in (c.get("b"), c.get("c"), c.get("x")) if x)
        sorok.append("- [%s] %s%s" % (c["i"], c["n"], (" (%s)" % extra) if extra else ""))
    return "A vasarlo ezt irta a keresobe: %s\n\nElerheto termekek:\n%s" % (
        str(q or "").strip()[:200], "\n".join(sorok))


# --------------------------------------------------------------------------- #
# valasz-feldolgozas
# --------------------------------------------------------------------------- #
_FENCE = re.compile(r"```[a-zA-Z]*|```")
# ar-gyanus reszlet: 3+ jegyu szam, vagy barmilyen szam penznem/egyseg mellett
_PRICE = re.compile(r"\d[\d\s\u00a0.,]{2,}|\d+\s*(?:ft|huf|eur|forint|%)", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")


def strip_prices(text):
    """Ar-gyanus MONDATOKAT dob ki (a maradek mondatok megmaradnak)."""
    kept = [s for s in _SENT.split(" ".join(str(text or "").split())) if s and not _PRICE.search(s)]
    return " ".join(kept[:MAX_SENTENCES]).strip()[:MAX_ANSWER_CHARS]


def parse_reply(raw):
    """LLM-valasz -> (szoveg, pid-lista). Hibas/nem-JSON valaszra ('', [])."""
    s = _FENCE.sub("", str(raw or "")).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return "", []
    try:
        data = json.loads(s[i:j + 1])
    except Exception:  # noqa: BLE001 - a rossz valasz nem hiba, csak nincs sav
        return "", []
    if not isinstance(data, dict):
        return "", []
    text = data.get("a") or data.get("answer") or ""
    pids = data.get("pids") or data.get("products") or []
    if not isinstance(pids, list):
        pids = []
    return str(text), [str(p).strip() for p in pids if str(p).strip()]


def finalize(raw, candidates):
    """LLM-valasz + jeloltek -> {"answer", "pids"} vagy None (nincs sav).

    None a valasz, ha: nem ertelmezheto a JSON, egyetlen pid sem a jeloltek kozul
    valo, vagy az ar-szures utan nem marad szoveg. Ez a "good enough" kapu.
    """
    text, pids = parse_reply(raw)
    engedett = {c["i"]: c for c in (candidates or [])}
    valid, latott = [], set()
    for p in pids:
        if p in engedett and p not in latott:
            latott.add(p)
            valid.append(p)
        if len(valid) >= MAX_PICKS:
            break
    if not valid:
        return None
    text = strip_prices(text)
    if len(text) < 10:
        return None
    return {"answer": text, "pids": valid}

"""m106: CX Konfigurator-felajanlas a chatben (stdlib-only, fajl-betoltheto).

Ha a latogato nyomtatot (termekkort) valasztana / bizonytalan / rakerdez a
konfiguratorra, a /chat valasz melle egy `cta` gomb kerul ({label, url}), ami
a tenant konfigurator-oldalara visz. Sessiononkent legfeljebb egyszer (a hivo
az events tablaban nezi: kind='konf_cta').

Tenant-beallitas: tenants.konf_config["chat_cta"] (az admin Konfigurator-fulen,
a config JSON-ban szerkesztheto):
    {"enabled": true, "url": "https://.../nyomtato-konfigurator?source=chatbot",
     "label": "Nyomtato-valaszto megnyitasa ->"}  (ures -> DEFAULT_LABEL)
A felismero szotara jelenleg a nyomtato-termekkorre van hangolva (copygo, a
d21a korpusz-meres alapjan); mas termekkorhoz a chat_cta "nouns" listaja
adhat sajat foneveket (ekezet nelkul, regex-toredek).
"""

import re
import unicodedata
from urllib.parse import urlsplit

DEFAULT_LABEL = "Nyomtató-választó megnyitása →"


def fold(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# termekkor-fonev (nyomtato)
_NOUN = r"(nyomtato\w*|multifunkcio\w*|lezernyomtat\w*|tintasugaras\w*|tintatartalyos\w*|fenymasolo\w*|printer\w*)"
# kifejezett rakerdezes a varazslora -> fonev nelkul is
_EXPLICIT = re.compile(r"(konfigurator\w*|nyomtato\s*-?\s*valaszto\w*|termekvalaszto\w*|valaszto\s*varazslo\w*)")
# valasztasi szandek / bizonytalansag / igeny-leiras
_CHOICE = re.compile(
    r"\b(melyik\w*|milyen\w*|ajanl\w*|javasol\w*|valassz\w*|valaszt\w*|vegyek|vennek|vasarolnek|"
    r"erdemes\w*|keres\w*|kellene|kene|kell\s+egy|szeretnek\s+(egy|venni|vasarolni|uj)|"
    r"tanacs\w*|segits\w*|nem\s+tudom|bizonytalan\w*|dont\w*|osszehasonlit\w*|legjobb\w*|"
    r"legolcsobb\w*|olcso\w*|jobb|uj\s+nyomtat\w*)\b"
)
# igeny-leiras kovetkezo korben (a nyomtato-szo egy korabbi korben volt)
_NEED = re.compile(
    r"\b(otthon\w*|irod\w*|diak\w*|iskol\w*|ceg\w*|vallalkozas\w*|havonta|havi|oldal\w*|szines\w*|"
    r"fekete\s*-?\s*feher\w*|szkenner\w*|szkenn\w*|masol\w*|wifi\w*|wi-fi\w*|duplex\w*|ketoldal\w*|"
    r"fotot?\w*|dokumentum\w*|lezer\w*|tinta(sugaras|tartalyos)\w*|keret\w*|max\w*|\d+\s*(e|ezer)\s*(ft|forint)?)\b"
)
# nem valasztas: kellek, szerviz, rendeles, nem-konfiguralhato nyomtatotipus
_STOP = re.compile(
    r"(toner\w*|patron\w*|\btinta\b|\btintat\b|tintak\w*|festek\w*|dobegyseg\w*|\bdob\b|kellek\w*|utantolt\w*|"
    r"alkatresz\w*|szerviz\w*|javit\w*|elromlo\w*|hibas\w*|hibat\w*|nem\s+nyomtat|garanci\w*|jotall\w*|"
    r"rendelesem\w*|szallitas\w*|visszakuld\w*|nyugta\w*|blokk\w*|cimke\w*|matrica\w*|3d|hopapir\w*|"
    r"termo\w*|papir\w*|driver\w*|illesztoprogram\w*|telepit\w*)"
)
_NOUN_RE = re.compile(r"\b" + _NOUN)
# konkret tipuskod (L3270, M234sdn, MFP28a) -> a latogato mar dontott, hacsak
# nem hasonlit ossze / bizonytalan
_CODE = re.compile(r"\b(?!a[3-6]\b)(?!\d+(e|k|ft|ezer|eft)\b)(?=[a-z-]*\d)(?=\d*[a-z])[a-z0-9-]{3,}\b")
# konkret, mar mutatott termekre visszautalo kerdes ("ez tud szinesben nyomtatni?")
_DEICTIC = re.compile(r"\b(ez|ezt|ennek|ehhez|ebben|ezzel|ez\s+a|az\s+(elso|masodik|harmadik|utolso)|a\s+(elso|masodik|harmadik|utolso))\b")
_UNSURE = re.compile(r"\b(melyik\w*|vagy|jobb|osszehasonlit\w*|nem\s+tudom|bizonytalan\w*|dont\w*|kulonbseg\w*)\b")


def _noun_re(extra):
    if not extra:
        return _NOUN_RE
    parts = [str(x).strip() for x in extra if str(x or "").strip()]
    if not parts:
        return _NOUN_RE
    try:
        return re.compile(r"\b(" + "|".join(parts) + r")")
    except re.error:
        return _NOUN_RE


def detect(message, prev_user=(), nouns=None):
    """True, ha a konfigurator felajanlasa indokolt. (tiszta fuggveny)

    message   - az aktualis latogatoi uzenet
    prev_user - a korabbi latogatoi uzenetek (az aktualis NELKUL), legujabb a vegen
    """
    m = fold(message)
    if not m.strip():
        return False
    if _EXPLICIT.search(m):
        return True
    if _STOP.search(m):
        return False
    if _DEICTIC.search(m):
        return False
    noun = _noun_re(nouns)
    if noun.search(m):
        if _CODE.search(m) and not _UNSURE.search(m):
            return False
        return bool(_CHOICE.search(m) or _NEED.search(m))
    # kovetkezo kor: a nyomtato-szo az utolso ket korabbi latogatoi uzenetben volt
    # (valasztasi szandekkal), most az igenyet irja le
    if _NEED.search(m):
        for p in list(prev_user or ())[-2:]:
            fp = fold(p)
            if noun.search(fp) and _CHOICE.search(fp) and not _STOP.search(fp):
                return True
    return False


def _http(u):
    u = str(u or "").strip()
    return u if u.startswith("https://") or u.startswith("http://") else ""


def cta_cfg(konf_config):
    """A tenant chat_cta beallitasa ({label, url, nouns}) vagy None."""
    if not isinstance(konf_config, dict):
        return None
    c = konf_config.get("chat_cta")
    if not isinstance(c, dict) or not c.get("enabled"):
        return None
    url = _http(c.get("url"))
    if not url:
        return None
    label = " ".join(str(c.get("label") or "").split())[:80] or DEFAULT_LABEL
    nouns = c.get("nouns") if isinstance(c.get("nouns"), list) else None
    return {"label": label, "url": url, "nouns": nouns}


def _path(u):
    try:
        p = urlsplit(str(u or ""))
        return (p.netloc.lower().removeprefix("www."), p.path.rstrip("/").lower())
    except Exception:  # noqa: BLE001
        return ("", "")


def same_page(page_url, cta_url):
    """A latogato mar a konfigurator-oldalon van?"""
    a, b = _path(page_url), _path(cta_url)
    return bool(a[1]) and a == b

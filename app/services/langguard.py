"""m87: NEM-LATIN irasrendszeru szo-szivargas kiszurese a bot valaszabol.

Kivalto eles hiba (2026-08-07, ugyfel-bejelentes / notebookstore): a valaszban ukran szo
jelent meg -- "Fontos: ez a <cirill> ar a most elerheto adataim alapjan". Korabban az
onboarding-riportban is elofordult. A m77 tanulsaga szerint erre NEM prompt-szabaly kell,
hanem determinisztikus utoellenorzes a mar LEGENERALT valaszon.

MERES (tools/m87_langscan.py, 3767 valodi tarolt valasz, 13 tenant): 10 szivargas = 0,27%
(notebookstore 8 = 1,0%, nagyonallatshop 1, kellegyszerszam 1), es a kontextus-kapu utan
UGYANANNYI -> 0 hamis pozitiv. A minta tulnyomorest a "najd*" to, gyakran FELBEHAGYVA
("najmostani", "najdene", "najdenc") -- a modell elkezd egy cirill tokent, majd visszavalt.

Stdlib-only, fajlbol betoltheto (minta: selfrepeat/linkterm/branddict).

FP-KOCKAZAT es a ket kapu: a TERMEKNEVEKBEN elofordul legitim nem-latin karakter (pl.
"MAGUS MES10 10<cirill kha>/22 mm"), ezert
  (1) csak a legalabb `_MIN_RUN` hosszu, EGYBEFUGGO nem-latin BETU-futam szamit
      (az egyetlen beszorult karakter NEM),
  (2) ami megjelenik a KONTEXTUSBAN (terneknev/leiras), az a bolt adata -> nem jelezzuk.

TUDATOS HATAR: az egykarakteres CJK szo (`_MIN_RUN`=2 alatt) nem akad fenn -- magyar
webshop-kontextusban ez nem eletszeru, es a lazitas FP-t hozna a fenti termeknevekre.
"""
import re
import unicodedata

__all__ = ["foreign_tokens", "has_foreign_leak", "strip_foreign"]

_MIN_RUN = 2
# szo-hatarok: irasjelek, zarojelek, idezojelek, kotojelek, url-elvalasztok
_TOKEN_RX = re.compile(r"[^\s.,;:!?()\[\]{}<>\"'\u00ab\u00bb\u201e\u201d\u201c\u2026/\\|\u2014\u2013*`#]+")
_MULTISPACE_RX = re.compile(r"[ \t]{2,}")
_ORPHAN_PUNCT_RX = re.compile(r"\s+([,.;:!?])")


def _is_foreign_letter(ch: str) -> bool:
    """Betu, ami NEM latin irasrendszeru (cirill, gorog, CJK, arab, heber, ...)."""
    if not ch.isalpha():
        return False
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False
    return not name.startswith("LATIN")


def _has_run(token: str) -> bool:
    run = 0
    for ch in token:
        if _is_foreign_letter(ch):
            run += 1
            if run >= _MIN_RUN:
                return True
        else:
            run = 0
    return False


def foreign_tokens(text: str, allow_text: str = "") -> list:
    """A valaszban levo, nem-latin irasrendszeru szavak -- a kontextusbol ismertek nelkul.

    `allow_text`: a retrieval-kontextus (terneknevek + leirasok) osszefuzve. Ami ott
    szerepel, az a BOLT adata (pl. cirill karakteres terneknev), nem a modell talalmanya.
    """
    allow = (allow_text or "").lower()
    out = []
    seen = set()
    for tok in _TOKEN_RX.findall(text or ""):
        if not _has_run(tok):
            continue
        low = tok.lower()
        if allow and low in allow:
            continue
        if low not in seen:
            seen.add(low)
            out.append(tok)
    return out


def has_foreign_leak(text: str, allow_text: str = "") -> bool:
    return bool(foreign_tokens(text, allow_text))


def strip_foreign(text: str, allow_text: str = "") -> str:
    """VEGSO MENTESZ: a nem-latin betuket kivagja a jelolt tokenekbol.

    Csak akkor fut, ha a regen IS szivargott. A hibrid tokeneknel eppen a szandekolt
    magyar szot adja vissza ("najmostani" -> "mostani"); tisztan idegen szonal a token
    eltunik, ami nyelvtanilag sanyibb mondatot ad -- de az ugyfel keresenek megfeleloen
    cirill betu semmikeppen nem kerul ki a chatbe.
    """
    bad = foreign_tokens(text, allow_text)
    if not bad:
        return text
    out = text or ""
    for tok in bad:
        cleaned = "".join(ch for ch in tok if not _is_foreign_letter(ch)).strip()
        out = out.replace(tok, cleaned)
    out = _MULTISPACE_RX.sub(" ", out)
    return _ORPHAN_PUNCT_RX.sub(r"\1", out)

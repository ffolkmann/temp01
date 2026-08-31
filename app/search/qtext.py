"""CX SmartSearch — szoveg-normalizalas a szerver-oldali keresohoz (ssq/1, 2026-08-31).

BITRE a widget (cx-search/smartsearch.js) `fold()` / `qTokens()` / STOP-listajanak parja,
mert a Qdrant-index es a /search/q keresonek UGYANUGY kell tokenizalnia, mint ahogy a
kliens-oldali MiniSearch tette - kulonben a ket motor talalatai nem osszevethetok.

  fold():   kisbetu + ekezet-levalasztas (NFD, U+0300-036F), de csak ha az eredmeny
            EGY karakter (a widget szabalya: 'ss'-re bomlo vagy osszetett jelek maradnak)
  words():  a foldolt szoveg [0-9a-z] futamai
  tokens(): a lekerdezes tokenjei - 3+ szonal a magyar toltelekszavak kiesnek
            (ha minden token toltelek, marad az eredeti lista)
  term_id(): a ritka vektor dimenzioja (crc32) - a build es a kereso ugyanezt hasznalja
  compact_sku(): a cikkszam [0-9a-z]-re szukitve ("WF-M5899" -> "wfm5899")

Stdlib-only, nincs app-fuggoseg (file-load teszttel is betoltheto).
"""
import re
import zlib

_NONALNUM = re.compile(r"[^0-9a-z]+")
_MARK_LO, _MARK_HI = 0x0300, 0x036F

# smartsearch.js STOP (qTokens) - szo szerint
STOP = frozenset((
    "a az egy ez ezt az azt es vagy de hogy ha mert mi mit mik milyen melyik mennyi "
    "mekkora hany hogyan hol mikor miert mire mihez mivel kinek kihez kerdes "
    "van vannak volt lesz kell kellene lehet erdemes szabad tud tudsz tudtok tudna "
    "tudnal tudnatok segit segiteni segitesz segitenel segitene kerem kerlek koszonom "
    "ajanl ajanlas ajanlasz ajanlana ajanlanad javasol javasolsz javasolna keres keresek "
    "keresem keresnek kereses szeretnek szeretnem szeretne akarok kene "
    "illik illene passzol passzolna valo valok jo jol legjobb jobb "
    "benne bele hozza rajta ehhez ahhoz nekem neked nekunk oda ide "
    "nem igen is meg csak mar pedig nagyon "
    "hoz hez hoz ba be ban ben ra re rol rul tol tul nak nek val vel bol bol ig"
).split())

_fold_cache: dict = {}


def fold_char(ch: str) -> str:
    """Egy karakter ekezet-levalasztasa a widget szabalyaval (NFD + U+0300-036F torles,
    csak ha egy karakter marad)."""
    c = _fold_cache.get(ch)
    if c is not None:
        return c
    import unicodedata
    d = unicodedata.normalize("NFD", ch)
    d = "".join(x for x in d if not (_MARK_LO <= ord(x) <= _MARK_HI))
    c = d if len(d) == 1 else ch
    if len(_fold_cache) < 4096:
        _fold_cache[ch] = c
    return c


def fold(s) -> str:
    return "".join(fold_char(ch) for ch in str(s or "").lower())


def words(s) -> list:
    """A foldolt szoveg [0-9a-z]-futamai (a widget `split(/[^0-9a-z]+/)` parja)."""
    return [t for t in _NONALNUM.split(fold(s)) if t]


def drop_stop(toks: list) -> list:
    out = [t for t in toks if t not in STOP]
    return out if out else toks


def tokens(q) -> list:
    """Lekerdezes-tokenek: 3+ szonal toltelekszo-szures (qTokens-parity)."""
    t = words(q)
    return drop_stop(t) if len(t) >= 3 else t


def compact_sku(sku) -> str:
    return _NONALNUM.sub("", fold(sku or ""))


def term_id(term: str) -> int:
    """Ritka-vektor dimenzio: crc32 (u32). Ugyanez a build- es a kereso-oldalon."""
    return zlib.crc32(term.encode("utf-8")) & 0xFFFFFFFF

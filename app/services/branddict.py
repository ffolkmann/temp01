"""m82h/2: tenant-szintu MARKA-SZOTAR a Qdrant VALODI `brand` payload-ertekeibol.

Elv (a m82-es sav alapelve): a valodi ertekek MAGUK a szotar -- a kezi
`paramextract._BRANDS` (26 elem) helyett a felismeres a bolt sajat
brand-ertekeibol epul. A SZURO-UT VALTOZATLAN: tovabbra is a `brand` payload
must-feltetel szur (100% fedettseg, kategoria-kapu nelkul, follow-upra is jo) --
csak a SZOTAR cserelodik.

A terkepet a `tools/brand_map_crawl.py` irja tenantonkent
(`data/brand_map_<client_id>.json`), a higienia-kapukkal:
  H1  STOP-lista: kategoria-szeru toltelek brand-ertekek (Egyeb, No name,
      Alkatresz, Premium, TOP, Import...)
  H2' kerdes-oldali tisztitas (ITT, a `clean_message`-ben): e-mail ki, URL
      HOST ki -- az utvonal-tokenek MARADNAK (a beillesztett termek-URL
      utvonalaban ott a marka: `copygo.hu/xiaomi-mesh-system...`)
  H3  koznyelvi-kapu: ROVID kulcs (<= 4 karakter) ES kereszt-tenant df >= 3
      (hany MASIK tenant KB-jeben fordul elo) -> ki. Igy esik ki a `hu`, `elo`,
      `1000`, es marad bent a `Microsoft` (hosszu) es a `Gree` (df=2).

Illesztes: token/n-gram (nem alfanumerikus -> szokoz), a LEGHOSSZABB kulcs nyer.
Igy a tobbszavas marka is illeszkedik ("carp expert", "risen energy"), es nincs
reszszo-talalat ("asuszal" nem asus).

Csak stdlib -- tesztbol fajl-betoltheto (importlib.spec_from_file_location).
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

__all__ = ["load_map", "detect_brand", "strip_brand", "clean_message", "MAX_WORDS_DEFAULT"]

MAX_WORDS_DEFAULT = 4
_cache: dict = {}  # path -> (mtime, data)

_RE_MAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\b")
_RE_URL = re.compile(
    r"(?:https?://|www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:hu|com|net|org|eu|io))(/\S*)?")
_RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def _fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c)).strip()


def _norm(s):
    return _RE_NONALNUM.sub(" ", s).strip()


def clean_message(fm):
    """H2': e-mail ki; URL: a HOST ki, az utvonal tokenekre bontva MARAD.

    A bemenet mar fold-olt (kisbetus, ekezet nelkuli) szoveg.
    """
    fm = _RE_MAIL.sub(" ", fm)

    def _u(m):
        return " " + _RE_NONALNUM.sub(" ", m.group(2) or "") + " "
    return _RE_URL.sub(_u, fm)


def load_map(client_id, map_dir=None):
    """A tenant marka-terkepenek betoltese (mtime-cache). Nincs fajl -> None."""
    base = map_dir or os.environ.get("FACET_MAP_DIR", "/app/data")
    path = os.path.join(base, "brand_map_%s.json" % client_id)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001 - serult fajl: fail-safe None
        return None
    if not isinstance(data, dict) or not isinstance(data.get("brands"), dict):
        return None
    _cache[path] = (mt, data)
    return data


def detect_brand(message, bmap):
    """(kulcs, nyers payload-ertekek) a kerdesbol. Nincs talalat -> ("", []).

    A kulcs a fold-olt, szokozzel tagolt alak ("tp link", "carp expert"); a
    hivo (paramextract) ebbol kepzi a linkfacet-nek a slug-alakot.
    """
    if not bmap:
        return "", []
    brands = bmap.get("brands") or {}
    if not brands:
        return "", []
    try:
        maxw = int(bmap.get("max_words") or MAX_WORDS_DEFAULT)
    except (TypeError, ValueError):
        maxw = MAX_WORDS_DEFAULT
    maxw = max(1, min(maxw, 6))
    toks = _norm(clean_message(_fold(message))).split()
    best = ""
    for i in range(len(toks)):
        for n in range(1, maxw + 1):
            if i + n > len(toks):
                break
            cand = " ".join(toks[i:i + n])
            if len(cand) > len(best) and cand in brands:
                best = cand
    if not best:
        return "", []
    ent = brands.get(best) or {}
    vals = ent.get("vals") if isinstance(ent, dict) else None
    return best, [str(v) for v in (vals or []) if str(v).strip()]


# --- m82h/3: a markanev kivezetese az EMBEDELT kerdesbol ---------------------
# A marka mar Qdrant must-feltetel, ezert a szurt poolban MINDEN termek
# ugyanattol a markatol van -> a marka NEVE nulla informacio, viszont elnyomja
# az ALTIPUST ("sator", "szaraz tap", "furo"). Meres (tools/m82h3_sweep.py):
# "Milyen Delphin satratok van?" -> a rerank top-8-ban 0 sator; a markanev
# nelkuli embeddel 6 (a bolt 21 elerheto sator-termeke kozul).
_SPLIT = re.compile(r"([^0-9A-Za-z\u00c0-\u00ff]+)")
_MIN_REST = 3


def strip_brand(message, brand_key):
    """A marka szavainak kivetele a szovegbol, TOKEN-szinten.

    A maradek EKEZETES marad (ekezet nelkul gyenge az embed). Ha nem marad
    ertelmes szoveg (< _MIN_REST alfanumerikus karakter, pl. tiszta
    marka-kerdes: "Van Ryobi termeketek?" -> "Van termeketek?" meg jo, de
    "Ryobi" -> ""), akkor "" a valasz es a hivo a mai embedet hasznalja.
    """
    words = {w for w in re.split(r"[^0-9a-z]+", _fold(brand_key)) if w}
    if not words:
        return ""
    parts = _SPLIT.split(str(message or ""))
    toks, seps = parts[0::2], parts[1::2]
    keep = [_fold(t) not in words for t in toks]
    out = []
    for i, t in enumerate(toks):
        if keep[i]:
            out.append(t)
        if i < len(seps):
            # a szeparatort (pl. a "TP-Link" kotojelet) CSAK akkor tartjuk meg,
            # ha mindket szomszedos szo megmaradt -- kulonben szokoz
            nxt = keep[i + 1] if i + 1 < len(keep) else True
            out.append(seps[i] if (keep[i] and nxt) else " ")
    rest = "".join(out)
    if len(re.sub(r"[^0-9A-Za-z\u00c0-\u00ff]+", "", rest)) < _MIN_REST:
        return ""
    return re.sub(r"\s{2,}", " ", rest).strip(" ,.-")

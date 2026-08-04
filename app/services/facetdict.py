"""m82b: generikus kerdes -> bolt-szuro felismero (Qdrant `facets` payload).

A crawl-olt facet_map ERTEKEI maguk a szotar (nincs kezi lista): a
kontextus-talalatokbol adodo KATEGORIABAN letezo attr:ertek parokat
illesztjuk a kerdesre, es ebbol epitunk Qdrant must-felteteleket a
tools/facet_label_crawl.py altal irt `facets` keyword listara.

KATEGORIA-KAPU KOTELEZO: egy erteket csak akkor alkalmazunk, ha az adott
kategoriaban letezik. E nelkul tomeges false positive jonne ("fekete
pentek" -> szin:fekete).

Szotar-higienia (a nyers crawl-ertekek nem hasznalhatok kozvetlenul):
  - bool/toltelek ertekek tiltva ("nem" MINDEN magyar kerdesben ott van)
  - csak szamjegybol allo ertek tiltva (azt a p_<attr> range-ag kezeli)
  - min. hossz
  - szelektivitas-kapu: ha egy ertek a kategoria termekeinek >= 80%-at
    fedi (pl. extrak:webkamera 942/948), nem szuro -> kihagyjuk

m82b v1 SZANDEKOSAN kihagyja azokat az attributumokat, amiket mar kulon,
bejaratott ag kezel (marka -> brand payload m80; kijelzo-meret ->
p_kijelzo m81; taska-attributumok -> p_* m79c; felhasznalas-jellege ->
usage m76). Ezek kivezetese a generikus szotar javara: m82c, lepesenkent,
regresszio-teszttel. Igy az m82b tisztan ADDITIV: csak olyan
attributumokra szur, amikre eddig semmi.

Stdlib-only, fajlbol betoltheto (minta: linkfacet/paramextract).
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["detect_facet_tags", "build_facet_conditions", "facet_tag_url"]

# mar sajat aggal kezelt attributumok (m82c vezeti ki oket ide)
_SKIP_ATTRS = frozenset({
    "marka",                      # m80: brand payload
    "kijelzo-meret",              # m81: p_kijelzo range
    "maximalis-notebook-meret",   # m79c: p_max_meret
    "taska-tipusa",               # m79c: p_tipus
    "szin",                       # m79c: p_szin (bag-gate)
    "felhasznalas-jellege",       # m76: usage payload
})

# bool/toltelek ertekek: soha nem jelentenek kerdes-oldali igenyt
_STOP_VALUES = frozenset({"nem", "igen", "van", "nincs", "mas", "egyeb", "egyeb-egyeb"})

_MIN_LEN = 3
_COVER_MAX = 0.8   # ennel nagyobb lefedettsegnel az ertek nem szelektiv
_MAX_ATTRS = 3     # egy kerdesbol legfeljebb ennyi attributumra szurunk

_rx_cache: dict = {}


def _fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c))


def _norm_key(s):
    return re.sub(r"[^a-z0-9]", "", _fold(s))


def _leaf(category_name):
    parts = [p.strip() for p in str(category_name or "").split(">")]
    return parts[-1] if parts else ""


def _top_category(categories):
    cnt: dict = {}
    for c in categories or []:
        c = str(c or "").strip()
        if c:
            cnt[c] = cnt.get(c, 0) + 1
    if not cnt:
        return ""
    return max(cnt.items(), key=lambda kv: kv[1])[0]


def _rx(val):
    """Ertek-slug -> illeszto regex.

    'windows-11-professional' -> windows[\\s-]*11[\\s-]*professional
    '16gb'                    -> 16\\s*gb   (a kerdesben '16 GB' is lehet)
    A hatarok betu/szam-osztalyra nezve vannak, hogy az 'ips' ne
    illeszkedjen a 'chips'-be.
    """
    hit = _rx_cache.get(val)
    if hit is not None:
        return hit
    toks = []
    for part in str(val).split("-"):
        if not part:
            continue
        m = re.match(r"^(\d+)([a-z]+)$", part)
        if m:
            toks.append(re.escape(m.group(1)) + r"\s*" + re.escape(m.group(2)))
        else:
            toks.append(re.escape(part))
    if not toks:
        return None
    rx = re.compile(r"(?<![a-z0-9])" + r"[\s\-]*".join(toks) + r"(?![a-z0-9])")
    _rx_cache[val] = rx
    return rx


def _usable(val, count, cat_size, cat_key=""):
    v = str(val or "")
    if len(v) < _MIN_LEN or v in _STOP_VALUES:
        return False
    nk = _norm_key(v)
    if cat_key and len(nk) >= 4 and nk in cat_key:
        # a kategoria sajat neve nem szuro-szandek: a "legolcsobb tintasugaras
        # NYOMTATO" kerdesben a 'nyomtato' a termeknev, nem a
        # funkcionalitas:nyomtato (egyfunkcios) szuro -- e nelkul kiesne az
        # osszes multifunkcios gep (elo sweep-eset: 90 -> 19 termek)
        return False
    if v.replace("-", "").replace(".", "").isdigit():
        return False  # tisztan szamos ertek -> p_<attr> range-ag
    n = int(count or 0)
    if n <= 0:
        return False
    if cat_size and n >= _COVER_MAX * cat_size:
        return False  # nem szelektiv (pl. extrak:webkamera 942/948)
    return True


def _cat_size(facets):
    """A kategoria termekszamanak becslese: az attributumonkenti ertek-osszegek
    MEDIANJA.

    Nem a legnagyobb egyedi ertek (az alulbecsul: egy 40-es ertek egy 145-os
    kategoriaban meg szelektiv), es nem is a legnagyobb osszeg (a tobb-erteku
    attributum, pl. `extrak`, tulbecsul: 3320 osszeg 948 termeknel).
    """
    sums = []
    for vals in (facets or {}).values():
        s = sum(int(n or 0) for n in (vals or {}).values())
        if s > 0:
            sums.append(s)
    if not sums:
        return 0
    sums.sort()
    return sums[len(sums) // 2]


def _category_entry(categories, fmap):
    """(slug, entry) a kontextus top-kategoriajara, vagy ("", None)."""
    cat = _top_category(categories)
    if not cat:
        return "", None
    want = _norm_key(_leaf(cat))
    for slug, ent in (fmap.get("categories") or {}).items():
        if _norm_key(slug) == want:
            return slug, ent
    return "", None


def detect_facet_tags(message, categories, fmap, max_attrs=_MAX_ATTRS):
    """['operacios-rendszer:windows-11-professional', 'memoria-meret:16gb'] vagy [].

    `categories`: a kontextus-talalatok category payload-ertekei (a kapu).
    `fmap`: linkfacet.load_map(client_id) kimenete (None -> [] fail-safe).
    Attributumonkent max 1 ertek: tobb talalatnal a leghosszabb (legpontosabb).
    """
    if not (message and fmap):
        return []
    cat_slug, ent = _category_entry(categories, fmap)
    if not ent:
        return []
    cat_key = _norm_key(cat_slug)
    facets = ent.get("facets") or {}
    if not facets:
        return []
    cat_size = _cat_size(facets)
    fm = _fold(message)
    out = []
    for attr in sorted(facets):
        if attr in _SKIP_ATTRS:
            continue
        best = ""
        for val, n in (facets[attr] or {}).items():
            if not _usable(val, n, cat_size, cat_key):
                continue
            rx = _rx(val)
            if rx is not None and rx.search(fm) and len(str(val)) > len(best):
                best = str(val)
        if best:
            out.append("%s:%s" % (attr, best))
            if len(out) >= max_attrs:
                break
    return out


def facet_tag_url(base_url, categories, tags, fmap):
    """Az elso olyan felismert cimke szuro-URL-je, ami a kategoriaban letezik.

    A linkfacet _PRIORITY-lancaba a generikus cimkek nem fernek bele (nincs
    hozzajuk constraint-kulcs), ezert a zaro-linket itt epitjuk: a m79b
    fasetta-link elsobbseget elvez, ez csak akkor jon, ha az nem adott URL-t.
    """
    if not (base_url and tags and fmap):
        return None
    _slug, ent = _category_entry(categories, fmap)
    if not ent or not ent.get("url"):
        return None
    facets = ent.get("facets") or {}
    base = str(base_url).rstrip("/")
    for t in tags or []:
        attr, _, val = str(t).partition(":")
        if not (attr and val):
            continue
        if int((facets.get(attr) or {}).get(val) or 0) > 0:
            return base + str(ent["url"]) + "/" + attr + ":" + val
    return None


def build_facet_conditions(tags):
    """Qdrant must-feltetelek a cimkekbol (attributumonkent kulon feltetel = AND)."""
    return [{"key": "facets", "match": {"value": t}} for t in (tags or []) if t]

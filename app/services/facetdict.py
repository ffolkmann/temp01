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

__all__ = [
    "detect_facet_tags", "build_facet_conditions", "facet_tag_url", "category_value",
    "detect_category",
]

# mar sajat aggal kezelt attributumok (m82c vezeti ki oket ide)
_SKIP_ATTRS = frozenset({
    "marka",                      # m80: brand payload
    "kijelzo-meret",              # m81: p_kijelzo range
    "maximalis-notebook-meret",   # m79c: p_max_meret
    "taska-tipusa",               # m79c: p_tipus
    "szin",                       # m79c: p_szin (bag-gate)
    # m82c: a "felhasznalas-jellege" INNEN KIVEZETVE -- a crawl-olt generikus
    # szotar ismeri fel (a kezi _USAGE_WORDS lista es a m76-os kulon usage
    # payload-ag megszunt a kerdes-oldalon).
})

# bool/toltelek ertekek: soha nem jelentenek kerdes-oldali igenyt
_STOP_VALUES = frozenset({"nem", "igen", "van", "nincs", "mas", "egyeb", "egyeb-egyeb"})

_MIN_LEN = 3
_COVER_MAX = 0.8   # ennel nagyobb lefedettsegnel az ertek nem szelektiv
_MAX_ATTRS = 3     # egy kerdesbol legfeljebb ennyi attributumra szurunk

# m82c/2: kategoria-szandek a KERDESBOL
_CAT_MIN = 4       # ennel rovidebb kategoria-nev-reszt nem illesztunk
_CAT_SUFFIX = 4    # ennyi ragozasi karakter engedett a talalat vegen
# m82c/4: OSSZETETT SZO. A magyar a kategoria-fonevet gyakran a szo VEGERE
# teszi ("lezerNYOMTATO", "gamerLAPTOP"), a kezdo hatar viszont szigoru volt,
# ezert a kapu nem allt be, es a talalat-alapu fallbackre esett vissza.
# Ezert HOSSZU kategoria-nev ele max _CAT_PREFIX_MAX betu tapadhat.
# Biztonsagos, mert a detect_category a LEGHOSSZABB reszt valasztja, es
# holtversenynel nem dont: a "cimkenyomtato" igy a Cimkenyomtatora megy,
# nem a Nyomtatora.
_CAT_COMPOUND_MIN = 6   # ennel rovidebb kategoria-nev ele nem engedunk elotagot
_CAT_PREFIX_MAX = 12    # az elotag maximalis hossza
_CAT_STOP = frozenset({
    "egyeb", "kiegeszito", "kiegeszitok", "tartozek", "tartozekok",
    "hasznalt", "termek", "termekek", "akcio", "akciok", "ujdonsag", "ujdonsagok",
})

# m82c/3: ragozas-tures. A zaro hatar csak HOSSZU ertekeknel lazul: rovid
# ertekeknel a toldalek-engedmeny mas szot csinalna belole --
#   intel (5) + "ligens" -> "intelligens"   (496 termek szurese egy KB-kerdesre)
#   pla   (3) + "zma"    -> "plazma"
# ezert _SUF_MIN a normalizalt ertek MINIMALIS hossza, es max _SUF_MAX
# karakter tapadhat a vegere. Az elejen a hatar VALTOZATLANUL szigoru.
_SUF_MIN = 7
_SUF_MAX = 3

# m82c/3: koznyelvi szinonimak attributumonkent -> a crawl-olt ertek.
# Kezi lista, SZANDEKOSAN rovid: csak olyan alak, ami a slugbol semmilyen
# szabaly szerint nem vezetheto le. A szinonima ugyanazon a higienian
# (kategoria-kapu, szelektivitas, kat-fonev) megy at, mint a nyers ertek.
_SYNONYMS = {
    "felbontas": {
        "3840x2160": ("4k", "uhd"),
        "2560x1440": ("2k", "qhd", "wqhd"),
        "1920x1080": ("full-hd", "fullhd", "fhd", "1080p"),
    },
    "erintokepernyo": {
        "10-point-multi-touch": ("erintokepernyo", "erinto-kijelzo", "touchscreen", "multitouch"),
    },
    "nyomtatasi-technologia": {
        "lezer": ("lezernyomtato", "lezeres"),
        "tintasugaras": ("tintasugarasnyomtato",),
    },
}

# m82c/3: ertek-csapdak. Egy-egy ertek olyan ALLANDO SZOKAPCSOLATBAN is
# szerepel, ahol nem szuro-szandek. A kimerito FP-scan (20 negativ kerdes x
# 85 kategoria = 1700 par) PONTOSAN egy ilyet talalt: a "fekete pentek" a
# nyomtato-kategoriaban a szinkeszlet:fekete-re illeszkedett volna, es
# kizarta volna a szines gepeket. Ha az ertek ilyen frazis reszekent all,
# nem szamit talalatnak.
_VALUE_TRAPS = {
    "fekete": r"fekete[\s-]*pentek|black[\s-]*friday",
}
_trap_cache: dict = {}


def _is_trap(val, folded_message):
    pat = _VALUE_TRAPS.get(str(val))
    if not pat:
        return False
    rx = _trap_cache.get(pat)
    if rx is None:
        rx = _trap_cache[pat] = re.compile(pat)
    return bool(rx.search(folded_message))


_rx_cache: dict = {}
_crx_cache: dict = {}


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
    tail = (r"(?![a-z0-9]{%d,})" % (_SUF_MAX + 1)) if len(_norm_key(val)) >= _SUF_MIN \
        else r"(?![a-z0-9])"
    rx = re.compile(r"(?<![a-z0-9])" + r"[\s\-]*".join(toks) + tail)
    _rx_cache[val] = rx
    return rx


def _syn_hit(attr, val, folded_message):
    """Illeszkedik-e az `attr:val` valamelyik koznyelvi szinonimaja a kerdesre."""
    for syn in (_SYNONYMS.get(attr) or {}).get(val, ()):
        rx = _rx(syn)
        if rx is not None and rx.search(folded_message):
            return True
    return False


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


def _cat_parts(category):
    """A payload-kategoria LEVELNEVENEK illesztheto reszei (vesszo menten).

    'Nyomtato > Tintapatron, toner' -> ['tintapatron', 'toner']
    """
    out = []
    for part in _fold(_leaf(category)).split(","):
        p = re.sub(r"\s+", " ", part).strip()
        if len(p) < _CAT_MIN or _norm_key(p) in _CAT_STOP:
            continue
        out.append(p)
    return out


def _cat_rx(part):
    """Kategoria-nev-resz -> illeszto regex, rovid magyar toldalekkal.

    A zaro hatar SZANDEKOSAN nem szigoru (a facet-ertekekkel ellentetben):
    'asztali szamitogepET', 'monitorT', 'nyomtatoK' meg talalat, de a
    'monitorszuro' (5+ karakter ratoldva) mar NEM -- igy a ragozas nem esik
    ki, a masik kategoriaba atcsuszas viszont igen.
    """
    hit = _crx_cache.get(part)
    if hit is not None:
        return hit
    toks = [re.escape(t) for t in str(part).split(" ") if t]
    if not toks:
        return None
    rx = re.compile(
        r"(?<![a-z0-9])"
        + (r"(?:[a-z]{2,%d})?" % _CAT_PREFIX_MAX
           if len(_norm_key(part)) >= _CAT_COMPOUND_MIN else r"") + r"[\s\-]*".join(toks)
        + r"(?![a-z0-9]{" + str(_CAT_SUFFIX + 1) + r",})"
    )
    _crx_cache[part] = rx
    return rx


def detect_category(message, catalog):
    """A kerdesben megnevezett kategoria PAYLOAD-erteke, vagy "".

    m82c/2: a kategoria-kaput eddig a TALALATOK top-kategoriaja adta, azaz
    "hova estek a talalatok" -- helyesen viszont "mit kerdezett". Elo eset: a
    "legolcsobb gamer ASZTALI szamitogep" poolja notebook-dominans, ezert a
    kapu notebookra allt be, es a 6 gamer asztali gep sosem jutott be.

    `catalog`: a tenant VALODI `category` payload-ertekei (Qdrant facet API) --
    igy a talalat EGYBEN a Qdrant-feltetel erteke is, nincs slug->payload
    forditas. Tobbertelmu illeszkedesnel "" -> marad a talalat-alapu kapu.
    """
    if not (message and catalog):
        return ""
    fm = _fold(message)
    best = ""
    best_len = 0
    tie = False
    for cat in catalog:
        cat = str(cat or "")
        if not cat:
            continue
        for p in _cat_parts(cat):
            rx = _cat_rx(p)
            if rx is None or not rx.search(fm):
                continue
            if len(p) > best_len:
                best, best_len, tie = cat, len(p), False
            elif len(p) == best_len and cat != best:
                tie = True   # ket kulonbozo kategoria egyforma erossen -> nem dontunk
    return "" if tie else best


def _category_entry(categories, fmap, category=""):
    """(slug, entry) a kategoriara, vagy ("", None).

    m82c/2: `category` = a KERDESBOL feloldott payload-kategoria; ha van, az
    eros a kontextus-talalatok top-kategoriajanal. A terkepben nem letezo
    kategoria ("", None)-t ad -> a hivo nem szur (fail-safe).
    """
    cat = str(category or "") or _top_category(categories)
    if not cat:
        return "", None
    want = _norm_key(_leaf(cat))
    for slug, ent in (fmap.get("categories") or {}).items():
        if _norm_key(slug) == want:
            return slug, ent
    return "", None


def detect_facet_tags(message, categories, fmap, max_attrs=_MAX_ATTRS, category=""):
    """['operacios-rendszer:windows-11-professional', 'memoria-meret:16gb'] vagy [].

    `categories`: a kontextus-talalatok category payload-ertekei (a kapu).
    `fmap`: linkfacet.load_map(client_id) kimenete (None -> [] fail-safe).
    Attributumonkent max 1 ertek: tobb talalatnal a leghosszabb (legpontosabb).
    """
    if not (message and fmap):
        return []
    cat_slug, ent = _category_entry(categories, fmap, category)
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
            hit = rx is not None and rx.search(fm)
            if not hit:
                hit = _syn_hit(attr, val, fm)   # m82c/3: koznyelvi alak
            if hit and _is_trap(val, fm):
                hit = False                     # m82c/3: allando szokapcsolat
            if hit and len(str(val)) > len(best):
                best = str(val)
        if best:
            out.append("%s:%s" % (attr, best))
            if len(out) >= max_attrs:
                break
    return out


def category_value(categories, fmap, category=""):
    """A kontextus top-kategoriajanak PAYLOAD-erteke, ha a terkepben letezik ("" ha nem).

    m82c: a `facets` cimkek kategoria-agnosztikusak -- ugyanaz a tag tobb
    kategoriaban is el (felhasznalas-jellege:gamer notebookon ES asztali
    gepen is). A bolt szuro-oldala viszont kategoria-szintu, ezert a Qdrant-
    szurest is oda kell kotni, kulonben a "legolcsobb gamer laptop" poolba
    gamer ASZTALI gep kerul (es ar-rendezes utan az is nyerhet).
    """
    if not (fmap and (categories or category)):
        return ""
    slug, ent = _category_entry(categories, fmap, category)
    if not (slug and ent):
        return ""
    return str(category or "") or _top_category(categories)


def facet_tag_url(base_url, categories, tags, fmap, category=""):
    """Az elso olyan felismert cimke szuro-URL-je, ami a kategoriaban letezik.

    A linkfacet _PRIORITY-lancaba a generikus cimkek nem fernek bele (nincs
    hozzajuk constraint-kulcs), ezert a zaro-linket itt epitjuk: a m79b
    fasetta-link elsobbseget elvez, ez csak akkor jon, ha az nem adott URL-t.
    """
    if not (base_url and tags and fmap):
        return None
    _slug, ent = _category_entry(categories, fmap, category)
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


def build_facet_conditions(tags, category=""):
    """Qdrant must-feltetelek a cimkekbol (attributumonkent kulon feltetel = AND).

    m82c: `category` megadasaval a szures a kontextus kategoriajara szukul (a
    bolt szuro-oldalanak parja). A hivo ures talalatnal kategoria NELKUL
    ujraprobalhat -- ez a fail-safe.
    """
    must = [{"key": "facets", "match": {"value": t}} for t in (tags or []) if t]
    if must and category:
        must.append({"key": "category", "match": {"value": str(category)}})
    return must

"""Ar-szuperlativusz kerdesek ("legolcsobb", "legdragabb") kezelese (m38). PURE modul.

A dense kereses TEMARA talal, de arat nem rendez: a modell a veletlenszeru top-8
legolcsobbjat mondja "a legolcsobbnak", es a kovetkezo korben (mas top-8) ellentmond
onmaganak (eles eset, notebookstore: 246 990 -> 144 990 "legolcsobb").

Szuperlativusz-kerdesnel ezert:
  1) SZELESEBB dense poolt kerunk (topikalisan relevans termekek),
  2) a rerank relevancia-sorrendje HELYETT determinisztikusan ar szerint rendezunk.

FONTOS: a nev-alapu szures NEM jo ut — a "notebook" nevre a 890 Ft-os NOTEBOOK
TAPKABEL lenne a "legolcsobb laptop". A dense pool viszont csak valodi gepeket hoz
(merve: mindket eles kor poolja 8/8 laptop volt).
"""

from __future__ import annotations

import re
import unicodedata

# szelesebb pool szuperlativusz-kerdesnel (a 24 helyett)
WIDE_LIMIT = 120
# m60: az available==True SZURT dense pool merete (a raktaros jeloltekhez)
AVAIL_WIDE_LIMIT = 300

_ASC_RE = re.compile(r"legolcsobb|legkedvezobb\s+ar|legalacsonyabb\s+ar|legjobb\s+ar")
_DESC_RE = re.compile(r"legdragabb|legmagasabb\s+ar")


def fold(s: str) -> str:
    s = str(s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def detect_price_superlative(message: str) -> str | None:
    """'asc' (legolcsobb...) | 'desc' (legdragabb...) | None.

    A kozepfok ("olcsobban", "dragabb-e") NEM szuperlativusz — arra a normal
    relevancia-rangsor a helyes.
    """
    a = fold(message)
    if _ASC_RE.search(a):
        return "asc"
    if _DESC_RE.search(a):
        return "desc"
    return None


def _is_product(hit: dict) -> bool:
    p = hit.get("payload", hit) if isinstance(hit, dict) else {}
    if str(p.get("type") or "").lower() == "product":
        return True
    return bool(str(p.get("sku") or "").strip())


def _price(hit: dict) -> float | None:
    p = hit.get("payload", hit) if isinstance(hit, dict) else {}
    raw = str(p.get("price") or "").replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def sort_by_price(hits: list[dict], direction: str, top_n: int) -> list[dict]:
    """A poolbol az arazott TERMEKEK ar szerint rendezve, top_n.

    Ha 3-nal kevesebb arazott termek van, ures listat adunk vissza — a hivo ilyenkor
    a normal rerank-agra esik vissza (nincs mibol megbizhatoan rendezni).
    """
    priced: list[tuple[float, dict]] = []
    for h in hits:
        if not _is_product(h):
            continue
        p = _price(h)
        if p is not None:
            priced.append((p, h))
    if len(priced) < 3:
        return []
    priced.sort(key=lambda t: t[0], reverse=(direction == "desc"))
    return [h for _, h in priced[:top_n]]

def price_context(hits: list[dict], direction: str, top_n: int) -> list[dict]:
    """m40: ar-szuperlativusz kontextus -- fele ar-veg, fele tema-relevancia.

    A tiszta ar-rendezes (sort_by_price) a topikalisan SZELES poolon a legolcsobb
    KIEGESZITOKET hozza (copygo eles eset, 2026-07-14: a "legolcsobb fotonyomtato"
    top-8-a 8/8 utangyartott tintapatron volt, egyetlen fotonyomtato sem -- a modell
    factuality-helyesen "nem tudom"-ot mondott). Score-floor nem valaszt szet
    (meres: Selphy CP1500 0.444 < MINOLTA toner 0.453), ezert a kontextus ket
    determinisztikus felbol all:
      1) az ar szerinti veg (asc/desc) -- a "legolcsobb/legdragabb" horgony,
      2) a tema legerosebb (score szerinti) termekei -- a valodi jeloltek.
    A modell a kerdezett termektipusra valaszol, a kiegeszitoket atugorja
    (m39 eles tapasztalat), HA a valodi jeloltek is a kontextusban vannak.

    3-nal kevesebb arazott termeknel tovabbra is ures lista -- a hivo a normal
    rerank-agra esik vissza.
    """
    priced: list[tuple[float, dict]] = []
    for h in hits:
        if not _is_product(h):
            continue
        p = _price(h)
        if p is not None:
            priced.append((p, h))
    if len(priced) < 3:
        return []
    by_price = [h for _, h in sorted(priced, key=lambda t: t[0], reverse=(direction == "desc"))]
    by_score = sorted(
        (h for _, h in priced), key=lambda h: float(h.get("score") or 0.0), reverse=True
    )

    def _key(h: dict):
        k = h.get("id")
        if k is not None:
            return ("id", str(k))
        pl = h.get("payload", {}) or {}
        return ("nu", str(pl.get("name") or ""), str(pl.get("url") or ""))

    n_price = max(1, (top_n + 1) // 2)
    out: list[dict] = []
    seen: set = set()
    for h in by_price[:n_price]:
        k = _key(h)
        if k not in seen:
            seen.add(k)
            out.append(h)
    for h in by_score:
        if len(out) >= top_n:
            break
        k = _key(h)
        if k not in seen:
            seen.add(k)
            out.append(h)
    for h in by_price[n_price:]:
        if len(out) >= top_n:
            break
        k = _key(h)
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out


_TOPIC_STOP = {
    "mennyi", "mennyibe", "melyik", "mi", "mik", "mit", "es", "a", "az", "ti",
    "nalatok", "nalunk", "most", "jelenleg", "van", "vane", "kaphato", "kerul",
    "ara", "aru", "arban", "arert",
    # m58: keszlet-szavak -- a tema-embedbol KI (kulonben a "nincs raktaron"
    # szoveget tartalmazo chunkok fele huz a dense kereses)
    "raktaron", "raktarrol", "raktarban", "keszleten", "keszletrol", "keszlet",
    "azonnal", "atveheto", "elviheto", "vihetem", "szallithato", "elerheto",
    "levo", "levot", "ami", "amit", "amelyik",
}
_SUPER_RE = re.compile(r"legolcsobb|legdragabb|legkedvezobb|legalacsonyabb|legmagasabb|legjobb")


def topic_of(message: str) -> str:
    """A szuperlativusz-kerdes TEMAJA ('mennyi a legolcsobb laptop nalatok?' -> 'laptop').

    A tema-embed KOR-FUGGETLEN: az elso es a folytato kerdes ('es a legolcsobb laptop?')
    ugyanazt a vektort kapja -> ugyanaz a pool -> ugyanaz a legkedvezobb aru termek.
    Ures tema (pl. 'es a legolcsobb?') eseten a hivo a normal embed-utra esik vissza.
    """
    out: list[str] = []
    for tok in str(message or "").split():
        f = fold(tok).strip(".,;:!?()\"'")
        if not f or _SUPER_RE.search(f) or f in _TOPIC_STOP:
            continue
        if re.fullmatch(r"[\W_]+", f):
            continue
        out.append(tok.strip(".,;:!?()\"'"))
    return " ".join(out)


# --------------------------------------------------------------------------- #
# m58: keszlet-szures a szuperlativusz-agban ("legolcsobb RAKTARON LEVO ...")
# --------------------------------------------------------------------------- #

_STOCK_RE = re.compile(
    r"raktaron|raktarrol|raktarban|keszleten|keszletrol|"
    r"azonnal\s+(atveheto|elviheto|viheto|vihetem|szallithato|kaphato)|"
    r"rogton\s+(atveheto|elviheto)"
)


def detect_stock_filter(message: str) -> bool:
    """True, ha a latogato keszleten levo termekre szur ("raktaron levo", "azonnal atveheto")."""
    return bool(_STOCK_RE.search(fold(message)))


def availability(hit: dict) -> bool | None:
    """Keszlet-jel a payloadbol: webdoc `available` bool; SR/Unas `stock` szam; kulonben None."""
    p = hit.get("payload", hit) if isinstance(hit, dict) else {}
    av = p.get("available")
    if isinstance(av, bool):
        return av
    raw = str(p.get("stock") or "").replace(" ", "").replace(",", ".")
    if raw:
        try:
            return float(raw) > 0
        except ValueError:
            return None
    return None


STOCK_FILTERED = "stock_filtered"
STOCK_NONE = "stock_none_available"
STOCK_UNKNOWN = "stock_unknown"
STOCK_HINT = "stock_hint"  # m59: sima ar-szuperlativusz, de a kontextusban raktaros jeloltek is vannak

STOCK_NOTES = {
    STOCK_HINT: (
        u"A látogató árban legkedvezőbb terméket keres, készlet-szűrés "
        u"nélkül. A # TUDÁSBÁZIS az ár szerinti véget ÉS a legkedvezőbb "
        u"árú, raktáron jelölt termékeket is tartalmazza. A legolcsóbb/legdrágább "
        u"kérdésre a teljes ár-vég a válasz (akkor is, ha épp nincs raktáron), "
        u"és emellett ajánld a legkedvezőbb árú raktáron lévőt is. Ha "
        u"készletről beszélsz: KIZÁRÓLAG a raktáron jelölt termékeket nevezd "
        u"raktáron lévőnek, és SOHA ne állítsd, hogy rajtuk kívül nincs más "
        u"raktáron — a kontextus a kínálatnak csak egy szelete."
    ),
    STOCK_FILTERED: (
        u"A # TUD\u00c1SB\u00c1ZIS tal\u00e1latai k\u00e9szletre sz\u0171rt, \u00e1r szerint rendezett "
        u"strukt\u00far\u00e1lt keres\u00e9sb\u0151l sz\u00e1rmaznak (szinkroniz\u00e1lt k\u00e9szlet-adat "
        u"alapj\u00e1n) \u2014 ezek t\u00e9nylegesen rakt\u00e1ron jel\u00f6lt term\u00e9kek. Ezekb\u0151l "
        u"aj\u00e1nlj, \u00e9s jelezd, hogy a v\u00e9gleges \u00e1r \u00e9s k\u00e9szlet a term\u00e9koldalon "
        u"ellen\u0151rizend\u0151."
    ),
    STOCK_NONE: (
        u"A l\u00e1togat\u00f3 rakt\u00e1ron l\u00e9v\u0151 term\u00e9ket keres, de a k\u00e9rd\u00e9sre "
        u"illeszked\u0151 szinkroniz\u00e1lt tal\u00e1latok k\u00f6z\u00f6tt most egy sincs rakt\u00e1ron "
        u"jel\u00f6l\u00e9s\u0171. TILOS ebb\u0151l a teljes k\u00edn\u00e1latra \u00e1ltal\u00e1nos\u00edtani "
        u"(pl. \u201esemmi nincs rakt\u00e1ron\u201d). Mondd ki, hogy az \u00e1ltalad most l\u00e1tott "
        u"tal\u00e1latok k\u00f6z\u00f6tt nincs rakt\u00e1ron l\u00e9v\u0151, \u00e9s ir\u00e1ny\u00edtsd a "
        u"l\u00e1togat\u00f3t a webshop keres\u0151j\u00e9hez vagy az \u00fcgyf\u00e9lszolg\u00e1lathoz."
    ),
    STOCK_UNKNOWN: (
        u"A l\u00e1togat\u00f3 rakt\u00e1rk\u00e9szletre k\u00e9rdez, de ehhez a bolthoz nincs "
        u"szinkroniz\u00e1lt k\u00e9szlet-adat. K\u00e9szletet NE \u00e1ll\u00edts \u00e9s ne tagadj; az "
        u"\u00e1rakr\u00f3l v\u00e1laszolhatsz, a k\u00e9szletr\u0151l mondd, hogy a term\u00e9koldal vagy "
        u"az \u00fcgyf\u00e9lszolg\u00e1lat ad pontos inform\u00e1ci\u00f3t."
    ),
}


def _score_median_price(hits: list[dict], k: int = 8) -> float | None:
    """A tema top-k score-u arazott termekeinek median-ara — a kerdezett termektipus arszintje.

    m40-megfigyeles: a dense pool top-score talalatai megbizhatoan a kerdezett tipusbol
    valok (eles meres: 8/8 laptop). A median-ar ezert jo horgony a tipus arszintjere.
    """
    prods = [h for h in hits if _is_product(h) and _price(h) is not None]
    prods.sort(key=lambda h: float(h.get("score") or 0.0), reverse=True)
    ps = sorted(_price(h) for h in prods[:k])
    if not ps:
        return None
    return ps[len(ps) // 2]


def _price_floor_filter(hits: list[dict], ratio: float = 0.2) -> list[dict]:
    """m61: kiegeszito-beszivargas elleni ar-padlo a RAKTAROS jeloltekre.

    Eles eset (notebookstore): az available-szurt pool ar-vege notebookTASKAKKAL
    (4690 Ft) telt meg, igy a "legolcsobb raktaros" jelolt taska lett, a valodi
    legolcsobb gep (109 900) meg a score-felbol szorult ki. A padlo: a tema
    top-score median-aranak <ratio>-szorosa alatti termek nem lehet ar-jelolt.
    Fail-safe: ha a padlo mindent kivagna, az eredeti lista marad.
    """
    m = _score_median_price(hits)
    if not m:
        return hits
    floor = m * ratio
    out = [h for h in hits if (_price(h) or 0.0) >= floor]
    return out or hits


def needs_available_boost(hits: list[dict]) -> bool:
    """m64: igaz, ha a kontextus termekei kozott NINCS raktaron levo, de van keszlet-adat.

    Ilyenkor az m63-as "csak raktarost ajanlj" szabalynak nincs mibol ajanlania —
    a retrieval available-szurt jelolteket fuz hozza.
    """
    avails = [availability(h) for h in hits if _is_product(h)]
    if not avails:
        return False
    return not any(a is True for a in avails) and any(a is not None for a in avails)


def merge_available_extras(hits: list[dict], pool: list[dict], k: int = 3) -> list[dict]:
    """m64: legfeljebb k raktaros jelolt hozzafuzese a kontextushoz (relevancia-sorrend, dedup)."""
    def _k(h: dict):
        if h.get("id") is not None:
            return ("id", str(h.get("id")))
        pl = h.get("payload", {}) or {}
        return ("nu", str(pl.get("name") or ""), str(pl.get("url") or ""))

    seen = {_k(h) for h in hits}
    out = list(hits)
    added = 0
    for h in pool or []:
        if added >= k:
            break
        if _k(h) in seen or not _is_product(h) or availability(h) is not True:
            continue
        out.append(h)
        seen.add(_k(h))
        added += 1
    return out


def _sorted_by_price(hits: list[dict], direction: str, top_n: int) -> list[dict]:
    """Sima ar-rendezes MIN-3 kuszob nelkul (a keszlet-szurt reszhalmazon 1-2 talalat is ervenyes)."""
    priced: list[tuple[float, dict]] = []
    for h in hits:
        if not _is_product(h):
            continue
        p = _price(h)
        if p is not None:
            priced.append((p, h))
    priced.sort(key=lambda t: t[0], reverse=(direction == "desc"))
    return [h for _, h in priced[:top_n]]


def price_context_stock(
    hits: list[dict], direction: str, top_n: int, stock_only: bool,
    avail_pool: list[dict] | None = None,
) -> tuple[list[dict], str]:
    """(context_hits, mode) -- mode: "" | STOCK_FILTERED | STOCK_NONE | STOCK_UNKNOWN.

    stock_only=False: az m40-es price_context valtozatlanul (mode="").
    stock_only=True:
      - van available==True jelolt -> CSAK azokbol epul a kontextus (m40-mix; ha <3, sima
        ar-rendezes a szurt reszhalmazon), mode=STOCK_FILTERED;
      - van keszlet-adat, de senki sincs raktaron -> a szuretlen ar-kontextus megy tovabb
        (a modell lassa, MIK illeszkednek), mode=STOCK_NONE (a prompt tiltja az altalanositast);
      - nincs keszlet-adat a poolban (pl. Sellvio) -> szuretlen kontextus, mode=STOCK_UNKNOWN.
    """
    if not stock_only:
        # m59: sima ar-szuperlativusznal ("melyik a legolcsobb laptop?") a modell hajlamos
        # a kontextus VELETLEN raktaros darabjat "ami raktaron van"-kent ajanlani (eles eset:
        # Victus 465e, mikozben a legolcsobb raktaros Asus 325e nem volt a kontextusban).
        # Ezert az ar-vegi kontextushoz hozzatesszuk a 2 legkedvezobb aru RAKTARON jeloltet,
        # es a STOCK_HINT prompt-szabaly mondja meg, mit szabad keszletnek nevezni.
        base = price_context(hits, direction, top_n)
        if not base:
            return base, ""
        extras = _sorted_by_price(
            _price_floor_filter(
                [x for x in (avail_pool or hits) if _is_product(x) and availability(x) is True]
            ),
            direction, 2,
        )
        if not extras:
            return base, ""

        def _k(h: dict):
            if h.get("id") is not None:
                return ("id", str(h.get("id")))
            pl = h.get("payload", {}) or {}
            return ("nu", str(pl.get("name") or ""), str(pl.get("url") or ""))

        seen = {_k(h) for h in base}
        for h in extras:
            if _k(h) not in seen:
                base.append(h)
                seen.add(_k(h))
        return base, STOCK_HINT
    avail = [
        h for h in (avail_pool or hits)
        if _is_product(h) and _price(h) is not None and availability(h) is True
    ]
    avail = _price_floor_filter(avail)  # m61: taska/kabel/patron ne lehessen "legolcsobb raktaros"
    if avail:
        ctxh = price_context(avail, direction, top_n)
        if not ctxh:
            ctxh = _sorted_by_price(avail, direction, top_n)
        return ctxh, STOCK_FILTERED
    known = any(_is_product(h) and availability(h) is not None for h in hits)
    mode = STOCK_NONE if known else STOCK_UNKNOWN
    return price_context(hits, direction, top_n), mode

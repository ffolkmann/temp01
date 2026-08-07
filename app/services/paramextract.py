"""m79c: parameter-kinyeres (Qdrant payload) + kerdes-oldali megkotes-detektor.

Stdlib-only, fajlbol betoltheto (minta: selfrepeat/linkterm). Pilot:
notebookstore/webdoc taska-attributumok (colmeret/tipus/szin) + kategoria-nev.
Konzervativ elv: csak egyertelmu jelre adunk megkotest, es a kerdes-oldali
Qdrant-szures CSAK taska-temaju kerdesnel aktiv (bag-gate) -- "fekete pentek"
ne szurjon szinre. Ures szurt eredmenyre a hivo (retrieval) szuretlen
fallbackot ad.

m79b-nb: notebook-temaju kerdesnel LINK-oldali megkotesek (kijelzo_meret_gte,
usage) -- ezeket a build_filter_conditions szandekosan NEM forditja
Qdrant-feltetelle (nincs hozzajuk payload-mezo), csak a linkfacet hasznalja.

m80: marka-megkotes TEMA-GATE NELKUL (a marka-szo onmagaban egyertelmu jel,
follow-upban is: "es ASUS markajuak kozul?") -> Qdrant brand-szures
(match any, iras-valtozatokkal) + marka-szuros zaro-link (linkfacet).
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["extract_params", "category_tags", "detect_constraints", "build_filter_conditions"]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


# --- sync-oldali kinyeres (termeknev + text) ---

# webdoc nev-minta: 'Maximum 17.3" meretu notebookokhoz' (fold utan)
_RE_MERET_NAME = re.compile(r"maximum\s+(\d{1,2}(?:[.,]\d)?)\s*[\"\u2033']?\s*meretu")
# text-minta: 'Kategoria: Kiegeszitok > Notebook taska, hatizsak.' (eredeti, ekezetes)
# m86 POZICIO-KAPU: a builder a kategoriat MINDIG a nev/ar/(keszlet)/marka szegmens
# UTAN irja (". Kategoria: ..."), a termek-LEIRASBAN viszont elofordul ugyanilyen
# SPEC-SOR -- merve (tools/m86_fpdiag.py) a 4 Shoprenter tenanton, ahol a builder
# egyaltalan NEM ir kategoriat: "Kategoria: 6a" (halozati aljzat), "Kategoria:
# minnowbait; ..." (wobbler), "Kategoria: R12, R134a, ..." (hutokozeg-kompatibilitas).
# Ezert a match a builder POZICIOJAHOZ kotott: szoveg-eleje (szintetikus/m79c alak),
# vagy "... Ft." / "...)." / "Marka: X." utan.
_RE_CATEGORY = re.compile(
    r"(?:\A|\bFt\b|\)|m\u00e1rka:[^.\n]{1,80})[.]?[ \t]*kateg[o\u00f3]ria:[ \t]*([^\n]+)",
    re.IGNORECASE)
# m86 ERTEK-HIGIENIA (m82g-minta: ne ertekenkent foltozzunk, hanem OSZTALY-szintu alakra
# szurjunk): a valodi kategoria-nev nem tartalmaz spec-elvalasztot.
_RE_CAT_JUNK = re.compile(r"[;:\u2022]|&nbsp;")
# m86: az Unas builder a kategoriat ZAROJELBEN irja, 'Kategoria:' prefix NELKUL,
# '|'-elvalasztasu utkent:  "NEV <emdash> 3190 Ft (Epitkezes |Keziszerszam| Fogo)".
# A tobbi platform UGYANEBBE a pozicioba keszlet/elerhetoseg-jelzot ir
# ("(rendelheto, keszlet: 0 db)", "(raktaron)", "(jelenleg nincs raktaron)"),
# ezert a szo-kapu KOTELEZO -- e nelkul a Shoprenter/webdoc textbol keszlet-szoveg
# kerulne a category payloadba. A 'Kategoria:' prefixes alak MINDIG elsobbseget elvez.
_RE_CAT_PAREN = re.compile(r"\sFt\s*\(([^()]{2,160})\)\s*(?:\.|$)")
_RE_CAT_STOCKWORD = re.compile(
    r"k\u00e9szlet|rakt\u00e1ron|rendelhet|inakt\u00edv|akci\u00f3s", re.IGNORECASE)
_CAT_TAG_MIN = 3   # 2 karakteres resz-nev (pl. 'TV') tul altalanos szuro lenne
_CAT_TAG_MAX = 12


def _paren_category(text: str) -> str:
    """m86: kategoria a zarojeles (Unas) alakbol; keszlet-szoveg eseten ""."""
    m = _RE_CAT_PAREN.search(text or "")
    if not m:
        return ""
    raw = m.group(1).strip()
    if _RE_CAT_STOCKWORD.search(raw):
        return ""
    return " > ".join(x.strip() for x in raw.split("|") if x.strip())


def _cat_ok(cat: str) -> bool:
    """m86: alak-alapu kapu a leirasbol szarmazo spec-sorra (lasd _RE_CAT_JUNK)."""
    return len(cat) >= _CAT_TAG_MIN and not _RE_CAT_JUNK.search(cat)


def category_tags(category) -> list:
    """m86: a kategoria-ertek RESZ-nevei -- kulon keyword-ertekek a Qdrantban.

    A webdoc HIERARCHIA-utat ir ("Nyomtato > Tintapatron, toner"), a Sellvio/Woo
    builder viszont ', '-vel osszefuzott LISTAT ("Model Y (2020-2025), Model Y,
    Karbonszalas"). A kombinalt string mint szuro-ertek HASZNALHATATLAN (merve,
    tools/m86_catgate.py: teslashop 0% feloldas, nagyonallatshop 0%), a resz-nevekre
    bontva viszont mukodik (24% / 11%, median fedes 98/5289 ill. 550/1580).
    Ezert a `category` string VALTOZATLAN marad -- arra epul a teljes m82-es sav --,
    es a kategoria-kapu egy KULON, listas payload-kulcsot kap (`cat_tags`).
    """
    out = []
    for seg in str(category or "").split(">"):
        for part in seg.split(","):
            part = part.strip().rstrip(".").strip()
            if len(part) >= _CAT_TAG_MIN and part not in out:
                out.append(part)
                if len(out) >= _CAT_TAG_MAX:
                    return out
    return out

# m82g: a kezi _COLORS lista KIVEZETVE -- a kerdes-oldali szint a crawl-olt
# generikus szotar (facetdict, `szin` attributum) ismeri fel, kategoria-kapuval
# + tema-kapuval, es a zaro-linket is az adja (chat.py m82b aga ugyanazt az
# URL-alakot epiti, mint a linkfacet szin-moda). A SYNC-oldali extract_params
# p_szin-je VALTOZATLAN: az a termeknevbol olvas, nem a kerdesbol.


def _parse_num(whole: str, frac: str | None = None) -> float:
    if frac is not None:
        return float(f"{whole}.{frac}")
    return float(whole.replace(",", "."))


def extract_params(name: str, text: str = "") -> dict:
    """Uj payload-mezok a termeknevbol/textbol. Csak a biztosan kinyert kulcsok."""
    out: dict = {}
    fn = _fold(name)

    m = _RE_MERET_NAME.search(fn)
    if m:
        out["p_max_meret"] = _parse_num(m.group(1))

    if "hatizsak" in fn or "backpack" in fn:
        out["p_tipus"] = "hatizsak"
    elif "sleeve" in fn or re.search(r"\btok\b", fn):
        out["p_tipus"] = "tok"
    elif "taska" in fn:
        out["p_tipus"] = "valltaska"

    # szin: az utolso ' ... szinben' szegmens szavai (tobbszavas szin is: 'acelszurke',
    # 'tie dye batikolt mintas'); szeparator: kotojel vagy vesszo
    if "szinben" in fn:
        seg = re.split(r"[-,]", fn)
        for part in reversed(seg):
            if "szinben" in part:
                words = part.split("szinben")[0].split()
                if words:
                    out["p_szin"] = " ".join(words[-4:]).strip()
                break

    if text:
        cat = ""
        mc = _RE_CATEGORY.search(text)
        if mc:
            cat = mc.group(1)
            # m79b: a text egysoros -> a kategoria-nev az elso '. ' hatarig tart
            cut = cat.find(". ")
            if cut != -1:
                cat = cat[:cut]
            cat = cat.strip().rstrip(".").strip()
        else:
            cat = _paren_category(text)          # m86: Unas zarojeles alak
        if cat and _cat_ok(cat):                 # m86: pozicio- ES alak-kapu
            out["category"] = cat
            tags = category_tags(cat)            # m86
            if tags:
                out["cat_tags"] = tags
    return out


# --- kerdes-oldali megkotes-detektor (determinisztikus, konzervativ) ---

_RE_BAG_TOPIC = re.compile(r"taska|hatizsak|\btok\b|sleeve")
# m79b-nb: notebook/laptop tema -- csak link-oldali megkotesekhez
_RE_NB_TOPIC = re.compile(r"notebook|laptop|ultrabook")
# '17', '17,3', '17.3' + egyertelmu egyseg/rag: '"', col/colos, inch, huvelyk, -os/-es
_RE_MERET_Q = re.compile(
    r"\b(1[0-8])(?:[.,](\d))?\s*(?:[\"\u2033']|col\w*|inch\w*|huvelyk\w*|-?os\b|-?es\b)"
)
# m82c: a kezi _USAGE_WORDS lista KIVEZETVE -- a felhasznalas-jelleget a
# crawl-olt generikus szotar (facetdict) ismeri fel, kategoria-kapuval, es a
# zaro-linket is az adja (chat.py m82b fallback-aga).
# m80: gyakori markak (fold-olt) -- a payload brand-ertekek iras-valtozatait a
# build_filter_conditions kepzi; a linkfacet a marka-szuro slugjaval matchel.
# m82h/2 ota ez CSAK FALLBACK: ha van tenant-terkep (data/brand_map_<client>.json),
# a felismeres onnan jon (branddict) -- ez a lista terkep/client_id nelkul fut.
_BRANDS = (
    "asus", "acer", "lenovo", "dell", "apple", "msi", "samsung", "huawei",
    "microsoft", "fujitsu", "toshiba", "xiaomi", "gigabyte", "honor",
    "brother", "epson", "canon", "logitech", "synology", "kingston",
    "tp-link", "targus", "philips", "dicota", "hp", "lg",
)
# marka -> tovabbi pontos payload-ertekek (ahol az iras-valtozat nem eleg)
_BRAND_PAYLOAD_ALIASES = {
    "msi": ("MSI (Micro-Star International)",),
    "tp-link": ("TP-Link",),
}


def _meret_from_q(fm: str) -> float | None:
    """Colmeret a kerdesbol.

    Kizarasok: 'windows 11-es' szoftver-verzio nem meret; ha az uzenetben
    RAM es SSD szo is van (beillesztett termeknev-spec), a benne szereplo
    colmeret a termek adata, nem kerdes-oldali igeny (m80 guard).
    """
    if re.search(r"\bram\b", fm) and re.search(r"\bssd\b", fm):
        return None
    for m in _RE_MERET_Q.finditer(fm):
        pre = fm[max(0, m.start() - 9):m.start()]
        if "windows" in pre:
            continue
        return _parse_num(m.group(1), m.group(2))
    return None


def _brand_from_dict(message: str, client_id: str):
    """m82h/2: (kulcs, nyers payload-ertekek) a tenant marka-terkepebol.

    VAN terkep -> (kulcs, ertekek) vagy ("", []) ha a kerdesben nincs a bolt
    markai kozul valo. NINCS terkep / nincs client_id / barmi hiba -> None,
    es a hivo a mai kezi _BRANDS listara esik vissza (fail-safe).
    """
    if not client_id:
        return None
    try:
        from app.services.branddict import detect_brand, load_map
    except Exception:  # noqa: BLE001 - fajl-betoltes (sync-oldali import-fuggetlenseg)
        try:
            import importlib.util as _ilu
            import pathlib as _pl
            _p = _pl.Path(__file__).resolve().parent / "branddict.py"
            _spec = _ilu.spec_from_file_location("cx_branddict_dyn", _p)
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            detect_brand, load_map = _mod.detect_brand, _mod.load_map
        except Exception:  # noqa: BLE001
            return None
    try:
        bmap = load_map(client_id)
        if not bmap:
            return None
        return detect_brand(message, bmap)
    except Exception:  # noqa: BLE001 - a szotar hibaja ne torje a retrievalt
        return None


def detect_constraints(message: str, client_id: str = "") -> dict:
    """Egyertelmu megkotesek a kerdesbol.

    Taska-temanal (bag-gate, elsobbseg): p_max_meret_gte / p_tipus -- ezek a
    Qdrant-szurest IS hajtjak (build_filter_conditions). A p_szin m82g ota
    NEM innen jon (generikus szotar), de a build_filter_conditions tovabbra is
    lefordit egy kivulrol kapott p_szin-t.
    Notebook-temanal (m79b-nb): kijelzo_meret_gte / usage -- CSAK a zaro
    fasetta-linkhez (linkfacet).
    Marka (m80): tema-gate nelkul -- Qdrant brand-szures ES zaro-link is.
    """
    fm = _fold(message)
    out: dict = {}
    if _RE_BAG_TOPIC.search(fm):
        v = _meret_from_q(fm)
        if v is not None:
            out["p_max_meret_gte"] = v

        if "hatizsak" in fm or "backpack" in fm:
            out["p_tipus"] = "hatizsak"
        elif "valltaska" in fm:
            out["p_tipus"] = "valltaska"
        elif "sleeve" in fm or re.search(r"\btok\b", fm):
            out["p_tipus"] = "tok"
        # generikus 'taska' -> NINCS tipus-szures (a hatizsak is taska)
    elif _RE_NB_TOPIC.search(fm):
        v = _meret_from_q(fm)
        if v is not None:
            out["kijelzo_meret_gte"] = v

    # m82h/2: a marka-szotar a tenant VALODI Qdrant brand-ertekeibol jon
    # (branddict + data/brand_map_<client_id>.json, tools/brand_map_crawl.py).
    # A SZURO-UT valtozatlan: a brand payload must-feltetel szur.
    _bd = _brand_from_dict(message, client_id)
    if _bd is not None:
        # VAN terkep -> AZ dont (a kezi listara nem esunk vissza): amit a bolt
        # nem arul, arra ne szurjunk (a mai listaval az 0 talalat + fallback volt)
        _bk, _bvals = _bd
        if _bk:
            out["brand"] = _bk.replace(" ", "-")  # slug-alak: a linkfacet igy matchel
            out["brand_vals"] = _bvals
        return out
    # m80: marka tema-gate nelkul (FALLBACK: nincs terkep / nincs client_id)
    for b in _BRANDS:
        if re.search(r"\b" + re.escape(b) + r"\b", fm):
            out["brand"] = b
            break
    return out


def _brand_variants(b: str) -> list[str]:
    """A Qdrant brand payload lehetseges iras-valtozatai (match any lista)."""
    variants = [b, b.upper(), b.capitalize(), b.title()]
    variants.extend(_BRAND_PAYLOAD_ALIASES.get(b, ()))
    seen: list[str] = []
    for v in variants:
        if v not in seen:
            seen.append(v)
    return seen


def build_filter_conditions(cons: dict) -> list[dict]:
    """Qdrant must-feltetelek a detect_constraints kimenetebol. Ures dict -> ures lista.

    A p_* kulcsokbol, a brand-bol es (m81 ota) a kijelzo_meret_gte-bol epit
    feltetelt. A usage szandekosan kimarad: azt a retrieval m76-os aga
    kezeli (qdrant.search(usage=), sajat fallbackkal).
    """
    must: list[dict] = []
    if not cons:
        return must
    v = cons.get("p_max_meret_gte")
    if isinstance(v, (int, float)):
        must.append({"key": "p_max_meret", "range": {"gte": float(v)}})
    if cons.get("p_tipus"):
        must.append({"key": "p_tipus", "match": {"value": cons["p_tipus"]}})
    if cons.get("p_szin"):
        must.append({"key": "p_szin", "match": {"value": cons["p_szin"]}})
    if cons.get("brand_vals"):  # m82h/2: a terkepbol jott VALODI payload-ertekek
        must.append({"key": "brand", "match": {"any": list(cons["brand_vals"])}})
    elif cons.get("brand"):
        must.append({"key": "brand", "match": {"any": _brand_variants(cons["brand"])}})
    # m81: kijelzo-meret mar Qdrant-szuro is (p_kijelzo payload, a
    # usage_crawl kijelzo-meret JOB-ja irja a bolt szurojebol, egesz
    # szamkent: 173 = 17.3"). Csak akkor szurunk, ha a kerdes tenyleg
    # meretet ad meg -- a link-oldali viselkedes valtozatlan.
    v = cons.get("kijelzo_meret_gte")
    if isinstance(v, (int, float)):
        must.append({"key": "p_kijelzo", "range": {"gte": int(round(float(v) * 10))}})
    return must

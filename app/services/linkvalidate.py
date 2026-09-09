"""m98: LINK-UTÓVALIDÁCIÓ — a válaszban kiment termék-linkek determinisztikus
ellenőrzése, a m77/m87/m96 mintájára (erre az osztályra a prompt-szabály
bizonyítottan nem elég).

KIVÁLTÓ ESET (Fecó, 2026-09-08, kellegyszerszam): „Autó emelőt keresek" ->
2T/4T/5T/12T palack emelő, MIND a 12T URL-jén; „Ásó" -> 3 PALISAD ásó egy
RUSSIA URL-en. A név helyes, az URL nem.

MÉRT LELET (d09b_ctxscan.py, 144 valódi válasz / 261 termék-link, 08-26 óta):
  - 167 link (64%) URL-je benne volt a MOSTANI retrieval-kontextusban,
  - 83 link (32%) létező termékre mutat, de a mostani poolban NINCS benne
    (page_context terméke, korábbi fordulóból örökölt link, SKU-s follow-up),
  - 11 link (4,2%) FABRIKÁLT slug: a katalógusban nem létezik -> garantált 404.

TERVEZÉSI DÖNTÉS. Kézenfekvő lett volna a kontextushoz hasonlítani (ez volt az
eredeti terv), DE a fenti 32% miatt az a szabály 94 linkből 83 JÓT vágna el.
A hivatkozási alap ezért a KATALÓGUS (Qdrant `url` payload, m67 óta keyword-
indexelt): csak a kontextuson kívüli URL-eket kell lekérdezni, és csak a
BIZONYÍTOTTAN hiányzó linket bontjuk szét. A „nem illő név -> link kivétele"
ág is kimaradt: a 25 névbeli eltérésből a többség írásmód-különbség
(„sitteszsák" vs „Sittes zsák") vagy mutató anchor („termékoldalt", „ez itt,
amit épp nézel") — ezekre a laza névegyezés-mérce FP-t gyárt. Csere CSAK
PONTOS (normalizált) névegyezésnél.

Két szabály:
  R1 TÖRLÉS   — terméknévszerű anchor + termék-alakú URL + a katalógusból
                bizonyítottan hiányzik -> a link markup kikerül, a szöveg marad.
  R2 CSERE    — az anchor normalizálva PONTOSAN egyezik egy másik kontextusbeli
                termék nevével -> URL-csere.
Minden más érintetlen.

PURE, stdlib-only modul (mint a linkgate.py): az I/O (Qdrant-lookup) a hívóé,
így a teszt közvetlenül fájl-betöltheti.
"""

import re
import unicodedata

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

# a feed-ekből átjövő HTML-entitások (a Qdrant `name` payloadban is benne vannak:
# 'YATO Láncfűrész láncvezető 15&quot; 0,325"')
_ENT = {
    "&quot;": '"', "&amp;": "&", "&#039;": "'", "&apos;": "'",
    "&nbsp;": " ", "&lt;": "<", "&gt;": ">", "&#34;": '"', "&#38;": "&",
}

# mutató / nem termék-nevű anchorok: ezekre SOHA nem nyúlunk (a látogató a
# page_context termékét nézi, vagy policy-oldalra mutat a link)
_DEICTIC = (
    "termekoldal", "termeklap", "adatlap", "ez itt", "amit epp", "amit eppen",
    "nezed", "nezel", "kattint", "itt talalod", "itt elerheto", "reszletek",
    "bovebben", "tovabbi talalat", "webaruhaz", "kereso", "keresoben",
    "aszf", "adatkezel", "szallitas", "kapcsolat", "vasarlasi feltetel",
)

# kereső-/kategória-/címke-linkek: az m25/m62/m79b/m82b ág terméke, nem termék-URL
_SEARCHY = ("/termek-kereses", "/kereses", "/search", "?k=", "&k=", "/cimke/", "/kategoria")

_CODE = re.compile(r"(?=[a-z0-9]*[a-z])(?=[a-z0-9]*[0-9])[a-z0-9]{4,}")


def fold(s) -> str:
    s = str(s or "").lower()
    for k, v in _ENT.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm_name(s) -> str:
    """Ékezet nélküli, kisbetűs, csak alfanumerikus tokenekből álló alak."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", fold(s)).split())


def tight(s) -> str:
    """Szóköz nélküli alak — a '550 x 1100' vs '550x1100' írásmódra."""
    return norm_name(s).replace(" ", "")


def is_product_anchor(anchor) -> bool:
    """Terméknévszerű-e az anchor (>=2 token vagy típuskód), és nem mutató szó."""
    f = norm_name(anchor)
    if not f:
        return False
    for d in _DEICTIC:
        if d in f:
            return False
    if len(f.split()) >= 2:
        return True
    return bool(_CODE.search(f))


def url_key(url) -> str:
    """Összehasonlítható URL-alak (fragment le, záró / le)."""
    return str(url or "").split("#")[0].rstrip("/")


def _parts(url):
    m = re.match(r"(https?://[^/]+)(/[^?#]*)?", str(url or ""))
    if not m:
        return "", []
    return m.group(1), [s for s in (m.group(2) or "").split("/") if s]


def shapes(urls) -> set:
    """A tenant termék-URL-jeinek alakja: (host, path-melyseg, elso szegmens).

    Enélkül a policy-oldalak (ÁSZF, szállítás) is „ismeretlen URL"-nek
    látszanának, hiszen a Qdrantban nincsenek termékként.
    """
    out = set()
    for u in urls or []:
        host, segs = _parts(u)
        if not host:
            continue
        out.add((host, len(segs), segs[0] if len(segs) > 1 else ""))
    return out


def same_shape(url, shp) -> bool:
    host, segs = _parts(url)
    if not host:
        return False
    return (host, len(segs), segs[0] if len(segs) > 1 else "") in (shp or set())


def lookup_candidates(reply, ctx_urls, limit: int = 4) -> list:
    """Mely URL-eket kell a katalógusban ellenőrizni (a kontextusban lévők nem).

    Plafon: a latency ne fusson el — a mérésben válaszonként átlag <1 ilyen van.
    """
    ctx = {url_key(u) for u in (ctx_urls or set())}
    shp = shapes(ctx)
    if not shp:
        return []                       # fail-safe: alak nélkül nem validálunk
    out: list = []
    for anchor, url in _LINK.findall(reply or ""):
        k = url_key(url)
        if k in ctx or any(s in url for s in _SEARCHY):
            continue
        if not is_product_anchor(anchor) or not same_shape(k, shp):
            continue
        if k not in out:
            out.append(k)
    return out[:limit]


def apply_fixes(reply, ctx, missing) -> tuple:
    """-> (uj_valasz, {"removed": n, "retargeted": n})

    ctx     : {url: termeknev} a kontextusbol (hits + page_context terméke)
    missing : a katalogusbol BIZONYITOTTAN hianyzo URL-ek halmaza
    """
    info = {"removed": 0, "retargeted": 0}
    if not reply:
        return reply, info
    ctxk = {url_key(u): str(n or "") for u, n in (ctx or {}).items()}
    miss = {url_key(u) for u in (missing or set())}
    exact: dict = {}
    for u, n in ctxk.items():
        if n:
            exact.setdefault(norm_name(n), u)
            exact.setdefault(tight(n), u)

    def _repl(m):
        anchor, url = m.group(1), m.group(2)
        k = url_key(url)
        if any(s in url for s in _SEARCHY) or not is_product_anchor(anchor):
            return m.group(0)
        if k in miss:                                   # R1
            info["removed"] += 1
            return anchor
        name = ctxk.get(k)
        if name:                                        # R2
            an, at = norm_name(anchor), tight(anchor)
            if an != norm_name(name) and at != tight(name):
                tgt = exact.get(an) or exact.get(at)
                if tgt and url_key(tgt) != k:
                    info["retargeted"] += 1
                    return "[%s](%s)" % (anchor, tgt)
        return m.group(0)

    return _LINK.sub(_repl, reply), info

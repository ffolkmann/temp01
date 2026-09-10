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

m98/1 (2026-09-10, d10a mérés, 31 napos teljes korpusz, 2500 linkes válasz):
  - R1 PLATFORM-KAPU. A „katalógusban nincs => fabrikált" premissza CSAK Unason
    igaz. HTTP-ellenőrzés az R1 által vágandó URL-eken: kellegyszerszam 24/26
    404 (a maradék: követő-paraméteres élő link, ld. lent), DE copygo 22/23 és
    fishingoutlet 28/32 ÉLŐ termékoldal, notebookstore 4/4 élő (a Shoprenter/
    Webdoc index nem teljes, a bolti kereső-fallback nem indexelt élő terméket
    is ad, és a /withdrawal, /adatvedelmi-szabalyzat oldal is termék-alakú).
    Ezért R1 csak `r1_enabled(platform)` esetén vág; máshol a hívó shadow-logol.
  - Követő paraméterek (gad_*, gclid, utm_*, fbclid…) le a kulcsból: a Google
    Ads-ből érkező látogató page_context URL-je élő termék, a query miatt
    „hiányzónak" látszott.
  - Kereső-minták: Unas shop_search.php?search=, WooCommerce ?s=&post_type=,
    Shoprenter keyword= (nagyonallatshopon 3 kereső-link termék-alakú volt).
  - Szabályzat-anchorok a mutató szavak közé (elállási nyilatkozat, adatvédelmi
    szabályzat, jótállás bejelentése).
  - R2b SZÁM/KÓD-CSERE. Ha a linkelt (kontextusbeli) termék neve NEM fedi az
    anchor valamelyik szám/kód-tokenjét („2T" vs „12T"), és a kontextusban
    PONTOSAN EGY termék fedi az anchor minden tokenjét (a számokat azonos
    sorrendben) -> URL-csere. Szám/kód-token csak a név egymás utáni tokenjeinek
    PONTOS összefűzéseként illeszkedik („205x275mm" = „205x"+„275"+„mm", de
    „bq1105" != „bq1105w", „2t" != „12t"). Betűs eltérésre NINCS csere
    (katalógus-mérés: „YATO vezetőlemez" -> láncvezető-lemez FESZÍTŐ lett volna).
    Mérés (kontextus-pool): kellegyszerszam 10 jelölt, kézzel 10/10 helyes;
    notebookstore / copygo / nagyonallatshop: 0 jelölt.

m98/2 (2026-09-10, d10a_m982scan, 6 tenant):
  - (B) A hívó a kontextuson KÍVÜLI, de a katalógusban létező linkelt termék
    NEVÉT is átadja (find_by_url payload) -> R2/R2b arra is fut. Mérés:
    kellegyszerszam +3 csere (MAGUS Stereo 8TH, DENZEL 1200W 15L, FIELDMANN
    FZG 3011), kézzel 3/3 helyes; a többi tenanton 0.
  - R3 URL-JAVÍTÁS: (a) dupla URL („https://x/hu/https://x/hu/…") -> a belső
    URL; (b) elírt útvonal-előtag („/termem/<slug>") -> a tenant termék-alakja
    ugyanazzal a sluggal. CSAK ha a javított URL a kontextusban van vagy a
    katalógus-lookup igazolja (a hívó dönt). Mérés: teslashop 3 dupla URL,
    nagyonallatshop 2 „/termem/" — mind létező termékre javul.
  - A laza betű-fedés (R2c, T=0,85…0,66) a B-n felül 0 új jelöltet adott ->
    NEM került be.
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
    "elallasi", "adatvedelm", "jotallas bejelent",                 # m98/1
)

# kereső-/kategória-/címke-linkek: az m25/m62/m79b/m82b ág terméke, nem termék-URL
_SEARCHY = ("/termek-kereses", "/kereses", "/search", "?k=", "&k=", "/cimke/", "/kategoria",
            # m98/1: Unas / WooCommerce / Shoprenter bolti kereső
            "shop_search", "search=", "keyword=", "?s=", "&s=", "post_type=", "route=product/list")

# m98/1: követő paraméterek — a kulcsból kiesnek (a nem-követő query marad)
_TRACK = re.compile(
    r"^(utm_[a-z0-9_]+|gclid|gbraid|wbraid|gad_source|gad_campaignid|fbclid|msclkid|srsltid|_gl|mc_cid|mc_eid)$",
    re.I)

# m98/1: R1 (törlés) csak ott, ahol a premissza MÉRVE van (d10a: Unas 24/26 404;
# Shoprenter/Webdoc: a „hiányzó" URL-ek ~90%-a élő oldal)
R1_PLATFORMS = frozenset({"unas"})

_STOP = frozenset({"es", "az", "egy", "db", "ft", "the", "and", "raktaron",
                   "keszleten", "akcios", "uj", "is"})

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
    """Összehasonlítható URL-alak (fragment le, követő paraméterek le, záró / le).

    A nem-követő query-t (pl. Shoprenter index.php?route=...&product_id=) BETŰRE
    megtartja — nincs újrakódolás, különben a katalógus-URL-lel nem egyezne.
    """
    u = str(url or "").split("#")[0]
    if "?" in u:
        base, q = u.split("?", 1)
        keep = [p for p in q.split("&") if p and not _TRACK.match(p.split("=", 1)[0])]
        u = base + ("?" + "&".join(keep) if keep else "")
    return u.rstrip("/")


def r1_enabled(platform) -> bool:
    """Vághat-e az R1 ezen a platformon (ld. R1_PLATFORMS)."""
    return str(platform or "").strip().lower() in R1_PLATFORMS


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


def _hasdig(t) -> bool:
    return any(c.isdigit() for c in t)


def content_tokens(s) -> list:
    """Tartalmi tokenek: szám/kód-token mindig, betű-token >=3 karakter, stopszó nélkül."""
    return [t for t in norm_name(s).split()
            if t not in _STOP and (_hasdig(t) or len(t) >= 3)]


def _nums(s) -> list:
    return re.findall(r"[0-9]+", norm_name(s))


def _prep(name) -> tuple:
    nt = norm_name(name).split()
    return nt, "".join(nt), _nums(name)


def _dig_cov(tok, nt) -> bool:
    """Szám/kód-token: a név EGYMÁS UTÁNI tokenjeinek pontos összefűzése."""
    n = len(nt)
    for i in range(n):
        acc = ""
        for j in range(i, min(n, i + 5)):
            acc += nt[j]
            if acc == tok:
                return True
            if len(acc) >= len(tok):
                break
    return False


def _subseq(a, b) -> bool:
    it = iter(b)
    return all(x in it for x in a)


def _covers(toks, nums, p) -> bool:
    nt, tn, pn = p
    if not toks:
        return False
    for t in toks:
        if _hasdig(t):
            if not _dig_cov(t, nt):
                return False
        elif t not in tn:
            return False
    return _subseq(nums, pn)


def numeric_retarget(anchor, key, ctxp):
    """R2b: szám/kód-eltérés a linkelt névvel + PONTOSAN EGY teljes fedésű
    kontextus-termék -> annak kulcsa; különben None."""
    toks = content_tokens(anchor)
    if len(toks) < 2 or key not in ctxp:
        return None
    dt = [t for t in toks if _hasdig(t)]
    if not dt or all(_dig_cov(t, ctxp[key][0]) for t in dt):
        return None
    nums = _nums(anchor)
    hit = [k for k, p in ctxp.items() if _covers(toks, nums, p)]
    if len(hit) != 1 or hit[0] == key:
        return None
    return hit[0]


def repair_guesses(reply, ctx_urls, limit: int = 4) -> dict:
    """R3 (m98/2): hibás termék-URL javítás-JELÖLTJEI -> {url_key(eredeti): [tipp, ...]}.

    (a) dupla URL: a legutolsó 'http' utáni belső URL;
    (b) elírt útvonal-előtag: ha az URL NEM termék-alakú, a tenant termék-alakjaiból
        (kontextus) épített URL ugyanazzal az utolsó szegmenssel.
    Csak terméknév-anchor, csak kontextuson kívüli, nem kereső-URL. A tippet a
    hívónak kell igazolnia (kontextus vagy katalógus-lookup) — itt nincs I/O.
    """
    ctx = {url_key(u) for u in (ctx_urls or ())}
    shp = shapes(ctx)
    out: dict = {}
    for anchor, url in _LINK.findall(reply or ""):
        k = url_key(url)
        if k in ctx or k in out or any(s in url for s in _SEARCHY):
            continue
        if not is_product_anchor(anchor):
            continue
        guesses = []
        i = url.rfind("http")
        if i > 0:
            guesses.append(url_key(url[i:]))
        elif shp and not same_shape(k, shp):
            host, segs = _parts(k)
            if host and segs:
                slug = segs[-1]
                for h, depth, s0 in sorted(shp):
                    if h != host:
                        continue
                    if depth == 1:
                        g = "%s/%s" % (h, slug)
                    elif depth == 2 and s0:
                        g = "%s/%s/%s" % (h, s0, slug)
                    else:
                        continue
                    if g != k and g not in guesses:
                        guesses.append(g)
        if guesses:
            out[k] = guesses[:2]
        if len(out) >= limit:
            break
    return out


def apply_fixes(reply, ctx, missing, repaired=None) -> tuple:
    """-> (uj_valasz, {"removed": n, "retargeted": n})

    ctx     : {url: termeknev} a kontextusbol (hits + page_context terméke)
    missing : a katalogusbol BIZONYITOTTAN hianyzo URL-ek halmaza
    """
    info = {"removed": 0, "retargeted": 0, "num": 0, "repaired": 0}
    if not reply:
        return reply, info
    ctxk = {url_key(u): str(n or "") for u, n in (ctx or {}).items()}
    miss = {url_key(u) for u in (missing or set())}
    reps = {url_key(u): str(v) for u, v in (repaired or {}).items() if v}
    exact: dict = {}
    for u, n in ctxk.items():
        if n:
            exact.setdefault(norm_name(n), u)
            exact.setdefault(tight(n), u)
    ctxp = {u: _prep(n) for u, n in ctxk.items() if n}

    def _repl(m):
        anchor, url = m.group(1), m.group(2)
        k = url_key(url)
        if any(s in url for s in _SEARCHY) or not is_product_anchor(anchor):
            return m.group(0)
        if k in reps:                                   # R3 (m98/2)
            info["repaired"] += 1
            return "[%s](%s)" % (anchor, reps[k])
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
                tgt = numeric_retarget(anchor, k, ctxp)      # R2b (m98/1)
                if tgt:
                    info["num"] += 1
                    return "[%s](%s)" % (anchor, tgt)
        return m.group(0)

    return _LINK.sub(_repl, reply), info


def absolutize_links(reply, base):
    """m101: a domain nelkuli markdown-link celjat a tenant alap-URL-jevel egesziti ki.

    d10b: 4mfrigon 8 link ment ki "[FCP ...](fcp-univerzalis-lyuk-takaro-1539)"
    alakban -> torott link. Abszolut, mailto:, tel:, # es // cel erintetlen.
    Visszaad: (uj_valasz, javitott_db).
    """
    import re as _re
    b = str(base or "").strip()
    if not b.lower().startswith(("http://", "https://")):
        return reply, 0
    b = b.rstrip("/")
    n = [0]

    def _fix(m):
        tgt = m.group(2)
        low = tgt.lower()
        if low.startswith(("http://", "https://", "mailto:", "tel:", "#", "//")):
            return m.group(0)
        if low.startswith("www."):
            n[0] += 1
            return "[%s](https://%s)" % (m.group(1), tgt)
        if ":" in tgt.split("/")[0]:
            return m.group(0)
        if not _re.match(r"^/?[A-Za-z0-9][A-Za-z0-9._~%/+-]*(\?\S*)?$", tgt):
            return m.group(0)
        n[0] += 1
        return "[%s](%s/%s)" % (m.group(1), b, tgt.lstrip("/"))

    new = _re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _fix, str(reply or ""))
    return new, n[0]

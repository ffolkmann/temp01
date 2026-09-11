"""m103: hamis "nem talaltam" ellen - cikkszam- es lexikai nev-ag a dense pool mellett.

Mert lelet (d10d_fn2, 30 napos korpusz, 288 "nincs / nem talaltam" valasz termek-
kerdesre, kezzel igazolva): ~10 esetben a kert termek MEGVAN az indexunkben (tobbnyire
raktaron), a dense kereses megsem hozza fel - a kerdes tartalmas szavai (marka, tipus,
kod, fonev) szo szerint a termek neveben vannak ("Huawei Luna ... 3F 80A", "Gaz grill",
"Venom amur wafter", "Horgasz fotelt keresek"), vagy cikkszamra kerdeztek ("yt82992" ->
sku YT-82992). A m25 bolti fallback nem segitett: a pool top score-ja 0.55 folott volt.

Mukodes (fail-safe, a hivo try-ban hivja):
- tenantonkent memoriaban tartott, ekezet nelkuli nev + normalizalt sku lista (Qdrant
  scroll, 30 perces TTL; ha nincs kesz, hatterben epul, addig a pool valtozatlan);
- CIKKSZAM-AG: kodszeru token (>=3 szamjegy, >=5 alnum karakter) -> sku pontos vagy
  (betus tokennel) vegzodes-egyezes (Unas szallito-elotag: P-YT-24231);
- NEV-AG: a kerdes tartalmas tokenjei IDF-sulyozott fedese; csak ha a pool legjobb
  nev-fedese elmarad (margo), a legjobb szint eleg specifikus (<= _TIER_MAX termek),
  es a fedes >= _MIN_COVER;
- osszesen legfeljebb _MAX_ADD termek kerul a pool VEGERE (a pool-limit nem no).
Nem fut: ar-szuperlativusznal (sajat, ar szerint rendezett pool), szabalyzat-kerdesnel.
"""
import asyncio
import logging
import math
import re
import time
import unicodedata

logger = logging.getLogger("cx.lexmatch")

_TTL = 1800.0
_MAX_ADD = 3
_MIN_COVER = 0.75
_MARGIN = 0.15
_TIER_MAX = 12
_MAX_QTOK = 8

# client_id -> (epites ideje, [(id, name_fold, sku_norm, available), ...])
_cache: dict = {}
_building: set = set()

STOP = set("""a az es egy van vannak keresek keresnek kerestem keresem keresnem kellene kell kene szeretnek
szeretnem szeretne szeretnenk milyen olyan olyat hozza ehhez ahhoz nektek nalatok nalad nalunk is meg ami amit
amivel amibe amihez lenne tudtok tudsz tudna tudnal ajanlani ajanlasz ajanlanal ajanlj ajanl valami valamit
valamilyen hogy nem de mert vagy ha szia hello helo hali udv udvozlom koszonom kerem kerek esetleg lehet itt ott
erre arra ilyen melyik mennyi mennyibe mennyiert kerul ara aron arat olcso olcson olcsobb draga jobb legjobb
raktaron raktar keszleten kaphato kaphatok kapni venni vennek vasarolni rendelni erdekel erdekelne erdekelnenek
erdeklodnek erdeklodom termek termeket termekek termeketek dolog dolgot hol mikor tudom nekem nekunk ezt azt ezek
azok the for with and mit most mar csak minden egyeb masik fajta tipus tipusu szinu meretu darab cikkszamu
cikkszam cikkszamot pedig igy ugy max min nagy kis kicsi ido idot nap napot napon napra het hetet ora oras perc
oldal oldalon oldalra hely helyen helyre fele mennyire menyire
""".split())

_TOK = re.compile(r"[a-z0-9]+")
# d10d FP-sweep: nehany bolt (copygo) "termekneve" marketing-mondat ("Nagy kepernyos
# parhuzamos feladatvegzes. Konfigu...") -> a nev-agban nem jelolt
_MKT = re.compile(r"[a-z]{3}\. [a-z]|&lt;|&gt;|<br")
_SKU_RAW = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]*[A-Za-z0-9]")
# m104: csupa-szam token utan penznem -> osszeg, nem cikkszam ("20000 ft-om", "43.590 Ft")
_MONEY = re.compile(r"\s*(?:-\s*)?(?:ft\b|ft-|forint|huf\b|eur\b|euro|\u20ac)", re.I)


def fold(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def norm_sku(s):
    return re.sub(r"[^a-z0-9]", "", fold(s))


def _has_digit(t):
    return any(c.isdigit() for c in t)


def query_tokens(message):
    """A kerdes tartalmas tokenjei (foldolt, egyedi, sorrendtarto, max _MAX_QTOK)."""
    out = []
    for t in _TOK.findall(fold(message)):
        if t in STOP or t in out:
            continue
        if _has_digit(t):
            if t.isdigit() and len(t) < 3:
                continue
            if len(t) < 2:
                continue
        elif len(t) < 3:
            continue
        out.append(t)
    return out[:_MAX_QTOK]


def sku_tokens(message):
    """Kodszeru tokenek normalizalva: >=3 szamjegy, >=5 alnum karakter, nem telefonszam-szeru."""
    out = []
    msg = str(message or "")
    for mt in _SKU_RAW.finditer(msg):
        raw = mt.group(0)
        n = norm_sku(raw)
        digits = sum(c.isdigit() for c in n)
        if len(n) < 5 or digits < 3:
            continue
        if n.isdigit() and len(n) >= 9:  # telefonszam / rendelesszam-gyanu
            continue
        if n.isdigit() and (_MONEY.match(msg, mt.end()) or msg[max(0, mt.start() - 1):mt.start()] == "#"):
            continue  # m104: osszeg ("20000 ft-om") vagy rendelesszam ("#30781")
        if n not in out:
            out.append(n)
    return out[:3]


def _stem(t):
    if _has_digit(t) or len(t) <= 5:
        return t
    return t[:max(5, len(t) - 3)]


def _matcher(t):
    """A kerdes-token illesztoje egy foldolt nevre.
    Szamos token: onallo tokenkent (80a, 2kg, 3f); rovid (<=4): szokezdet;
    hosszabb: a to (toldalek nelkul) resz-szokent is (osszetett szo: horgaszfotel)."""
    st = _stem(t)
    if not _has_digit(t) and len(st) >= 6:
        return lambda nf: st in nf
    # d10d FP-sweep: a rovid to resz-szokent ("kapta" -> kaptar, "szep" -> szepiacsont)
    # veletlen neveket fogott -> csak szokezdeten
    lb = r"(?<![a-z0-9.,])" if (_has_digit(t) and not t.isdigit()) else r"(?<![a-z0-9])"
    rx = re.compile(lb + re.escape(st) + (r"(?![a-z0-9])" if _has_digit(t) else ""))
    return lambda nf: st in nf and rx.search(nf) is not None


def _codelike(t):
    return _has_digit(t) and any(c.isalpha() for c in t) and len(t) >= 4


def _cover(qt, idf, nf, matchers):
    tot = sum(idf[t] for t in qt)
    if tot <= 0:
        return 0.0
    return sum(idf[t] for t in qt if matchers[t](nf)) / tot


def pick(entries, message, pool_names, hide_oos=False, exclude_ids=()):
    """Tiszta fuggveny (tesztelheto): -> (sku_ids, name_ids, info)."""
    info = {}
    excl = set(str(x) for x in exclude_ids)

    def usable(e):
        return (not hide_oos or e[3]) and str(e[0]) not in excl

    sku_ids = []
    for s in sku_tokens(message):
        hit = [e for e in entries if e[2] and usable(e)
               and (e[2] == s or (len(s) >= 6 and not s.isdigit() and e[2].endswith(s)))]
        hit.sort(key=lambda e: (not e[3], len(e[1]), str(e[0])))
        for e in hit[:_MAX_ADD]:
            if e[0] not in sku_ids:
                sku_ids.append(e[0])
    sku_ids = sku_ids[:_MAX_ADD]
    qt = query_tokens(message)
    name_ids = []
    if not qt or len(sku_ids) >= _MAX_ADD:
        return sku_ids, name_ids, info
    matchers = {t: _matcher(t) for t in qt}
    idx = {t: [i for i, e in enumerate(entries) if matchers[t](e[1])] for t in qt}
    df = {t: len(v) for t, v in idx.items()}
    known = [t for t in qt if df[t] > 0]
    info["qt"] = qt
    info["df"] = df
    if not known:
        return sku_ids, name_ids, info
    n = max(1, len(entries))
    idf = {t: math.log((n + 1.0) / (df[t] + 1.0)) for t in known}
    tot = sum(idf.values())
    if tot <= 0:
        return sku_ids, name_ids, info
    pool_best = max((_cover(known, idf, fold(nm), matchers) for nm in pool_names), default=0.0)
    info["pool"] = round(pool_best, 3)
    if pool_best >= 0.99:
        return sku_ids, name_ids, info
    acc = {}
    for t in known:
        w = idf[t] / tot
        for i in idx[t]:
            acc[i] = acc.get(i, 0.0) + w
    skip = set(str(x) for x in sku_ids)
    scored = [(c, entries[i]) for i, c in acc.items()
              if usable(entries[i]) and str(entries[i][0]) not in skip and not _MKT.search(entries[i][1])]
    if not scored:
        return sku_ids, name_ids, info
    best = max(c for c, _ in scored)
    tier = [e for c, e in scored if c >= best - 1e-9]
    info["best"] = round(best, 3)
    info["tier"] = len(tier)
    full = best >= 0.999  # teljes fedes (pl. a poolban csak a testver-variant: 100A vs 80A)
    if best >= _MIN_COVER and (best >= pool_best + _MARGIN or full) and len(tier) <= _TIER_MAX:
        # d10d FP-sweep: egyetlen illeszkedo koznyelvi szo (cseveges: "kaptam", "szep",
        # "mindkettot") nem eleg - legalabb 2 kerdes-token, vagy egy ritka kodszeru token
        def strong(e):
            mt = [t for t in known if matchers[t](e[1])]
            return len({_stem(t) for t in mt}) >= 2 or any(_codelike(t) and df[t] <= 10 for t in mt)
        tier = [e for e in tier if strong(e)]
        info["strong"] = len(tier)
        tier.sort(key=lambda e: (not e[3], len(e[1]), str(e[0])))
        name_ids = [e[0] for e in tier[:_MAX_ADD - len(sku_ids)]]
    return sku_ids, name_ids, info


async def _build(client_id):
    from app.core.qdrant import get_qdrant
    q = get_qdrant()
    pts = await q.scroll_products(q.collection, client_id, ["name", "sku", "available"])
    ent = []
    for p in pts:
        pl = p.get("payload") or {}
        nm = fold(pl.get("name"))
        if not nm:
            continue
        ent.append((p.get("id"), nm, norm_sku(pl.get("sku")), bool(pl.get("available", True))))
    _cache[client_id] = (time.monotonic(), ent)
    logger.info("m103 lexmatch: katalogus kesz client=%s n=%d", client_id, len(ent))


async def _build_guarded(client_id):
    if client_id in _building:
        return
    _building.add(client_id)
    try:
        await _build(client_id)
    except Exception:  # noqa: BLE001
        logger.exception("m103 lexmatch: katalogus-epites hiba client=%s", client_id)
    finally:
        _building.discard(client_id)


async def ensure_catalog(client_id):
    """Meresekhez / bemelegiteshez: szinkron epites."""
    hit = _cache.get(client_id)
    if not hit or (time.monotonic() - hit[0]) >= _TTL:
        await _build_guarded(client_id)
    return (_cache.get(client_id) or (0, []))[1]


def _catalog_nowait(client_id):
    """A cache-elt katalogus (ha van); lejart/hianyzo -> hatter-epites, addig a regi / None."""
    hit = _cache.get(client_id)
    if not hit or (time.monotonic() - hit[0]) >= _TTL:
        if client_id not in _building:
            try:
                asyncio.get_running_loop().create_task(_build_guarded(client_id))
            except RuntimeError:
                pass
    return hit[1] if hit else None


async def _fetch_points(ids):
    from app.core.qdrant import get_qdrant
    q = get_qdrant()
    r = await q._client.post(f"/collections/{q.collection}/points",
                             json={"ids": list(ids), "with_payload": True, "with_vector": False})
    r.raise_for_status()
    return r.json().get("result", []) or []


def _skip(message):
    try:  # d10d FP-sweep: bolti tema / a botnak szolo kerdes nem termek-kereses
        from app.services.linkgate import meta_topic, shop_topic
        if shop_topic(message) or meta_topic(message):
            return "bolti/meta"
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.policy_filter import is_policy_query
        if is_policy_query(message):
            return "policy"
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.superlative import detect_price_superlative
        if detect_price_superlative(message):
            return "szuperlativusz"
    except Exception:  # noqa: BLE001
        pass
    return ""


async def augment(hits, message, client_id, hide_oos=False, wait=False, stats=None):
    """A pool kiegeszitese (max _MAX_ADD termek a VEGERE). Hiba / nem kell -> a hits valtozatlan."""
    hits = list(hits or [])
    if not (message or "").strip():
        return hits
    why = _skip(message)
    if why:
        if stats is not None:
            stats["skip"] = why
        return hits
    ents = await ensure_catalog(client_id) if wait else _catalog_nowait(client_id)
    if not ents:
        return hits
    pool_names, have = [], set()
    for h in hits:
        if not isinstance(h, dict):
            continue
        have.add(str(h.get("id")))
        pl = h.get("payload") or {}
        if str(pl.get("type") or "") == "product":
            pool_names.append(pl.get("name") or "")
    sku_ids, name_ids, info = pick(ents, message, pool_names, hide_oos=hide_oos, exclude_ids=have)
    if stats is not None:
        stats.update(info)
        stats["sku"] = len(sku_ids)
        stats["nev"] = len(name_ids)
    ids = sku_ids + name_ids
    if not ids:
        return hits
    pts = await _fetch_points(ids)
    byid = {str(p.get("id")): p for p in pts}
    low = min((float(h.get("score") or 0.0) for h in hits if isinstance(h, dict)), default=0.0)
    for i in ids:
        p = byid.get(str(i))
        if not p or str((p.get("payload") or {}).get("type") or "") != "product":
            continue
        hits.append({"id": p.get("id"), "version": 0, "score": low, "payload": p.get("payload") or {}, "m103": True})
    logger.info("m103 lexmatch: sku=%d nev=%d pool=%s best=%s tier=%s client=%s",
                len(sku_ids), len(name_ids), info.get("pool"), info.get("best"), info.get("tier"), client_id)
    return hits


# --- m104: a latogato altal megadott cikkszam lathatova tetele a promptban ------------
# d11a lelet: a sku a payloadban van, de a text-ben (amit a prompt # TUDASBAZIS-a mutat)
# tobbnyire nincs (kellegyszerszam 14/300, fishingoutlet 1/300, nagyonallatshop, teslashop,
# smartzilla 0/300) -> a m103 cikkszam-aga betette a YT-82992 termeket a kontextusba, a
# modell megis "nem talalom"-ot mondott, mert a kodot sehol nem latta. Csak a KERDES
# kodjaval egyezo termeket jeloljuk (a pick() sku-aganak szabalyaval), es a latogato sajat
# kodjat mutatjuk: a belso, szallito-elotagos sku (pl. "tolnagro-143167") nem kerul ki.

def _codes(message):
    """[(normalizalt, ahogy a latogato irta), ...] a sku_tokens() feltetelei szerint."""
    want = sku_tokens(message)
    out, seen = [], set()
    for raw in _SKU_RAW.findall(str(message or "")):
        n = norm_sku(raw)
        if n in want and n not in seen:
            seen.add(n)
            out.append((n, raw.strip()))
    return out


def sku_match(sku_raw, message):
    """-> a megjelenitendo kod, ha a termek sku-ja egyezik a kerdes egy kodszeru tokenjevel
    (pontos egyezes: a katalogus-alak; betus tokennel vegzodes-egyezes, pl. szallito-elotag:
    a latogato sajat alakja); kulonben ''."""
    s = norm_sku(sku_raw)
    if not s:
        return ""
    for n, raw in _codes(message):
        if s == n:
            return str(sku_raw).strip()
        if len(n) >= 6 and not n.isdigit() and s.endswith(n):
            return raw
    return ""


def mark_sku(hits, message, current=None):
    """m104: a kerdes kodjaval egyezo termek-talalatok jelolese (hit["m104_sku"]) es az
    aktualis termeke (current.m104_sku). A szoveget a prompt rajzolja. -> jeloltek szama."""
    if not _codes(message):
        return 0
    n = 0
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        pl = h.get("payload") or {}
        if str(pl.get("type") or "") != "product":
            continue
        code = sku_match(pl.get("sku"), message)
        if code:
            h["m104_sku"] = code
            n += 1
    if current is not None:
        code = sku_match(getattr(current, "sku", ""), message)
        if code:
            setattr(current, "m104_sku", code)
            n += 1
    return n

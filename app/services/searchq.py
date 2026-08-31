"""CX SmartSearch — szerver-oldali kereses a Qdrant-profilon (ssq/2, 2026-08-31).

A `GET /search/q` vegpont magja (app/api/search.py csak a HTTP-reteg). Az index az
app/search/qdrantout.py altal epitett tenantonkenti kollekcio (alias cx_search_<tenant>),
a prefix-kiegeszites szotara a /cxsearch/<tenant>-q/vocab.json (manifest.json mellette).

A kliens-oldali widget (MiniSearch) viselkedesenek szerver-oldali parja - ugyanaz a
tokenizalas (app/search/qtext.py), ugyanazok a szinonima-, intent- es merch-szabalyok:

  szures  : Qdrant full-text PREFIX index az `ft` mezon -> minden token prefixkent (MatchText),
            logikai tokenenkent szinonima-alternativak (should), ES-kapcsolat (must);
            ures talalatnal a widget kaszkadja: AND -> (n-1 token, min_should) -> OR
  rangsor : ritka `lex` vektor (idf-modifier) - a query-termek 1.0, a szotar-prefix-
            kiegesziteseik 0.375 sullyal (MiniSearch prefix-suly); utana a jeloltek
            keszlet-boostja (a=1 -> score*(1+stock_boost)), intent-particio es merch-vodrok
  facetek : Qdrant facet API (b, c, px) + 7 fix ar-sav count - mindegyik a SAJAT szurojet
            kihagyva szamol (a widget rpFilter(base, except) parja)
  rendezes: rel (fent) | pa/pd (scroll order_by p) | nm (nev, Python-oldalon, plafon)

TUDATOS ELTERESEK a widgettol (v1): nincs elgepeles-tures (MiniSearch fuzzy 0.15);
a merch/intent atrendezes csak a lekert top-CAND_MAX jeloltre hat, nem a teljes listara.

A Qdrant-hivasok egy `client` objektumon (httpx.AsyncClient-alaku: .post(path, json=...))
mennek at -> fake klienssel tesztelheto; a tenant-szotar cache-elt (TTL + manifest mtime).
"""
import asyncio
import bisect
import json
import logging
import math
import os
import time
from datetime import date

try:
    from app.search import qtext
except Exception:  # file-load teszt / fake `app` -> relativ betoltes
    import importlib.util as _ilu
    _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "search", "qtext.py")
    _s = _ilu.spec_from_file_location("searchq_dep_qtext", _p)
    qtext = _ilu.module_from_spec(_s)
    _s.loader.exec_module(qtext)

logger = logging.getLogger("cx.searchq")

ROOT = os.environ.get("CXSEARCH_ROOT", "/cxsearch")
SUFFIX = "-q"
ALIAS_PREFIX = "cx_search_"
VECTOR = "lex"
TENANT_TTL = 60.0
PREFIX_MAX = 40        # prefix-kiegeszites plafon tokenenkent (df szerint csokkeno)
PREFIX_W = 0.375       # MiniSearch alapertelmezett prefix-suly
CAND_MAX = 500         # relevancia-rangsorolt jeloltek plafonja (lapozas ezen belul)
SORT_MAX = 1000        # ar/nev rendezes plafonja
FACET_LIMIT = 30       # ertekek csoportonkent a valaszban
FACET_MAX_GROUPS = 8   # parameter-csoportok plafonja (widget RP_MAX_FACETS)
FACET_COV = 0.2        # lefedettseg-kuszob (widget RP_COV)
FACET_MIN = 5          # ... de legalabb ennyi termek (widget need = max(5, ceil(n*0.2)))
FACET_API_LIMIT = 2000
STOCK_BOOST = 0.15
PRICE_BUCKETS = [("0", 0, 20000), ("1", 20000, 50000), ("2", 50000, 100000),
                 ("3", 100000, 200000), ("4", 200000, 300000), ("5", 300000, 500000),
                 ("6", 500000, None)]

# smartsearch.js SYN_GROUPS / ACC_WORDS / MODEL_WORDS / MACHINE_CATS - szo szerint
SYN_GROUPS = [["laptop", "notebook"], ["eger", "mouse"], ["billentyuzet", "keyboard"],
              ["fulhallgato", "fejhallgato", "headset"], ["monitor", "kijelzo"],
              ["nyomtato", "printer"], ["patron", "tintapatron"], ["gamer", "gaming"],
              ["szamitogep", "pc"], ["merevlemez", "hdd", "winchester"], ["tv", "televizio"]]
ACC_WORDS = set("taska hatizsak tok huzat sleeve eger mouse egerpad billentyuzet keyboard "
                "dokkolo allvany kabel adapter tolto patron tintapatron toner tinta fulhallgato "
                "fejhallgato headset webkamera hangszoro pendrive memoriakartya folia zsanor".split())
MODEL_WORDS = set("legion thinkpad ideapad thinkbook yoga loq pavilion victus omen elitebook "
                  "probook vivobook zenbook tuf rog aspire nitro predator swift macbook latitude "
                  "inspiron vostro xps katana prestige travelmate extensa laptop notebook "
                  "szamitogep pc".split())
MACHINE_CATS = {"uj notebook", "asztali szamitogep", "all in one", "felujitott-hasznalt pc",
                "grafikus munkaallomas"}
MERCH_RANK = {"front": 1, "up": 2, "down": 4, "back": 5}


class SearchUnavailable(Exception):
    """Nincs kereso-profil a tenanthoz (manifest/vocab hianyzik vagy hibas)."""


# --------------------------------------------------------------------------- #
# tenant-szotar (manifest + vocab) - cache
# --------------------------------------------------------------------------- #
class TenantIndex:
    __slots__ = ("cid", "manifest", "terms", "dfs", "loaded", "mtime")

    def __init__(self, cid, manifest, terms, dfs, mtime):
        self.cid, self.manifest, self.terms, self.dfs = cid, manifest, terms, dfs
        self.mtime, self.loaded = mtime, time.time()

    @property
    def alias(self):
        return self.manifest.get("alias") or (ALIAS_PREFIX + self.cid)

    def expand(self, tok, cap=PREFIX_MAX):
        """A szotar tok-kal kezdodo termjei (a pontos egyezes nelkul), df szerint csokkeno."""
        if not self.terms or not tok:
            return []
        i = bisect.bisect_left(self.terms, tok)
        out = []
        while i < len(self.terms) and self.terms[i].startswith(tok):
            if self.terms[i] != tok:
                out.append((self.dfs[i], self.terms[i]))
            i += 1
        out.sort(reverse=True)
        return [t for _, t in out[:cap]]


_cache: dict = {}


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_tenant(cid, root=None, now=None):
    """Manifest + vocab a webrootrol (TTL-cache, manifest-mtime valtozasra ujratolt).
    Hianyzo/hibas profil -> SearchUnavailable."""
    root = root or ROOT
    now = now or time.time()
    d = os.path.join(root, cid + SUFFIX)
    mp = os.path.join(d, "manifest.json")
    hit = _cache.get(cid)
    if hit and now - hit.loaded < TENANT_TTL:
        return hit
    try:
        mtime = os.stat(mp).st_mtime
    except OSError:
        _cache.pop(cid, None)
        raise SearchUnavailable("nincs kereso-profil: " + cid)
    if hit and hit.mtime == mtime:
        hit.loaded = now
        return hit
    try:
        man = _read_json(mp)
        if not isinstance(man, dict) or man.get("error") and not man.get("collection"):
            raise SearchUnavailable("kereso-profil hibas: " + str(man.get("error")))
        voc = _read_json(os.path.join(d, "vocab.json"))
        pairs = voc.get("terms") or []
        terms = [str(p[0]) for p in pairs]
        dfs = [int(p[1]) for p in pairs]
    except SearchUnavailable:
        raise
    except Exception as e:  # noqa: BLE001
        raise SearchUnavailable(f"kereso-profil nem olvashato ({cid}): {e}")
    tix = TenantIndex(cid, man, terms, dfs, mtime)
    _cache[cid] = tix
    return tix


# --------------------------------------------------------------------------- #
# tenant-beallitasok (search_config) - a widget loadSyn()-jenek parja
# --------------------------------------------------------------------------- #
def _word(w):
    return qtext.compact_sku(str(w or ""))


def synonyms(cfg):
    """{token: csoport} - beepitett csoportok + a tenant sajat csoportjai (foldolva)."""
    groups = [list(g) for g in SYN_GROUPS]
    raw = cfg.get("synonyms") if isinstance(cfg, dict) else None
    for g in (raw or [])[:100]:
        if not isinstance(g, list):
            continue
        cg = []
        for w in g[:8]:
            fw = _word(w)
            if len(fw) > 1 and fw not in cg:
                cg.append(fw)
        if len(cg) > 1:
            groups.append(cg)
    out = {}
    for g in groups:
        for w in g:
            out[w] = g
    return out


def oneway(cfg):
    out = {}
    raw = cfg.get("oneway") if isinstance(cfg, dict) else None
    for row in (raw or [])[:100]:
        if not isinstance(row, dict):
            continue
        fk = _word(row.get("f"))
        if len(fk) < 2:
            continue
        tos = []
        for t in (row.get("t") or [])[:8]:
            tw = _word(t)
            if len(tw) > 1 and tw != fk and tw not in tos:
                tos.append(tw)
        if tos:
            out[fk] = tos
    return out


def merch_rules(cfg, today=None):
    """Aktiv merch-szabalyok: {kw: [foldolt kulcsszo], skus: [tomoritett cikkszam], w}."""
    out = []
    raw = cfg.get("merch") if isinstance(cfg, dict) else None
    day = (today or date.today()).isoformat()
    for rule in (raw or [])[:100]:
        if not isinstance(rule, dict):
            continue
        w = str(rule.get("w") or "").strip()
        skus = [qtext.compact_sku(s) for s in (rule.get("skus") or [])[:50]]
        skus = [s for s in skus if s]
        if w not in MERCH_RANK or not skus:
            continue
        frm = str(rule.get("from") or "").strip()
        to = str(rule.get("to") or "").strip()
        if (frm and day < frm) or (to and day > to):
            continue
        kws = [" ".join(qtext.fold(k).split()) for k in (rule.get("kw") or [])[:20]]
        out.append({"kw": [k for k in kws if k], "skus": skus, "w": w})
    return out


def stock_boost(cfg):
    try:
        v = (cfg.get("server") or {}).get("stock_boost") if isinstance(cfg, dict) else None
        return STOCK_BOOST if v is None else max(0.0, min(2.0, float(v)))
    except (TypeError, ValueError):
        return STOCK_BOOST


# --------------------------------------------------------------------------- #
# lekerdezes-epites
# --------------------------------------------------------------------------- #
def logical_groups(toks, syn, ow):
    """Tokenenkent az alternativak listaja (szinonima-csoport / egyiranyu kiterjesztes)."""
    out = []
    for t in toks:
        g = syn.get(t)
        if g:
            out.append(list(g))
            continue
        o = ow.get(t)
        if o:
            out.append([t] + list(o))
            continue
        out.append([t])
    return out


def _match_text(term):
    return {"key": "ft", "match": {"text": term}}


def text_conditions(groups):
    conds = []
    for alts in groups:
        if len(alts) == 1:
            conds.append(_match_text(alts[0]))
        else:
            conds.append({"should": [_match_text(a) for a in alts]})
    return conds


def build_filter(base, groups, mode):
    """mode: and | near (n-1) | or  ->  Qdrant filter."""
    conds = text_conditions(groups)
    f = {"must": list(base)}
    if not conds:
        return f
    if mode == "and":
        f["must"].extend(conds)
    else:
        k = max(1, len(conds) - 1) if mode == "near" else 1
        f["min_should"] = {"conditions": conds, "min_count": k}
    return f


def price_bucket_condition(bid):
    for b, lo, hi in PRICE_BUCKETS:
        if b == bid:
            rng = {"gte": lo}
            if hi is not None:
                rng["lt"] = hi
            return {"key": "p", "range": rng}
    return None


def base_conditions(fb=(), fc=(), fpr="", fpx=(), avail=False):
    """A facet-szurok feltetelei csoportonkent: {csoport-kulcs: feltetel}. Az 'except'
    mechanikahoz (facet-szamolas a sajat szuro nelkul) a kulcs: b | c | pr | px:<nev>."""
    out = {}
    b = [str(x) for x in fb if str(x)]
    if b:
        out["b"] = {"key": "b", "match": {"any": b}}
    c = [str(x) for x in fc if str(x)]
    if c:
        out["c"] = {"key": "c", "match": {"any": c}}
    prs = [price_bucket_condition(x.strip()) for x in str(fpr or "").split(",") if x.strip()]
    prs = [p for p in prs if p]
    if prs:
        out["pr"] = prs[0] if len(prs) == 1 else {"should": prs}
    px = {}
    for tag in fpx:
        tag = str(tag)
        if "=" not in tag:
            continue
        name = tag.split("=", 1)[0]
        px.setdefault(name, []).append(tag)
    for name, tags in px.items():
        out["px:" + name] = {"key": "px", "match": {"any": tags}}
    if avail:
        out["a"] = {"key": "a", "match": {"value": True}}
    return out


def conds_except(base, skip=None):
    return [v for k, v in base.items() if k != skip]


def sparse_query(groups, tix):
    """Query-vektor: minden alternativa 1.0, a szotar-prefix-kiegesziteseik PREFIX_W."""
    acc = {}
    for alts in groups:
        for a in alts:
            acc[a] = max(acc.get(a, 0.0), 1.0)
            if len(a) >= 2:
                for t in tix.expand(a):
                    acc[t] = max(acc.get(t, 0.0), PREFIX_W)
    vec = {}
    for t, w in acc.items():
        i = qtext.term_id(t)
        vec[i] = vec.get(i, 0.0) + w
    keys = sorted(vec)
    return {"indices": keys, "values": [round(vec[k], 4) for k in keys]}


# --------------------------------------------------------------------------- #
# utorendezes (widget-paritas): keszlet-boost, intent-particio, merch-vodrok
# --------------------------------------------------------------------------- #
def calc_intent(toks):
    acc = any(t in ACC_WORDS for t in toks)
    mod = any(t in MODEL_WORDS for t in toks)
    return 1 if acc else (2 if mod else 0)


def rerank(hits, toks, q, merch, boost):
    """hits: [(score, payload)] relevancia-sorrendben -> payload lista."""
    scored = []
    for s, pl in hits:
        sc = float(s or 0.0)
        if boost and pl.get("a"):
            sc *= 1.0 + boost
        scored.append((sc, pl))
    scored.sort(key=lambda x: -x[0])
    rows = [pl for _, pl in scored]
    intent = calc_intent(toks)
    if intent:
        a, b = [], []
        for pl in rows:
            mc = qtext.fold(pl.get("c") or "") in MACHINE_CATS
            if (intent == 2) == mc:
                a.append(pl)
            else:
                b.append(pl)
        rows = a + b
    if merch:
        fq = qtext.fold(q)
        rank = {}
        for m in merch:
            act = not m["kw"] or any(k in fq for k in m["kw"])
            if not act:
                continue
            rv = MERCH_RANK[m["w"]]
            for s in m["skus"]:
                rank.setdefault(s, rv)
        if rank:
            buckets = [[], [], [], [], []]
            for pl in rows:
                r = rank.get(pl.get("ks") or "", 3)
                buckets[r - 1].append(pl)
            rows = [pl for b in buckets for pl in b]
    return rows


def shape(pl):
    """Qdrant payload -> a widget kompakt rekordja (i,k,n,b,c,p[,o],a,u,m,d)."""
    row = {"i": pl.get("i", ""), "k": pl.get("k", ""), "n": pl.get("n", ""),
           "b": pl.get("b", ""), "c": pl.get("c", ""), "p": pl.get("p"),
           "a": 1 if pl.get("a") else 0, "u": pl.get("u", ""), "m": pl.get("m", ""),
           "d": pl.get("d", 0)}
    if pl.get("o") is not None:
        row["o"] = pl["o"]
    return row


# --------------------------------------------------------------------------- #
# Qdrant-hivasok
# --------------------------------------------------------------------------- #
async def _post(client, path, body):
    r = await client.post(path, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"qdrant {path} -> {r.status_code}: {str(getattr(r, 'text', ''))[:200]}")
    return r.json()


async def q_count(client, alias, flt):
    res = await _post(client, f"/collections/{alias}/points/count", {"exact": True, "filter": flt})
    return int((res.get("result") or {}).get("count") or 0)


async def q_query(client, alias, vec, flt, limit):
    body = {"query": vec, "using": VECTOR, "filter": flt, "limit": limit,
            "with_payload": True, "with_vector": False}
    res = await _post(client, f"/collections/{alias}/points/query", body)
    pts = (res.get("result") or {}).get("points") or []
    return [(p.get("score"), p.get("payload") or {}) for p in pts]


async def q_scroll(client, alias, flt, limit, order_by=None):
    body = {"filter": flt, "limit": limit, "with_payload": True, "with_vector": False}
    if order_by:
        body["order_by"] = order_by
    res = await _post(client, f"/collections/{alias}/points/scroll", body)
    return [p.get("payload") or {} for p in (res.get("result") or {}).get("points") or []]


async def q_facet(client, alias, key, flt, limit):
    res = await _post(client, f"/collections/{alias}/facet",
                      {"key": key, "filter": flt, "limit": limit, "exact": True})
    return [(str(h.get("value")), int(h.get("count") or 0))
            for h in (res.get("result") or {}).get("hits") or []]


# --------------------------------------------------------------------------- #
# facetek
# --------------------------------------------------------------------------- #
def _entries(pairs, cap=FACET_LIMIT):
    return [[v, n] for v, n in sorted(pairs, key=lambda x: (-x[1], x[0]))[:cap]]


async def facets(client, alias, base, text_f, total):
    """b / c / pr / px facetek - mindegyik a sajat szurojet kihagyva (widget rpFilter parja).
    text_f: a szoveg-feltetelek (must + esetleg min_should) a keresesbol."""

    def flt(skip=None):
        f = {"must": conds_except(base, skip) + list(text_f.get("must") or [])}
        if text_f.get("min_should"):
            f["min_should"] = text_f["min_should"]
        return f

    jobs = {
        "b": q_facet(client, alias, "b", flt("b"), 300),
        "c": q_facet(client, alias, "c", flt("c"), 300),
        "px": q_facet(client, alias, "px", flt(), FACET_API_LIMIT),
    }
    for bid, lo, hi in PRICE_BUCKETS:
        f = flt("pr")
        f["must"].append(price_bucket_condition(bid))
        jobs["pr:" + bid] = q_count(client, alias, f)
    active_px = [k[3:] for k in base if k.startswith("px:")]
    for name in active_px:
        jobs["pxa:" + name] = q_facet(client, alias, "px", flt("px:" + name), FACET_API_LIMIT)
    keys = list(jobs)
    vals = await asyncio.gather(*[jobs[k] for k in keys], return_exceptions=True)
    got = {}
    for k, v in zip(keys, vals):
        if isinstance(v, Exception):
            logger.warning("searchq facet hiba (%s): %r", k, v)
            v = [] if not k.startswith("pr:") else 0
        got[k] = v

    out = {"b": _entries(got["b"]), "c": _entries(got["c"]),
           "pr": {bid: int(got.get("pr:" + bid) or 0) for bid, _, _ in PRICE_BUCKETS}, "px": {}}
    # parameter-csoportok: lefedettseg + >=2 ertek, aktiv csoportok mindig
    by_name = {}
    for tag, n in got["px"]:
        if "=" not in tag:
            continue
        name, val = tag.split("=", 1)
        by_name.setdefault(name, []).append((val, n))
    for name in active_px:   # az aktiv csoport szamai a SAJAT szuroje nelkul
        pairs = [(t.split("=", 1)[1], n) for t, n in got.get("pxa:" + name) or [] if t.startswith(name + "=")]
        by_name[name] = pairs
    need = max(FACET_MIN, math.ceil(max(total, 0) * FACET_COV))
    cand = []
    for name, pairs in by_name.items():
        cov = sum(n for _, n in pairs)
        if name in active_px or (cov >= need and len(pairs) >= 2):
            cand.append((0 if name in active_px else 1, -cov, name))
    cand.sort()
    for _, _, name in cand[:FACET_MAX_GROUPS]:
        out["px"][name] = _entries(by_name[name])
    return out


# --------------------------------------------------------------------------- #
# fo belepesi pont
# --------------------------------------------------------------------------- #
async def search(client, cfg, cid, q, limit=8, offset=0, sort="rel", want_facets=False,
                 fb=(), fc=(), fpr="", fpx=(), avail=False, root=None, today=None):
    """Kereses a tenant Qdrant-profiljan. Kivetel: SearchUnavailable (nincs profil),
    RuntimeError (Qdrant-hiba). Visszatero dict JSON-ba irhato."""
    t0 = time.time()
    tix = load_tenant(cid, root=root)
    alias = tix.alias
    q = " ".join(str(q or "").split())[:200]
    toks = qtext.tokens(q)
    syn, ow = synonyms(cfg), oneway(cfg)
    groups = logical_groups(toks, syn, ow)
    base = base_conditions(fb, fc, fpr, fpx, avail)
    limit = max(1, min(int(limit or 8), 100))
    offset = max(0, min(int(offset or 0), 5000))
    sort = sort if sort in ("rel", "pa", "pd", "nm") else "rel"

    # 1) szures-kaszkad a widget szerint: AND -> n-1 -> OR
    mode, flt, total = "none", build_filter(conds_except(base), [], "and"), 0
    if groups:
        n = len(groups)
        cascade = [("and", "and")]
        if n >= 2:
            cascade.append(("near", "and"))
        if n >= 3:
            cascade.append(("or", "or"))
        for fm, label in cascade:
            flt = build_filter(conds_except(base), groups, fm)
            total = await q_count(client, alias, flt)
            mode = label
            if total:
                break
    else:
        total = await q_count(client, alias, flt)

    # 2) talalatok
    rows = []
    if total and offset < total:
        if sort == "rel" and groups:
            k = min(offset + limit, CAND_MAX)
            hits = await q_query(client, alias, sparse_query(groups, tix), flt, k)
            rows = rerank(hits, toks, q, merch_rules(cfg, today), stock_boost(cfg))[offset:offset + limit]
        elif sort in ("pa", "pd"):
            k = min(offset + limit, SORT_MAX)
            rows = (await q_scroll(client, alias, flt, k,
                                   order_by={"key": "p", "direction": "asc" if sort == "pa" else "desc"}))[offset:offset + limit]
        elif sort == "nm":
            rows = await q_scroll(client, alias, flt, SORT_MAX)
            rows.sort(key=lambda pl: qtext.fold(pl.get("n") or ""))
            rows = rows[offset:offset + limit]
        else:   # ures lekerdezes, relevancia: index-sorrend (a widget state.all parja)
            rows = (await q_scroll(client, alias, flt, min(offset + limit, SORT_MAX)))[offset:offset + limit]

    out = {"tenant": cid, "q": q, "total": total, "mode": mode, "sort": sort,
           "offset": offset, "limit": limit, "hits": [shape(pl) for pl in rows],
           "url_prefix": tix.manifest.get("url_prefix") or "",
           "img_prefix": tix.manifest.get("img_prefix") or "",
           "v": tix.manifest.get("v") or "", "count": tix.manifest.get("count") or 0}
    if want_facets:
        text_f = {"must": [c for c in flt.get("must", []) if c not in conds_except(base)]}
        if flt.get("min_should"):
            text_f["min_should"] = flt["min_should"]
        out["facets"] = await facets(client, alias, base, text_f, total)
    out["ms"] = int((time.time() - t0) * 1000)
    return out

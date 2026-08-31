"""CX SmartSearch — Qdrant kimeneti profil (ssq/1, 2026-08-31).

Az indexcore HARMADIK kimenete (ADR-001 "egy kodbazis, tobb kimeneti profil"): ugyanabbol a
lekert `products` listabol - plusz API-hivas nelkul - Qdrant-kollekciot epit a SZERVER-OLDALI
keresonek (`GET /search/q`, app/services/searchq.py).

Miert kulon kollekcio, es miert nem a chat `cx_chatbot_v2` (merve 2026-08-31):
  - a chat-sync a Shoprenter-tenantoknal csak a keszleten levo termeket viszi (copygo 22 207
    pont, MIND available=true) - a keresonek viszont a 0 keszletu is kell (`a` valodi 0/1);
  - a chat-payloadban nincs kep, kategoria, parameter, akcios ar; csak dense vektor van, ami
    cikkszamra es prefix-gepelesre alkalmatlan.

Kollekcio: tenantonkent EGY, alias mogott:  cx_search_<tenant>  ->  cx_search_<tenant>_<ts>.
A build UJ kollekcioba ir, a min_ratio-kapu es a darabszam-ellenorzes utan az aliast
ATVALTJA (egy atomi alias-muvelet), majd a regi kollekciot torli. A kereso igy sosem lat
felig kesz indexet - ez a statikus index atomikus irasanak parja.

Pont:  id = uuid5(tenant:i)
       payload = a kompakt index-rekord (i,k,n,b,c,p,o,a,u,m,d; `a` bool, `p`/`o` float) +
         px = ["nev=ertek", ...]   parameter-cimkek (facet + szuro; keyword-index)
         ft = ekezet-foldolt kereso-szoveg (nev, cikkszam, marka, kategoria) - full-text
              PREFIX index -> a MatchText "minden szo prefixkent" ES-szures
         ks = tomoritett cikkszam ([0-9a-z]) - pontos cikkszam-egyezes / merch
       ritka vektor `lex` (idf-modifier): a foldolt tokenek mezo-sullyal (n 3, k 5, b 1.5,
       c 1 - a widget MiniSearch-boostjainak parja). A prefix-kiegeszitest a kereso a
       vocab.json-bol vegzi (MiniSearch-mintara), az index csak egesz tokeneket tartalmaz.

Kimenet a webrootba, <out>/<tenant>-q/:  manifest.json + vocab.json ([term, df] rendezve).
Ezeket a kereso-API a /cxsearch mountrol olvassa. Hiba eseten error-manifest, a fo index
(index.json) es a konf-kimenet erintetlen - a hivo (app/search/__main__.py) is try-eli.

A Qdrant-hivasok EGY ponton mennek at (QdrantHTTP.request), igy fake klienssel tesztelheto.
"""
import hashlib
import json
import os
import re
import time
import uuid

try:
    from app.search import indexcore, qtext
except Exception:  # file-load teszt / fake `app` a sys.modules-ben -> relativ betoltes
    import importlib.util as _ilu

    def _load(_name):
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), _name + ".py")
        _s = _ilu.spec_from_file_location("qdrantout_dep_" + _name, _p)
        _m = _ilu.module_from_spec(_s)
        _s.loader.exec_module(_m)
        return _m

    indexcore = _load("indexcore")
    qtext = _load("qtext")

SUFFIX = "-q"
ALIAS_PREFIX = "cx_search_"
VECTOR = "lex"
BATCH = 200
FIELD_BOOST = {"n": 3.0, "k": 5.0, "b": 1.5, "c": 1.0}
NS = uuid.UUID("7b8c2f4e-3a1d-4c5b-9e6f-1a2b3c4d5e6f")
FT_SCHEMA = {"type": "text", "tokenizer": "prefix", "min_token_len": 1,
             "max_token_len": 30, "lowercase": True}
PAYLOAD_INDEXES = {
    "b": "keyword", "c": "keyword", "px": "keyword", "ks": "keyword",
    "a": "bool", "p": "float", "d": "integer", "ft": FT_SCHEMA,
}
_TS_RE = re.compile(r"_(\d{14})$")


# --------------------------------------------------------------------------- #
# pont-epites (tiszta fuggvenyek)
# --------------------------------------------------------------------------- #
def point_id(tenant, i):
    return str(uuid.uuid5(NS, f"{tenant}:{i}"))


def _num(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def doc_terms(row):
    """{term: suly} - a mezo-boostok OSSZEGE azokon a mezokon, ahol a term elofordul
    (mezonkent egyszer; a MiniSearch mezonkent szamol, mi a rovid termeknev miatt a
    tf-et elhagyjuk). + a tomoritett cikkszam a cikkszam sulyaval."""
    w = {}
    for f, boost in FIELD_BOOST.items():
        for t in set(qtext.words(row.get(f) or "")):
            w[t] = w.get(t, 0.0) + boost
    ks = qtext.compact_sku(row.get("k"))
    if ks and ks not in w:
        w[ks] = FIELD_BOOST["k"]
    return w


def sparse_vector(terms):
    """{term: suly} -> {"indices": [...], "values": [...]} (egyedi, rendezett indexek;
    crc32-utkozesnel a sulyok osszeadodnak)."""
    acc = {}
    for t, v in terms.items():
        idx = qtext.term_id(t)
        acc[idx] = acc.get(idx, 0.0) + float(v)
    keys = sorted(acc)
    return {"indices": keys, "values": [round(acc[k], 4) for k in keys]}


def make_point(tenant, row, px):
    """Kompakt sor + parameter-cimkek -> Qdrant pont. Visszaadja a termeket is (vocab/df)."""
    terms = doc_terms(row)
    payload = {"i": str(row.get("i", "")), "k": row.get("k") or "", "n": row.get("n") or "",
               "b": row.get("b") or "", "c": row.get("c") or "", "u": row.get("u") or "",
               "m": row.get("m") or "", "a": bool(row.get("a"))}
    p = _num(row.get("p"))
    if p is not None:
        payload["p"] = p
    o = _num(row.get("o"))
    if o is not None:
        payload["o"] = o
    if row.get("d") is not None:
        payload["d"] = int(row["d"])
    if px:
        payload["px"] = list(px)
    ks = qtext.compact_sku(row.get("k"))
    if ks:
        payload["ks"] = ks
    payload["ft"] = " ".join(terms.keys())
    return {"id": point_id(tenant, payload["i"]), "payload": payload,
            "vector": {VECTOR: sparse_vector(terms)}}, terms


def param_tags(p):
    out, seen = [], set()
    for name, v in indexcore.param_pairs(p):
        tag = f"{name}={v}"
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


# --------------------------------------------------------------------------- #
# Qdrant HTTP (egy pont, injektalhato klienssel)
# --------------------------------------------------------------------------- #
class QdrantHTTP:
    def __init__(self, url=None, client=None):
        if client is None:
            import httpx
            client = httpx.Client(base_url=(url or "").rstrip("/"), timeout=180)
        self.c = client

    def request(self, method, path, body=None):
        r = self.c.request(method, path, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"qdrant {method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def collections(self):
        res = self.request("GET", "/collections")
        return [c["name"] for c in (res.get("result") or {}).get("collections") or []]

    def aliases(self):
        # FIGYELEM: az osszes alias listaja a GYOKER /aliases vegponton van; a
        # /collections/aliases GET-je a Qdrantnak egy "aliases" NEVU kollekciot jelent
        # (404). Az alias-MUVELET (POST /collections/aliases) viszont helyes.
        res = self.request("GET", "/aliases")
        return {a["alias_name"]: a["collection_name"]
                for a in (res.get("result") or {}).get("aliases") or []}

    def create(self, name):
        self.request("PUT", f"/collections/{name}",
                     {"vectors": {}, "sparse_vectors": {VECTOR: {"modifier": "idf"}}})
        for field, schema in PAYLOAD_INDEXES.items():
            self.request("PUT", f"/collections/{name}/index?wait=true",
                         {"field_name": field, "field_schema": schema})

    def upsert(self, name, points):
        self.request("PUT", f"/collections/{name}/points?wait=true", {"points": points})

    def count(self, name):
        res = self.request("POST", f"/collections/{name}/points/count", {"exact": True})
        return int((res.get("result") or {}).get("count") or 0)

    def switch_alias(self, alias, name, had_alias):
        actions = []
        if had_alias:
            actions.append({"delete_alias": {"alias_name": alias}})
        actions.append({"create_alias": {"collection_name": name, "alias_name": alias}})
        self.request("POST", "/collections/aliases", {"actions": actions})

    def delete(self, name):
        self.request("DELETE", f"/collections/{name}")


def alias_name(tenant):
    return ALIAS_PREFIX + tenant


def _stale_collections(names, tenant, keep):
    pre = alias_name(tenant) + "_"
    return [n for n in names if n.startswith(pre) and _TS_RE.search(n) and n != keep]


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def build(tenant, products, out_root, url_prefix, img_prefix, only_available=False,
          min_ratio=0.5, scope=None, qdrant_url=None, client=None, batch=BATCH):
    """Feed-alaku termeklista -> Qdrant-kollekcio (alias mogott) + manifest/vocab a webrootba.

    Eredmeny-dict a CLI-nek; hibanal error-manifest + {"error": ...}, kivetelt NEM dob."""
    t0 = time.time()
    out_dir = os.path.join(out_root, tenant + SUFFIX)
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.json")

    if only_available:
        products = [p for p in products if p.get("available")]
    rows = [indexcore.compact(p, url_prefix, img_prefix) for p in products]
    if scope:
        pairs = [(p, r) for p, r in zip(products, rows)
                 if indexcore.scope_match(r, indexcore._param_map(p), scope)]
        products = [p for p, _ in pairs]
        rows = [r for _, r in pairs]
    if not rows:
        err = "0 termek a kereso-profilban, kollekcio nem frissult"
        indexcore.write_error_manifest(out_dir, tenant, err)
        return {"tenant": tenant, "error": err}
    indexcore.apply_days(rows, [p.get("created_day") for p in products], out_dir)

    points, df, avail = [], {}, 0
    for p, r in zip(products, rows):
        pt, terms = make_point(tenant, r, param_tags(p))
        points.append(pt)
        avail += 1 if r.get("a") else 0
        for t in terms:
            df[t] = df.get(t, 0) + 1
    version = hashlib.sha256(json.dumps(
        {"products": rows}, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:12]

    alias = alias_name(tenant)
    q = client if isinstance(client, QdrantHTTP) else QdrantHTTP(qdrant_url, client)
    try:
        aliases = q.aliases()
        old = aliases.get(alias)
        prev = q.count(old) if old else 0
        if prev and len(points) < prev * min_ratio:
            err = f"gyanus zsugorodas {prev}->{len(points)}, kollekcio nem frissult"
            indexcore.write_error_manifest(out_dir, tenant, err)
            return {"tenant": tenant, "error": err, "count": prev}

        name = f"{alias}_{time.strftime('%Y%m%d%H%M%S', time.gmtime())}"
        q.create(name)
        batches = 0
        for i in range(0, len(points), batch):
            q.upsert(name, points[i:i + batch])
            batches += 1
        got = q.count(name)
        if got != len(points):
            q.delete(name)
            err = f"darabszam-elteres feltoltes utan {got} != {len(points)}, kollekcio nem frissult"
            indexcore.write_error_manifest(out_dir, tenant, err)
            return {"tenant": tenant, "error": err, "count": prev}

        q.switch_alias(alias, name, had_alias=old is not None)
        removed = []
        for stale in _stale_collections(q.collections(), tenant, keep=name):
            try:
                q.delete(stale)
                removed.append(stale)
            except Exception as e:  # noqa: BLE001 - a takaritas hibaja nem hiba
                removed.append(f"{stale}: {e}")
    except Exception as e:  # noqa: BLE001 - qdrant-hiba: a regi kollekcio marad, manifest error
        indexcore.write_error_manifest(out_dir, tenant, f"qdrant: {e}")
        return {"tenant": tenant, "error": f"qdrant: {e}"}

    vocab = {"v": version, "count": len(points),
             "terms": sorted([[t, n] for t, n in df.items()], key=lambda x: x[0])}
    indexcore.atomic_write(os.path.join(out_dir, "vocab.json"),
                           json.dumps(vocab, ensure_ascii=False, separators=(",", ":")))
    indexcore.atomic_write(manifest_path, json.dumps({
        "tenant": tenant, "v": version, "count": len(points), "avail": avail,
        "built_at": int(time.time()), "url_prefix": url_prefix, "img_prefix": img_prefix,
        "collection": name, "alias": alias, "terms": len(df),
    }, ensure_ascii=False))
    return {"tenant": tenant, "v": version, "count": len(points), "avail": avail,
            "collection": name, "alias": alias, "prev": prev, "removed": removed,
            "terms": len(df), "batches": batches, "out": out_dir, "scoped": bool(scope),
            "secs": round(time.time() - t0, 1)}

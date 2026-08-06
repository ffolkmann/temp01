"""m82h/2: tenant-szintu MARKA-TERKEP generalasa a Qdrant `brand` payloadbol.

Ir: /app/data/brand_map_<client_id>.json  (a chatbot `app/services/branddict.py`
olvassa; a szuro-ut valtozatlan, csak a SZOTAR jon innen).

Higienia-kapuk (a m82h/2 meresekbol, tools/m82h2_05_shadow.py a shadow):
  H1  STOP-lista: kategoria-szeru toltelek brand-ertekek (Egyeb, No name,
      Alkatresz, Premium, TOP, Import, Home...)
  H3  koznyelvi-kapu: ROVID kulcs (<= _SHORT_MAX) ES kereszt-tenant df >= _DF_MIN
      (hany MASIK tenant KB-szovegeben fordul elo) -> ki.
      Igy esik ki a `hu` (df=9), `elo` (df=7), `1000` (df=6), es marad a
      `Microsoft` (hosszu kulcs) es a `Gree` (df=2).
  (H2' = kerdes-oldali e-mail/URL-host tisztitas: az a branddict dolga.)

Fail-safe: tenantonkent kulon try; hiba eseten az ADOTT tenant fajlja
valtozatlan marad (a regi terkep tovabb el). 0 kulcs -> nem irunk fajlt.

Futtatas: docker exec -i chatbot-api-prod python - < tools/brand_map_crawl.py
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

QDRANT = os.environ.get("QDRANT_URL", "http://qdrant:6333").rstrip("/")
COLL = os.environ.get("QDRANT_COLLECTION", "cx_chatbot_v2")
OUT_DIR = os.environ.get("FACET_MAP_DIR", "/app/data")

_MIN_LEN = 2
_SHORT_MAX = 4
_DF_MIN = 3
_MAX_WORDS_CAP = 4
_STOP = frozenset({
    "egyeb", "egyeb marka", "other", "n/a", "na", "nincs", "ismeretlen",
    "no name", "noname", "general", "generic", "univerzalis",
    "alkatresz", "alkatreszek", "premium", "kiegeszito", "kiegeszitok",
    "akcio", "outlet", "csomag", "keszlet",
    "top", "import", "home", "profi", "standard",
})

_RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c)).strip()


def norm(s):
    return _RE_NONALNUM.sub(" ", s).strip()


def keyform(raw):
    """'MSI (Micro-Star International)' -> ['msi', 'micro star international']"""
    f = fold(raw)
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", f)
    parts = [m.group(1), m.group(2)] if m else [f]
    return [k for k in (norm(p) for p in parts) if k]


def post(path, body):
    r = urllib.request.Request(QDRANT + path, data=json.dumps(body).encode(),
                               method="POST", headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=180).read().decode())


def scroll(flt, fields, limit=500, max_pages=200):
    out = []
    offset = None
    for _ in range(max_pages):
        body = {"filter": flt, "limit": limit, "with_payload": fields, "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % COLL, body)["result"]
        out.extend(pt.get("payload") or {} for pt in res.get("points", []))
        offset = res.get("next_page_offset")
        if not offset:
            break
    return out


def tenant_list():
    """Qdrant facet API; ha nincs, teljes scroll a client_id payloadon."""
    try:
        res = post("/collections/%s/facet" % COLL,
                   {"key": "client_id", "limit": 200, "exact": True})["result"]
        vals = [h["value"] for h in res.get("hits", []) if h.get("value")]
        if vals:
            print("  tenant-lista: facet API (%d)" % len(vals))
            return sorted(vals)
    except Exception as e:  # noqa: BLE001
        print("  facet API nem elerheto (%s) -> scroll fallback" % e.__class__.__name__)
    seen = set()
    for p in scroll({}, ["client_id"], limit=1000, max_pages=500):
        c = p.get("client_id")
        if c:
            seen.add(str(c))
    print("  tenant-lista: scroll (%d)" % len(seen))
    return sorted(seen)


def main():
    t0 = time.time()
    clients = tenant_list()
    if not clients:
        print("NINCS tenant -- kilepes, fajlt nem irunk")
        return 1

    inv_all, kb_all = {}, {}
    for cid in clients:
        try:
            inv = {}
            flt = {"must": [{"key": "client_id", "match": {"value": cid}},
                            {"key": "type", "match": {"value": "product"}}]}
            for p in scroll(flt, ["brand", "available", "stock"]):
                b = str(p.get("brand") or "").strip()
                if not b:
                    continue
                av = p.get("available")
                if av is None:
                    av = p.get("stock")
                d = inv.setdefault(b, [0, 0])
                d[0] += 1
                d[1] += 1 if av else 0
            if inv:
                inv_all[cid] = inv
            kbflt = {"must": [{"key": "client_id", "match": {"value": cid}}],
                     "must_not": [{"key": "type", "match": {"value": "product"}}]}
            kb_all[cid] = fold(" ".join(str(p.get("text") or "")
                                        for p in scroll(kbflt, ["text"])))
        except Exception as e:  # noqa: BLE001 - egy tenant hibaja ne allitsa meg a tobbit
            print("  [%s] HIBA a beolvasasban: %s" % (cid, e))

    # --- kereszt-tenant df CSAK a rovid kulcsokra ---
    short = set()
    for inv in inv_all.values():
        for b in inv:
            for k in keyform(b):
                if _MIN_LEN <= len(k) <= _SHORT_MAX and k not in _STOP:
                    short.add(k)
    df = {}
    for k in short:
        rx = re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])")
        df[k] = {c for c, t in kb_all.items() if t and rx.search(t)}

    written = failed = 0
    for cid, inv in sorted(inv_all.items()):
        try:
            brands, dropped = {}, {}
            for b, (n, av) in inv.items():
                for k in keyform(b):
                    if len(k) < _MIN_LEN:
                        dropped[b] = "rovid"
                        continue
                    if k in _STOP:
                        dropped[b] = "H1 stop"
                        continue
                    own = 1 if cid in df.get(k, ()) else 0
                    d = len(df.get(k, ())) - own
                    if len(k) <= _SHORT_MAX and d >= _DF_MIN:
                        dropped[b] = "H3 df=%d" % d
                        continue
                    e = brands.setdefault(k, {"vals": [], "n": 0, "av": 0})
                    if b not in e["vals"]:
                        e["vals"].append(b)
                    e["n"] += n
                    e["av"] += av
            if not brands:
                print("  [%-16s] 0 kulcs -> fajlt NEM irunk (regi terkep marad)" % cid)
                continue
            maxw = min(_MAX_WORDS_CAP, max(len(k.split()) for k in brands))
            data = {
                "client_id": cid,
                "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "max_words": maxw,
                "dropped": dropped,
                "brands": brands,
            }
            path = os.path.join(OUT_DIR, "brand_map_%s.json" % cid)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
            written += 1
            print("  [%-16s] kulcs=%4d | kiejtve=%2d | elerheto lefedve=%6d | maxw=%d"
                  % (cid, len(brands), len(dropped),
                     sum(e["av"] for e in brands.values()), maxw))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("  [%s] HIBA az irasnal: %s" % (cid, e))

    print("KESZ: %d terkep irva, %d hiba, %.1f mp" % (written, failed, time.time() - t0))
    return 0 if written and failed == 0 else (0 if written else 1)


sys.exit(main())

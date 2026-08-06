"""m82h ADATFELVÉTEL — kivezethető-e a kézi `_BRANDS` lista a generikus szótárba?

A m82g/1 térkép-mérés két kockázatot mutatott, ez a lépés SZÁMOT ad rájuk:
  1. FEDETTSÉG: a `brand` payload minden terméken ott van, a `facets:marka:*`
     viszont csak a crawl-olt részhalmazon -> a kiváltás poolt veszíthet.
  2. `_MIN_LEN`=3: a 2 betűs márkák ("hp", "lg", "fs") a szótárból eleve kiesnek.

CSAK MÉR, nem javasol. Futtatás:
  docker exec -i chatbot-api-prod python - < tools/m82h_branddiag.py
"""
import asyncio
import json
import sys
import urllib.request

sys.path.insert(0, "/app")

CLIENT = "notebookstore"
Q = "http://qdrant:6333"
C = "cx_chatbot_v2"


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read().decode())


async def main():
    from app.services import facetdict as fd
    from app.services.linkfacet import load_map
    from app.services.paramextract import _BRANDS

    pts = []
    offset = None
    for _ in range(30):
        body = {"filter": {"must": [{"key": "client_id", "match": {"value": CLIENT}},
                                    {"key": "type", "match": {"value": "product"}}]},
                "limit": 1000,
                "with_payload": ["category", "brand", "facets"], "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % C, body)["result"]
        pts.extend(res.get("points", []))
        offset = res.get("next_page_offset")
        if not offset:
            break

    rows = []
    for pt in pts:
        p = pt.get("payload") or {}
        tags = [t for t in (p.get("facets") or []) if str(t).startswith("marka:")]
        rows.append((p.get("category") or "", p.get("brand") or "",
                     tags[0][6:] if tags else "", bool(p.get("facets"))))

    n = len(rows)
    n_brand = sum(1 for r in rows if r[1])
    n_facets = sum(1 for r in rows if r[3])
    n_marka = sum(1 for r in rows if r[2])
    print("=" * 92)
    print("A) GLOBALIS FEDETTSEG")
    print("=" * 92)
    print("  termek osszesen        : %d" % n)
    print("  van `brand` payload    : %d  (%.1f%%)" % (n_brand, 100.0 * n_brand / max(n, 1)))
    print("  van barmilyen `facets` : %d  (%.1f%%)" % (n_facets, 100.0 * n_facets / max(n, 1)))
    print("  van `facets:marka:*`   : %d  (%.1f%%)" % (n_marka, 100.0 * n_marka / max(n, 1)))
    print("  -> a kivaltas veszteseg-alapja: brand VAN de marka-cimke NINCS: %d"
          % sum(1 for r in rows if r[1] and not r[2]))

    print()
    print("=" * 92)
    print("B) A KEZI _BRANDS LISTA TETELENKENT (a kivaltas tenyleges ara)")
    print("=" * 92)
    print("  %-14s %8s %8s %8s   %s" % ("marka", "brand", "cimke", "veszt%", "megjegyzes"))
    fmap = load_map(CLIENT) or {}
    mapvals = set()
    for _s, ent in (fmap.get("categories") or {}).items():
        mapvals.update((ent.get("facets") or {}).get("marka") or {})
    for b in _BRANDS:
        nb = sum(1 for r in rows if b in fd._fold(r[1]))
        nt = sum(1 for r in rows if b in fd._fold(r[1]) and r[2])
        loss = 100.0 * (nb - nt) / max(nb, 1)
        note = []
        if len(b) < fd._MIN_LEN:
            note.append("KIESIK: _MIN_LEN=%d" % fd._MIN_LEN)
        if not any(v == b or v.startswith(b + "-") for v in mapvals):
            note.append("nincs a crawl-terkepben")
        print("  %-14s %8d %8d %7.0f%%   %s" % (b, nb, nt, loss, ", ".join(note) or "-"))

    print()
    print("=" * 92)
    print("C) A CRAWL-TERKEP MARKA-ERTEKEI, amik a SZOTAR-HIGIENIAN kiesnek")
    print("=" * 92)
    drop = {}
    for slug, ent in (fmap.get("categories") or {}).items():
        facets = ent.get("facets") or {}
        vv = facets.get("marka") or {}
        if not vv:
            continue
        cat_size = fd._cat_size(facets)
        for val, cnt in vv.items():
            if not fd._usable(val, cnt, cat_size, fd._norm_key(slug)):
                why = ("rovid(<%d)" % fd._MIN_LEN) if len(str(val)) < fd._MIN_LEN \
                    else "nem-szelektiv/egyeb"
                drop.setdefault((str(val), why), []).append((slug, cnt))
    for (val, why), where in sorted(drop.items(), key=lambda kv: -sum(c for _s, c in kv[1])):
        tot = sum(c for _s, c in where)
        print("  %-30s %-22s %5d termek %d kategoriaban" % (val, why, tot, len(where)))

    print()
    print("=" * 92)
    print("D) KATEGORIANKENTI FEDETTSEG (top 15 termekszam szerint)")
    print("=" * 92)
    per = {}
    for cat, brand, tag, _f in rows:
        d = per.setdefault(cat, [0, 0, 0])
        d[0] += 1
        d[1] += 1 if brand else 0
        d[2] += 1 if tag else 0
    print("  %-46s %6s %6s %6s" % ("kategoria", "ossz", "brand", "cimke"))
    for cat, d in sorted(per.items(), key=lambda kv: -kv[1][0])[:15]:
        print("  %-46s %6d %6d %6d" % (cat[-46:], d[0], d[1], d[2]))


asyncio.run(main())

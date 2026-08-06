"""m82f ADATFELVÉTEL — a kategória-szándék feloldása szülő-szinten ("laptop" → ?).

Nyitott eset: "Van 32 GB memóriával laptopotok?" → a kérdésből nem oldható fel
kategória (a payload-levél neve "ÚJ Notebook"), ezért a kapu a találat-alapú
fallbackre esik, ami RAM-modulokat ad.

Ez a lépés CSAK MÉR, nem javasol: kell a szülő-út szerkezete, a levelenkénti
termékszám és a facet_map fedettsége, mielőtt bármilyen szabályt írunk.

Futtatás:  docker exec -i chatbot-api-prod python - < tools/m82f_catdiag.py
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
    from app.services.facetdict import _cat_parts, _leaf, _norm_key, detect_category
    from app.services.linkfacet import load_map
    from app.services.retrieval import category_catalog

    # 1) termékszám kategóriánként
    cats = {}
    offset = None
    for _ in range(30):
        body = {"filter": {"must": [{"key": "client_id", "match": {"value": CLIENT}},
                                    {"key": "type", "match": {"value": "product"}}]},
                "limit": 1000, "with_payload": ["category"], "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % C, body)["result"]
        for pt in res.get("points", []):
            c = (pt.get("payload") or {}).get("category")
            if c:
                cats[c] = cats.get(c, 0) + 1
        offset = res.get("next_page_offset")
        if not offset:
            break
    print("termék kategóriákkal: %d | distinct: %d\n" % (sum(cats.values()), len(cats)))

    catalog = await category_catalog(CLIENT)
    fmap = load_map(CLIENT) or {}
    ments = (fmap.get("categories") or {})
    slugkeys = {_norm_key(s): s for s in ments}

    # 2) szülő-út szerkezet
    parents = {}
    for c in catalog:
        parts = [p.strip() for p in str(c).split(">")]
        par = " > ".join(parts[:-1]) if len(parts) > 1 else "(nincs szülő)"
        parents.setdefault(par, []).append((parts[-1], cats.get(c, 0), c))

    print("=" * 96)
    print("A) SZÜLŐ-ÚT → levelek (termékszám); a * = a levél NINCS a facet_map-ben")
    print("=" * 96)
    for par in sorted(parents, key=lambda p: -sum(n for _, n, _ in parents[p])):
        tot = sum(n for _, n, _ in parents[par])
        inmap = "IGEN" if _norm_key(_leaf(par)) in slugkeys else "nem"
        print("\n%-46s ossz=%-6d levél=%-3d | szülő a facet_mapben: %s"
              % (par[:46], tot, len(parents[par]), inmap))
        for leaf, n, full in sorted(parents[par], key=lambda t: -t[1]):
            star = "" if _norm_key(leaf) in slugkeys else " *"
            print("     %-44s %6d%s" % (leaf[:44], n, star))

    # 3) mely szülő-nevek illeszthetők egyáltalán kérdésre (a _cat_parts szabályai szerint)
    print("\n" + "=" * 96)
    print("B) SZÜLŐ-NEVEK mint lehetséges kategória-jelöltek (_cat_parts a szülő levelére)")
    print("=" * 96)
    for par in sorted(parents):
        if par == "(nincs szülő)":
            continue
        print("  %-44s -> %s | levelek: %d"
              % (par[:44], _cat_parts(par), len(parents[par])))

    # 4) a nyitott kérdés-korpusz mai állapota
    print("\n" + "=" * 96)
    print("C) A NYITOTT KORPUSZ — ma mit ad a detect_category")
    print("=" * 96)
    CASES = [
        "Van 32 GB memóriával laptopotok?",
        "Milyen laptopokat ajánlotok?",
        "Keresek egy laptopot",
        "Van notebookotok?",
        "Milyen notebookjaitok vannak 16 GB RAM-mal?",
        "Melyik a legolcsóbb laptop?",
        "Használt laptopot keresek",
        "Felújított notebookot szeretnék",
        "Van laptop táskátok?",
        "Milyen notebook hűtőt ajánlotok?",
    ]
    for q in CASES:
        print("  %-46s -> %r" % (q[:46], _leaf(detect_category(q, catalog)) or "(fallback)"))

    # 5) a facet_map azon bejegyzései, amikhez NINCS payload-kategória (és fordítva)
    print("\n" + "=" * 96)
    print("D) FEDETTSÉG: facet_map slug vs payload-kategória")
    print("=" * 96)
    leafkeys = {_norm_key(_leaf(c)) for c in catalog}
    only_map = [s for k, s in slugkeys.items() if k not in leafkeys]
    only_pl = [c for c in catalog if _norm_key(_leaf(c)) not in slugkeys]
    print("facet_map bejegyzés: %d | payload-kategória: %d" % (len(ments), len(catalog)))
    print("CSAK a mapben (%d): %s" % (len(only_map), sorted(only_map)[:40]))
    print("CSAK payloadban (%d): %s" % (len(only_pl), [_leaf(c) for c in sorted(only_pl)][:40]))


asyncio.run(main())

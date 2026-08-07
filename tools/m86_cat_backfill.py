"""m86 BACKFILL: `category` + `cat_tags` a MEGLEVO text payloadbol.

Miert kell: a builder-oldali kinyeres (paramextract.extract_params) csak az UJ/valtozott
terméket eri el, a sync ugyanis kizarolag azokat upsertali. A m79b-s category-kinyeres ota
a Sellvio/Woo tenantok pontjai nem valtoztak -> a text 96-100%-ban tartalmazza a
"Kategoria: ..." sort, a payload megis ures. Egyedul a notebookstore kapott akkor backfillt.

A tool a PRODUCTION fuggvenyt hivja (nincs shadow-drift, a m84 tanulsaga szerint), ezert a
PATCHELT app/-ot kell mountolni -- az api-konteneRBE sutott kod meg a regi:

  docker run --rm -i --network container:chatbot-api-prod \\
    -v "$PWD/app:/app/app" -w /app chatbot-prod-api:latest python - < tools/m86_cat_backfill.py

DRY-RUN alapbol. Iras: -e APPLY=1 ; egy tenant: -e ONLY=teslashop
"""
import json
import os
import sys
import urllib.request
from collections import defaultdict

sys.path.insert(0, "/app")
from app.services.paramextract import extract_params  # noqa: E402  (a PRODUCTION logika)

Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
APPLY = os.environ.get("APPLY") == "1"
ONLY = [c for c in (os.environ.get("ONLY") or "").split(",") if c]
IDCHUNK = 2000


def post(path, body, timeout=300):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


tenants = [t["value"] for t in post("/collections/%s/facet" % COLL,
                                    {"key": "client_id", "limit": 50})["result"]["hits"]]
if ONLY:
    tenants = [t for t in tenants if t in ONLY]

print("MOD: %s" % ("APPLY (IR)" if APPLY else "DRY-RUN"))
print("%-16s %8s %8s %8s %8s %7s" % ("tenant", "termek", "kinyert", "valtozik", "csoport", "tag/db"))
print("-" * 62)

total_w = 0
for client in sorted(tenants):
    groups = defaultdict(list)
    n = got = same = 0
    tagset = set()
    off = None
    while True:
        body = {"limit": 1000, "with_payload": ["text", "category", "cat_tags"],
                "with_vector": False,
                "filter": {"must": [{"key": "client_id", "match": {"value": client}},
                                    {"key": "type", "match": {"value": "product"}}]}}
        if off is not None:
            body["offset"] = off
        res = post("/collections/%s/points/scroll" % COLL, body)["result"]
        pts = res.get("points") or []
        for p in pts:
            n += 1
            pl = p.get("payload") or {}
            new = extract_params("", pl.get("text") or "")
            cat = new.get("category") or ""
            tags = new.get("cat_tags") or []
            if not cat:
                continue
            got += 1
            tagset.update(tags)
            if (pl.get("category") or "") == cat and list(pl.get("cat_tags") or []) == tags:
                same += 1
                continue
            groups[(cat, json.dumps(tags, ensure_ascii=False))].append(p["id"])
        off = res.get("next_page_offset")
        if not off or not pts:
            break

    to_write = sum(len(v) for v in groups.values())
    total_w += to_write
    print("%-16s %8d %8d %8d %8d %7d"
          % (client, n, got, to_write, len(groups), len(tagset)))

    if APPLY and to_write:
        for (cat, tags_json), ids in groups.items():
            payload = {"category": cat, "cat_tags": json.loads(tags_json)}
            for i in range(0, len(ids), IDCHUNK):
                post("/collections/%s/points/payload?wait=true" % COLL,
                     {"payload": payload, "points": ids[i:i + IDCHUNK]})

print("\nOSSZESEN irando pont: %d  (%s)" % (total_w, "KIIRVA" if APPLY else "csak DRY-RUN"))
if not APPLY:
    print("Iras:  -e APPLY=1")

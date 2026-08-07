"""m84 BACKFILL: a meglevo Qdrant-pontokra ratesszuk a szarmaztatott `available`-t.

A builder-fix (models.derive_available) csak az UJ / valtozott termekeket eri el,
a meglevo ~100k pont available mezoje hianyzik -> a keszlet-szuro tovabbra sem fogna.
Ez a tool a mar meglevo `stock` payloadbol tolti fel, tenantonkent, set_payload
MERGE-dzsel (a vektor es a tobbi mezo erintetlen).

DRY-RUN alapbol. Iras: APPLY=1 kornyezeti valtozoval.
  docker exec -i -e APPLY=1 chatbot-api-prod python - < tools/m84_avail_backfill.py
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, "/app")

Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
APPLY = os.environ.get("APPLY") == "1"
ONLY = [c for c in (os.environ.get("ONLY") or "").split(",") if c]
BATCH = 1000


def post(path, body, timeout=180):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def derive(available, stock_str):
    """A production logika tukre (app/sync/models.derive_available)."""
    if available is not None:
        return bool(available)
    raw = str(stock_str or "").replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw) > 0
    except ValueError:
        return None


tenants = [t["value"] for t in post("/collections/%s/facet" % COLL,
                                    {"key": "client_id", "limit": 50})["result"]["hits"]]
if ONLY:
    tenants = [t for t in tenants if t in ONLY]

print("MOD: %s | tenantok: %d" % ("IRAS (APPLY=1)" if APPLY else "DRY-RUN", len(tenants)))
print("%-20s %8s %8s %8s %8s %8s" % ("tenant", "termek", "van av", "UJ av=T", "UJ av=F", "kihagy"))
grand = [0, 0, 0]

for cid in sorted(tenants):
    n = have = 0
    to_true, to_false, skip = [], [], 0
    offset = None
    for _ in range(120):
        body = {"filter": {"must": [{"key": "client_id", "match": {"value": cid}},
                                    {"key": "type", "match": {"value": "product"}}]},
                "limit": 1000, "with_payload": ["available", "stock"], "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % COLL, body)["result"]
        for pt in res.get("points", []):
            n += 1
            p = pt.get("payload") or {}
            if p.get("available") is not None:
                have += 1
                continue
            av = derive(None, p.get("stock"))
            if av is True:
                to_true.append(pt["id"])
            elif av is False:
                to_false.append(pt["id"])
            else:
                skip += 1
        offset = res.get("next_page_offset")
        if not offset:
            break
    print("%-20s %8d %8d %8d %8d %8d" % (cid, n, have, len(to_true), len(to_false), skip))
    grand[0] += len(to_true)
    grand[1] += len(to_false)
    grand[2] += skip
    if APPLY:
        for val, ids in ((True, to_true), (False, to_false)):
            for i in range(0, len(ids), BATCH):
                chunk = ids[i:i + BATCH]
                post("/collections/%s/points/payload?wait=true" % COLL,
                     {"payload": {"available": val}, "points": chunk})
        if to_true or to_false:
            print("    -> beirva: %d True, %d False" % (len(to_true), len(to_false)))

print()
print("OSSZESEN: UJ available=True %d | available=False %d | keszlet-adat nelkul kihagyva %d"
      % (grand[0], grand[1], grand[2]))
if not APPLY:
    print("DRY-RUN volt -- iras: APPLY=1")

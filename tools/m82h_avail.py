"""m82h/2 — MIERT csak 36,6% a `facets` fedettseg?

Hipotezis: a cimke-crawl a bolt ELO szuro-oldalait jarja be, a Qdrant viszont a
TELJES feedet tartalmazza (kifuto/nem elerheto termekekkel egyutt). Ha igen, a
fedettseg nem crawl-hiba, hanem feed-kerdes (Kocsi/Global-Tender nyitott pont).

Futtatas:  docker exec -i chatbot-api-prod python - < tools/m82h_avail.py
"""
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


pts = []
offset = None
for _ in range(30):
    body = {"filter": {"must": [{"key": "client_id", "match": {"value": CLIENT}},
                                {"key": "type", "match": {"value": "product"}}]},
            "limit": 1000,
            "with_payload": ["category", "available", "facets"], "with_vector": False}
    if offset:
        body["offset"] = offset
    res = post("/collections/%s/points/scroll" % C, body)["result"]
    pts.extend(res.get("points", []))
    offset = res.get("next_page_offset")
    if not offset:
        break

rows = []
avail_vals = {}
for pt in pts:
    p = pt.get("payload") or {}
    a = p.get("available")
    avail_vals[repr(a)] = avail_vals.get(repr(a), 0) + 1
    rows.append((p.get("category") or "", bool(a), bool(p.get("facets"))))

n = len(rows)
na = sum(1 for r in rows if r[1])
nf = sum(1 for r in rows if r[2])
naf = sum(1 for r in rows if r[1] and r[2])
print("termek: %d | available: %d (%.1f%%) | van facets: %d (%.1f%%)"
      % (n, na, 100.0 * na / max(n, 1), nf, 100.0 * nf / max(n, 1)))
print("available ES cimkezett: %d -> az ELERHETO termekek %.1f%%-a cimkezett"
      % (naf, 100.0 * naf / max(na, 1)))
print("cimkezett DE nem available: %d" % (nf - naf))
print("available ertekek eloszlasa: %s" % sorted(avail_vals.items(), key=lambda kv: -kv[1])[:6])

per = {}
for cat, av, fx in rows:
    d = per.setdefault(cat, [0, 0, 0, 0])
    d[0] += 1
    d[1] += 1 if av else 0
    d[2] += 1 if fx else 0
    d[3] += 1 if (av and fx) else 0

print()
print("%-46s %6s %6s %6s %7s" % ("kategoria", "ossz", "avail", "cimke", "av+cim%"))
for cat, d in sorted(per.items(), key=lambda kv: -kv[1][0])[:20]:
    pct = 100.0 * d[3] / max(d[1], 1)
    print("%-46s %6d %6d %6d %6.0f%%" % (cat[-46:], d[0], d[1], d[2], pct))

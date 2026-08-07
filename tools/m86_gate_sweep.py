"""m86 KAPU-SWEEP: a kategoria-kapu KOCKAZAT-TERKEPE a valodi kerdes-korpuszon.

A production utat tukrozi: a katalogus a Qdrant facet API-bol jon a `cat_tags` kulcsra
(pontosan ugy, mint a retrieval.cat_tag_catalog), a feloldas pedig a production
facetdict.detect_category. Minden feloldott (kerdes -> kategoria) par KIIRODIK, hogy
kezzel atnezheto legyen -- ez a kotelezo kockazat-terkep a kapu elesitese elott.

  docker run --rm -i --network container:chatbot-api-prod \\
    -v "$PWD/app:/app/app" -v "$PWD/data:/app/data" -w /app \\
    chatbot-prod-api:latest python - < tools/m86_gate_sweep.py
"""
import json
import sys
import urllib.request
from collections import defaultdict

sys.path.insert(0, "/app")
from app.services.facetdict import detect_category  # noqa: E402

Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
QFILE = "/app/data/m86_q.tsv"
LIMIT = 400          # = retrieval._CAT_TAG_LIMIT
TENANTS = ["kellegyszerszam", "teslashop", "nagyonallatshop", "notebookstore",
           "smartzilla", "plcomfort", "mastercool", "rmweb"]
SHOW = 22


def post(path, body, timeout=300):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def catalog(client):
    body = {"key": "cat_tags", "limit": LIMIT, "exact": True,
            "filter": {"must": [{"key": "client_id", "match": {"value": client}},
                                {"key": "type", "match": {"value": "product"}}]}}
    hits = (post("/collections/%s/facet" % COLL, body).get("result") or {}).get("hits") or []
    return [str(h["value"]) for h in hits if h.get("value")], {str(h["value"]): h.get("count", 0) for h in hits}


questions = defaultdict(list)
with open(QFILE, encoding="utf-8", errors="replace") as fh:
    for ln in fh:
        if "\t" in ln:
            c, q = ln.rstrip("\n").split("\t", 1)
            if q.strip():
                questions[c].append(q.strip())

print("%-16s %6s %6s %7s %8s %9s" % ("tenant", "kat", "kerdes", "old", "old%", "med.fedes"))
print("-" * 58)
risk = {}
for client in TENANTS:
    cat, cnt = catalog(client)
    qs = questions.get(client, [])
    hits, cov, pairs = 0, [], []
    for q in qs:
        r = detect_category(q, cat)
        if r:
            hits += 1
            cov.append(cnt.get(r, 0))
            pairs.append((q, r, cnt.get(r, 0)))
    cov.sort()
    med = cov[len(cov) // 2] if cov else 0
    print("%-16s %6d %6d %7d %7.0f%% %9d"
          % (client, len(cat), len(qs), hits, (100.0 * hits / (len(qs) or 1)), med))
    risk[client] = pairs

print("\n\n=== KOCKAZAT-TERKEP: MINDEN feloldott par (kezi atnezesre) ===")
for client in TENANTS:
    pairs = risk.get(client) or []
    if not pairs:
        continue
    print("\n--- %s (%d db) ---" % (client, len(pairs)))
    for q, r, n in pairs[:SHOW]:
        print("   %-62s -> %-34s (%d termek)" % (q[:62], r[:34], n))
    if len(pairs) > SHOW:
        print("   ... es meg %d" % (len(pairs) - SHOW))

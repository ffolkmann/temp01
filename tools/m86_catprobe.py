"""m86/0 PROBE: honnan szerezheto a `category` tenantonkent (CSAK OLVAS).

Kerdes: a m85/3 lelet szerint a `category` payloadot csak a webdoc builder irja.
A builder-recon szerint viszont a Sellvio/Woo builder IS ir ". Kategoria: ..." sort,
az Unas builder a kategoriat ZAROJELBEN irja (prefix nelkul, ezert a
paramextract._RE_CATEGORY nem talalja), a Shoprenter builder pedig SEHOL nem ir
kategoriat. Ez a probe a VALODI Qdrant-adaton igazolja vagy cafolja ezt.

Futtatas:  docker exec -i chatbot-api-prod python - < tools/m86_catprobe.py
"""
import json
import re
import sys
import urllib.request

sys.path.insert(0, "/app")

Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
SAMPLE = 300

KAT = "Kateg\u00f3ria:"          # 'Kategoria:' ekezettel
RE_KAT = re.compile(r"kateg[o\u00f3]ria:[ \t]*([^\n]+)", re.IGNORECASE)
# Unas text-alak:  NEV [\u2014 12 345 Ft] (KATEGORIA)[. Keszlet: N db]...
RE_UNAS = re.compile(r"\(([^()]{2,120})\)\s*(?:\.|$)")


def post(path, body, timeout=180):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def base_must(c):
    return [{"key": "client_id", "match": {"value": c}},
            {"key": "type", "match": {"value": "product"}}]


def count(must):
    return post("/collections/%s/points/count" % COLL,
                {"exact": True, "filter": {"must": must}})["result"]["count"]


tenants = [t["value"] for t in post("/collections/%s/facet" % COLL,
                                    {"key": "client_id", "limit": 50})["result"]["hits"]]

print("%-16s %8s %8s %7s  %6s %6s" % ("tenant", "termek", "cat_pld", "cat_%", "txtKAT", "unasZJ"))
print("-" * 62)

samples = {}
for c in sorted(tenants):
    bm = base_must(c)
    n = count(bm)
    if not n:
        continue
    empty = count(bm + [{"is_empty": {"key": "category"}}])
    ncat = n - empty

    pts = post("/collections/%s/points/scroll" % COLL,
               {"limit": SAMPLE, "with_payload": ["text", "name", "category"],
                "with_vector": False, "filter": {"must": bm}})["result"]["points"]
    kat = zj = 0
    for p in pts:
        t = (p.get("payload") or {}).get("text") or ""
        if RE_KAT.search(t):
            kat += 1
        if RE_UNAS.search(t):
            zj += 1
    m = len(pts) or 1
    print("%-16s %8d %8d %6.1f%%  %5.0f%% %5.0f%%"
          % (c, n, ncat, 100.0 * ncat / n, 100.0 * kat / m, 100.0 * zj / m))
    samples[c] = [((p.get("payload") or {}).get("text") or "")[:230] for p in pts[:3]]

print("\n\n=== MINTA-TEXTEK (elso 230 karakter) ===")
for c in sorted(samples):
    print("\n--- %s ---" % c)
    for i, t in enumerate(samples[c], 1):
        print("  %d) %s" % (i, t.replace("\n", " ")))

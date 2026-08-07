"""m87 ELOMERES: milyen gyakori a nem-latin szo-szivargas a VALODI valaszokban?

A m78 tanulsaga szerint a poszt-guard tuzelesi aranyat MERNI kell a bevezetes elott
(a m77 guardja 62%-ban tuzelt feleslegesen -> dupla LLM-hivas). Itt a kerdes:
  (a) hany tarolt valaszban van nem-latin szo (tenantonkent),
  (b) ezek kozul melyik LEGITIM (a bolt terneknevebol jon) es melyik a modell talalmanya.

A production fuggvenyt hivja (app/services/langguard.py), ezert a mountolt app/ kell:

  docker run --rm -i --network container:chatbot-api-prod \\
    -v "$PWD/app:/app/app" -v "$PWD/data:/app/data" -w /app \\
    chatbot-prod-api:latest python - < tools/m87_langscan.py

Bemenet: /app/data/m87_answers.tsv  (client_id \\t answer, ujsorok szokozre cserelve)
"""
import json
import sys
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, "/app")
from app.services.langguard import foreign_tokens  # noqa: E402

Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
AFILE = "/app/data/m87_answers.tsv"


def post(path, body, timeout=300):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def catalog_text(client):
    """A tenant OSSZES terneknevenek (+sku) osszefuzese -- a legitim-kapu bemenete."""
    buf = []
    off = None
    while True:
        body = {"limit": 1000, "with_payload": ["name", "sku"], "with_vector": False,
                "filter": {"must": [{"key": "client_id", "match": {"value": client}},
                                    {"key": "type", "match": {"value": "product"}}]}}
        if off is not None:
            body["offset"] = off
        res = post("/collections/%s/points/scroll" % COLL, body)["result"]
        pts = res.get("points") or []
        for p in pts:
            pl = p.get("payload") or {}
            buf.append(str(pl.get("name") or ""))
            buf.append(str(pl.get("sku") or ""))
        off = res.get("next_page_offset")
        if not off or not pts:
            break
    return " ".join(buf).lower()


answers = defaultdict(list)
with open(AFILE, encoding="utf-8", errors="replace") as fh:
    for ln in fh:
        if "\t" in ln:
            c, a = ln.rstrip("\n").split("\t", 1)
            if a.strip():
                answers[c].append(a)

total = sum(len(v) for v in answers.values())
print("VALASZ-KORPUSZ: %d valasz, %d tenant\n" % (total, len(answers)))

# 1. kor: kontextus-kapu NELKUL -- minden nem-latin szo
raw = {}
for c, lst in answers.items():
    hits = []
    for a in lst:
        t = foreign_tokens(a)
        if t:
            hits.append((a, t))
    if hits:
        raw[c] = hits

print("%-16s %7s %7s %7s" % ("tenant", "valasz", "nyers", "nyers%"))
print("-" * 42)
for c in sorted(answers):
    n = len(answers[c])
    h = len(raw.get(c, []))
    if h:
        print("%-16s %7d %7d %6.1f%%" % (c, n, h, 100.0 * h / n))

# 2. kor: legitim-kapu a tenant terneknevei ellen
print("\n\n=== A KONTEXTUS-KAPU UTAN (ami NEM a bolt adata = valodi szivargas) ===")
print("%-16s %7s %7s %8s" % ("tenant", "valasz", "szivarg", "arany"))
print("-" * 44)
detail = {}
for c in sorted(raw):
    allow = catalog_text(c)
    leaks = []
    for a, _t in raw[c]:
        t2 = foreign_tokens(a, allow)
        if t2:
            leaks.append((a, t2))
    n = len(answers[c])
    print("%-16s %7d %7d %7.2f%%" % (c, n, len(leaks), 100.0 * len(leaks) / n))
    detail[c] = leaks

print("\n\n=== SZIVARGO SZAVAK (gyakorisag) ===")
for c in sorted(detail):
    cnt = Counter()
    for _a, toks in detail[c]:
        for t in toks:
            cnt[t] += 1
    if cnt:
        print("\n--- %s ---" % c)
        for tok, k in cnt.most_common(20):
            print("   %-24s %3d db" % (tok, k))

print("\n\n=== MINTA-RESZLETEK (max 3 tenantonkent) ===")
for c in sorted(detail):
    for a, toks in detail[c][:3]:
        i = min((a.find(t) for t in toks if a.find(t) >= 0), default=0)
        print("\n[%s] %r" % (c, toks))
        print("   ...%s..." % a[max(0, i - 90):i + 90])

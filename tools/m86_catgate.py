"""m86/1 ELOMERES: mit erne a kategoria-kapu ott, ahol MA nincs `category` payload.

A m86/0 probe leletei:
  - Sellvio (mastercool/teslashop/plcomfort) + Woo (nagyonallatshop/rmweb): a text
    96-100%-ban tartalmazza a "Kategoria: ..." sort, a payload megis 0-19% ->
    NEM builder-hiba: a sync csak a VALTOZOTT terméket upsertali, es a m79b-s
    category-kinyeres ota ezek a pontok nem valtoztak (csak a notebookstore kapott
    backfillt). Ezeken a tenantokon a category = TISZTA BACKFILL, kod nelkul.
  - Unas (kellegyszerszam/smartzilla): a kategoria a textben ZAROJELBEN all, "Kategoria:"
    prefix nelkul, `|`-elvalasztasu uttal -> a paramextract._RE_CATEGORY nem talalja.
  - Shoprenter (4mfrigo/copygo/ecowindoor/fishingoutlet): SEHOL nincs kategoria a textben.

Ez a mero azt donti el, hogy a backfill-bol szarmazo ertek HASZNALHATO-e kapunak:
  (A) a KOMBINALT ertek (amit a builder ir: Sellvio/Woo ", ".join -> LISTA, nem hierarchia)
  (B) a RESZ-ertekek (vesszo/">" mentén szetszedve = valodi kategoria-nevek)
Mindkettore: hany valodi kerdes old fel kategoriat, es a feloldott ertek HANY terméket fed.

Futtatas:  docker exec -i chatbot-api-prod python - < tools/m86_catgate.py
Bemenet:   /app/data/m86_q.tsv  (client_id \\t question)  -- a job generalja psql-bol
"""
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, "/app")
from app.services.facetdict import detect_category  # noqa: E402

Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
QFILE = "/app/data/m86_q.tsv"
MAXQ = 250

RE_KAT = re.compile(r"kateg[o\u00f3]ria:[ \t]*([^\n]+)", re.IGNORECASE)
RE_UNAS = re.compile(r"\sFt\s*\(([^()]{2,160})\)\s*(?:\.|$)")
RE_STOCKWORD = re.compile(r"k\u00e9szlet|rakt\u00e1ron|rendelhet|inakt\u00edv", re.IGNORECASE)

MODE = {
    "mastercool": "kat", "teslashop": "kat", "plcomfort": "kat",
    "nagyonallatshop": "kat", "rmweb": "kat", "notebookstore": "kat",
    "kellegyszerszam": "unas", "smartzilla": "unas",
}


def post(path, body, timeout=300):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def extract(text, mode):
    """A textbol kinyert kategoria-ertek (a leendo payload), vagy ''."""
    t = text or ""
    if mode == "unas":
        m = RE_UNAS.search(t)
        if not m:
            return ""
        v = m.group(1).strip()
        if RE_STOCKWORD.search(v):
            return ""
        return " > ".join(x.strip() for x in v.split("|") if x.strip())
    m = RE_KAT.search(t)
    if not m:
        return ""
    v = m.group(1)
    cut = v.find(". ")
    if cut != -1:
        v = v[:cut]
    return v.strip().rstrip(".").strip()


def parts_of(val):
    out = []
    for seg in str(val or "").split(">"):
        for p in seg.split(","):
            p = p.strip().rstrip(".").strip()
            if len(p) >= 3:
                out.append(p)
    return out


# --- kerdes-korpusz ---
questions = defaultdict(list)
try:
    with open(QFILE, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if "\t" not in ln:
                continue
            c, q = ln.rstrip("\n").split("\t", 1)
            q = q.strip()
            if q and len(questions[c]) < MAXQ:
                questions[c].append(q)
except OSError as e:
    print("!! nincs kerdes-korpusz: %s" % e)

print("KORPUSZ: " + ", ".join("%s=%d" % (c, len(v)) for c, v in sorted(questions.items())))
print()
hdr = ("%-16s %7s %7s %7s  %7s %7s %8s  %7s %7s %8s"
       % ("tenant", "termek", "kinyert", "fed%", "A_kat", "A_old%", "A_medfed", "B_kat", "B_old%", "B_medfed"))
print(hdr)
print("-" * len(hdr))

detail = {}
for client, mode in sorted(MODE.items()):
    combined = Counter()
    partcnt = Counter()
    n = 0
    off = None
    while True:
        body = {"limit": 1000, "with_payload": ["text"], "with_vector": False,
                "filter": {"must": [{"key": "client_id", "match": {"value": client}},
                                    {"key": "type", "match": {"value": "product"}}]}}
        if off is not None:
            body["offset"] = off
        res = post("/collections/%s/points/scroll" % COLL, body)["result"]
        pts = res.get("points") or []
        for p in pts:
            n += 1
            v = extract((p.get("payload") or {}).get("text") or "", mode)
            if v:
                combined[v] += 1
                for pa in set(parts_of(v)):
                    partcnt[pa] += 1
        off = res.get("next_page_offset")
        if not off or not pts:
            break

    got = sum(combined.values())
    catA = list(combined)
    catB = list(partcnt)
    qs = questions.get(client, [])

    def run(cat, cnt):
        hits, cov, ex = 0, [], []
        for q in qs:
            r = detect_category(q, cat)
            if r:
                hits += 1
                cov.append(cnt.get(r, 0))
                if len(ex) < 4:
                    ex.append((q[:56], r[:52], cnt.get(r, 0)))
        cov.sort()
        med = cov[len(cov) // 2] if cov else 0
        return hits, med, ex

    aH, aM, aEx = run(catA, combined)
    bH, bM, bEx = run(catB, partcnt)
    nq = len(qs) or 1
    print("%-16s %7d %7d %6.0f%%  %7d %6.0f%% %8d  %7d %6.0f%% %8d"
          % (client, n, got, 100.0 * got / (n or 1),
             len(catA), 100.0 * aH / nq, aM, len(catB), 100.0 * bH / nq, bM))
    detail[client] = (aEx, bEx, combined.most_common(5), partcnt.most_common(6))

print("\n\n=== RESZLETEK ===")
for c in sorted(detail):
    aEx, bEx, topA, topB = detail[c]
    print("\n--- %s ---" % c)
    print("  top KOMBINALT ertekek: " + " | ".join("%s (%d)" % (k[:44], v) for k, v in topA))
    print("  top RESZ-nevek:        " + " | ".join("%s (%d)" % (k[:30], v) for k, v in topB))
    for lbl, ex in (("A", aEx), ("B", bEx)):
        for q, r, cv in ex:
            print("   %s  %-56s -> %-52s (%d termek)" % (lbl, q, r, cv))

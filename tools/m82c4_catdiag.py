"""m82c/4 diagnosztika: miert nem all be a kategoria-kapu osszetett szavaknal.

Futtatas: docker exec -i chatbot-api-prod python - < tools/m82c4_catdiag.py
Nem modosit semmit.
"""
import json
import sys
import urllib.request

sys.path.insert(0, "/app")

from app.services.facetdict import _leaf, _norm_key, detect_category, detect_facet_tags  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

Q = "http://qdrant:6333"
C = "cx_chatbot_v2"
CID = "notebookstore"
FMAP = load_map(CID)


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read().decode())


cats = {}
offset = None
for _ in range(20):
    body = {"filter": {"must": [{"key": "client_id", "match": {"value": CID}},
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

CATS = sorted(cats)
print("distinct category:", len(CATS))
print()

print("=== 1. detect_category OSSZETETT SZAVAKRA ===")
print("%-46s %s" % ("kerdes", "felismert kategoria"))
print("-" * 100)
CASES = [
    "Melyik a legolcsobb lezernyomtato?",
    "Melyik a legolcsobb lezeres nyomtato?",       # kulon irva -> mukodnie kell
    "Melyik a legolcsobb tintasugaras nyomtato?",
    "Melyik a legolcsobb gamerlaptop?",            # osszetett
    "Melyik a legolcsobb gamer laptop?",           # kulon
    "Melyik a legolcsobb notebooktaska?",          # osszetett
    "Melyik a legolcsobb notebook taska?",
    "Melyik a legolcsobb gamer asztali szamitogep?",
    "Melyik a legolcsobb 4K monitor?",
]
for q in CASES:
    got = detect_category(q, CATS)
    print("%-46s %s" % (q[:46], _leaf(got) or "(NINCS -> talalat-fallback)"))

print()
print("=== 2. lezernyomtato: mi tortenik a ket uton ===")
q = "Melyik a legolcsobb lezernyomtato?"
det = detect_category(q, CATS)
print("  detect_category      :", det or "(nincs)")
print("  tags a detektalttal  :", detect_facet_tags(q, [], FMAP, category=det))
forced = [c for c in CATS if _norm_key(_leaf(c)) == "nyomtato"]
print("  a valodi kategoria   :", forced)
if forced:
    print("  tags rakenyszeritve  :", detect_facet_tags(q, [], FMAP, category=forced[0]))

print()
print("=== 3. mely kategoria-nevek allnak osszetett szo VEGEN? (kockazat-terkep) ===")
leaves = sorted({_norm_key(_leaf(c)) for c in CATS if len(_norm_key(_leaf(c))) >= 5})
print("  >=5 karakteres kategoria-nev:", len(leaves))
# melyik kategoria-nev tartalmaz masikat a vegen -> ezek utkoznenek, ha lazitunk
clash = []
for a in leaves:
    for b in leaves:
        if a != b and a.endswith(b):
            clash.append((a, b))
print("  egymas vegzodesei (lazitas eseten utkoznenek):", len(clash))
for a, b in clash[:15]:
    print("    %-34s vege: %s" % (a, b))

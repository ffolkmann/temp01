"""m82b sweep: a generikus facet-felismero offline probaja a VALODI terkepen.

Futtatas: docker exec -i chatbot-api-prod python - < tools/m82b_sweep.py
Nem modosit semmit, csak kiir.
"""
import json
import sys
import urllib.request

sys.path.insert(0, "/app")
from app.services.facetdict import _leaf, _norm_key, build_facet_conditions, detect_facet_tags  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

Q = "http://qdrant:6333"
C = "cx_chatbot_v2"
CID = "notebookstore"


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read().decode())


def count(conds):
    f = {"must": [{"key": "client_id", "match": {"value": CID}},
                  {"key": "type", "match": {"value": "product"}}] + list(conds)}
    return post("/collections/%s/points/count" % C, {"filter": f, "exact": True})["result"]["count"]


# --- valodi category payload-ertekek ---
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
print("distinct category:", len(cats))


def find(slug):
    tgt = _norm_key(slug)
    for c in cats:
        if _norm_key(_leaf(c)) == tgt:
            return c
    return ""


fmap = load_map(CID)
CTX = {
    "uj-notebook": find("uj-notebook"),
    "monitor": find("monitor"),
    "nyomtato": find("nyomtato"),
    "notebook-taska-hatizsak": find("notebook-taska-hatizsak"),
    "3d-nyomtato-filament": find("3d-nyomtato-filament"),
}
print("\nKATEGORIA-KONTEXTUSOK:")
for k, v in CTX.items():
    print("  %-28s -> %r" % (k, v))

print("\nELERHETO ATTRIBUTUMOK (nem kihagyott):")
for slug in CTX:
    ent = ((fmap.get("categories") or {}).get(slug)) or {}
    fac = ent.get("facets") or {}
    from app.services.facetdict import _SKIP_ATTRS, _cat_size
    print("  %s (cat_size=%d):" % (slug, _cat_size(fac)))
    for a in sorted(fac):
        if a in _SKIP_ATTRS:
            continue
        vv = sorted(fac[a].items(), key=lambda kv: -kv[1])[:8]
        print("     %-26s %s" % (a, ", ".join("%s(%d)" % x for x in vv)))

CASES = [
    # (kategoria-kulcs, kerdes, elvart_tag vagy None = ures)
    ("uj-notebook", "legolcsóbb 16 GB RAM-os laptop", "memoria-meret:16gb"),
    ("uj-notebook", "legolcsóbb 32 GB memóriás notebook", "memoria-meret:32gb"),
    ("uj-notebook", "legolcsóbb Windows 11 Professional laptop", "operacios-rendszer:windows-11-professional"),
    ("uj-notebook", "legolcsóbb NVIDIA videokártyás laptop", "grafikus-vezerlo-gyarto:nvidia"),
    ("uj-notebook", "legolcsóbb ujjlenyomat-olvasós notebook", "extrak:ujjlenyomat-olvaso"),
    ("uj-notebook", "legolcsóbb NFC-s laptop", "extrak:nfc"),
    ("uj-notebook", "legolcsóbb érintőképernyős laptop", None),
    ("uj-notebook", "legolcsóbb laptop", None),
    ("uj-notebook", "legolcsóbb 17 colos laptop", None),
    ("uj-notebook", "legolcsóbb üzleti laptop", None),
    ("uj-notebook", "legolcsóbb ASUS laptop", None),
    ("uj-notebook", "mennyibe kerül a szállítás?", None),
    ("uj-notebook", "van rá 3 év garancia?", None),
    ("uj-notebook", "fekete pénteki akciós laptop", None),
    ("uj-notebook", "nem szeretnék drága gépet", None),
    ("uj-notebook", "melyik a legjobb intelligens megoldás?", None),
    ("monitor", "legolcsóbb IPS paneles monitor", None),
    ("monitor", "legolcsóbb beépített hangszórós monitor", None),
    ("monitor", "legolcsóbb 4K monitor", None),
    ("nyomtato", "legolcsóbb lézernyomtató", None),
    ("nyomtato", "legolcsóbb A4-es tintasugaras nyomtató", None),
    ("notebook-taska-hatizsak", "legolcsóbb bőr notebook táska", None),
    ("3d-nyomtato-filament", "legolcsóbb PLA filament", None),
    ("3d-nyomtato-filament", "legolcsóbb fekete filament", None),
]

print("\nSWEEP (kategoria | kerdes -> cimkek [szurt termekszam]):")
fp = 0
for key, q, exp in CASES:
    ctx = [CTX.get(key) or ""] * 5
    tags = detect_facet_tags(q, ctx, fmap)
    n = count(build_facet_conditions(tags)) if tags else -1
    mark = " "
    if exp and (exp not in tags):
        mark = "!"
    if exp is None and tags:
        mark = "?"
    print(" %s %-24s %-46s -> %-60s %s" % (
        mark, key, q, ", ".join(tags) or "-", ("[%d]" % n) if n >= 0 else ""))
print("\nJelmagyarazat: '!' = elvart cimke hianyzik, '?' = nem vart cimke jott (nezd meg, lehet helyes)")

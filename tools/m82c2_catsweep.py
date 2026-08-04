"""m82c/2 sweep: kategoria-szandek felismerese a kerdesbol, a VALODI adatokon.

Futtatas: docker exec -i chatbot-api-prod python - < tools/m82c2_catsweep.py
Nem modosit semmit, csak kiir. A kategoria-katalogus a Qdrant facet API-jabol
jon (ugyanaz, amit a retrieval hasznal).
"""
import json
import sys
import urllib.request

sys.path.insert(0, "/app")
from app.services.facetdict import (  # noqa: E402
    _leaf, build_facet_conditions, category_value, detect_category, detect_facet_tags,
)
from app.services.linkfacet import load_map  # noqa: E402

Q = "http://qdrant:6333"
C = "cx_chatbot_v2"
CID = "notebookstore"


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read().decode())


def _base(extra=None):
    must = [{"key": "client_id", "match": {"value": CID}},
            {"key": "type", "match": {"value": "product"}}]
    return must + list(extra or [])


def facet_values(key, extra=None):
    r = post("/collections/%s/facet" % C,
             {"key": key, "limit": 300, "exact": True, "filter": {"must": _base(extra)}})
    return [(h["value"], h["count"]) for h in ((r.get("result") or {}).get("hits") or [])]


def count(conds):
    return post("/collections/%s/points/count" % C,
                {"filter": {"must": _base(conds)}, "exact": True})["result"]["count"]


def cheapest(conds):
    """A szurt halmaz legolcsobb RAKTARON levo termeke (nev, ar)."""
    best = None
    offset = None
    cc = list(conds) + [{"key": "available", "match": {"value": True}}]
    for _ in range(10):
        body = {"filter": {"must": _base(cc)}, "limit": 500,
                "with_payload": ["name", "price"], "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % C, body)["result"]
        for pt in res.get("points", []):
            pl = pt.get("payload") or {}
            try:
                p = int(float(str(pl.get("price") or "").replace(" ", "").replace("\u00a0", "")))
            except (TypeError, ValueError):
                continue
            if p > 0 and (best is None or p < best[1]):
                best = (str(pl.get("name") or "")[:60], p)
        offset = res.get("next_page_offset")
        if not offset:
            break
    return best


CATALOG = [v for v, _ in facet_values("category")]
print("Qdrant distinct category:", len(CATALOG))
fmap = load_map(CID)
print("facet_map kategoriak:", len((fmap.get("categories") or {})))

NB = ["Laptop, Notebook > ÚJ Notebook"] * 5   # a tipikus (notebook-dominans) kontextus

CASES = [
    # (kerdes, elvart kategoria-level VAGY None ha nem szabad felismerni)
    ("Melyik a legolcsóbb gamer asztali számítógép?", "Asztali számítógép"),
    ("Melyik a legolcsóbb üzleti asztali számítógép?", "Asztali számítógép"),
    ("Keresek egy olcsó asztali számítógépet irodai munkára", "Asztali számítógép"),
    ("legolcsóbb 4K monitor", "Monitor"),
    ("legolcsóbb IPS paneles monitort keresek", "Monitor"),
    ("legolcsóbb notebook táska", "Notebook táska, hátizsák"),
    ("legolcsóbb A4-es tintasugaras nyomtató", "Nyomtató"),
    ("legolcsóbb PLA filament", None),  # a levelnev egeszben nincs a kerdesben -> recall-hiany, nem FP
    ("melyik a legolcsóbb tablet?", "Tablet"),
    # NEGATIV: nincs kategorianev a kerdesben -> a talalatok dontenek (mint eddig)
    ("Melyik a legolcsóbb gamer laptop?", None),
    ("Melyik a legolcsóbb üzleti notebook?", None),
    ("legolcsóbb 32 GB memóriás laptop", None),
    ("legolcsóbb 17 colos laptop", None),
    ("legolcsóbb ASUS laptop", None),
    ("legolcsóbb otthoni notebook", None),
    ("mennyibe kerül a szállítás?", None),
    ("van rá 3 év garancia?", None),
    ("fekete pénteki akciós laptop", None),
    ("nem szeretnék drága gépet", None),
    ("melyik a legjobb intelligens megoldás?", None),
]

print("\nSWEEP  (kerdes -> felismert kategoria | cimkek | szurt db)")
bad = 0
for q, exp in CASES:
    cat = detect_category(q, CATALOG)
    tags = detect_facet_tags(q, NB, fmap, category=cat)
    cv = category_value(NB, fmap, category=cat)
    n = count(build_facet_conditions(tags, cv)) if tags else -1
    ok = (_leaf(cat) == exp) if exp else (cat == "")
    if not ok:
        bad += 1
    print("%s %-46s -> %-28s %-34s %s" % (
        " " if ok else "!", q[:46], _leaf(cat) or "-", (",".join(tags) or "-"),
        (str(n) if n >= 0 else "-")))
print("\nELTERES AZ ELVARTTOL:", bad)

print("\nKULCS-ESETEK (legolcsobb raktaron levo a szurt halmazban):")
for q in ("Melyik a legolcsóbb gamer asztali számítógép?",
          "Melyik a legolcsóbb gamer laptop?",
          "Melyik a legolcsóbb üzleti notebook?",
          "legolcsóbb 32 GB memóriás laptop"):
    cat = detect_category(q, CATALOG)
    tags = detect_facet_tags(q, NB, fmap, category=cat)
    cv = category_value(NB, fmap, category=cat)
    conds = build_facet_conditions(tags, cv)
    print("  %-46s cat=%-24s tags=%-32s db=%s min=%s" % (
        q[:46], _leaf(cv) or "-", ",".join(tags) or "-",
        count(conds) if tags else "-", cheapest(conds) if tags else "-"))

"""m82g/1 adatfelvetel: a 4 kezi lista (taska-tipusa, szin, kijelzo-meret, marka)
crawl-terkep-oldali kepe -- MIT tudna a generikus szotar, ha kivezetnenk a _SKIP_ATTRS-bol.

Qdrant NEM kell. Futtatas:
  docker run --rm -i -v "$PWD/app:/app/app" -v "$PWD/data:/app/data" -w /app \
    chatbot-prod-api:latest python - < tools/m82g_map.py
"""
import sys

sys.path.insert(0, "/app")

from app.services import facetdict as fd  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

CID = "notebookstore"
FMAP = load_map(CID)
CATS = (FMAP.get("categories") or {})

TARGET = ["taska-tipusa", "szin", "kijelzo-meret", "marka"]

print("facet_map kategoriak: %d" % len(CATS))
print("_SKIP_ATTRS: %s" % sorted(fd._SKIP_ATTRS))
print()

for attr in TARGET:
    rows = []
    for slug, ent in CATS.items():
        vv = (ent.get("facets") or {}).get(attr) or {}
        if vv:
            rows.append((slug, ent, vv))
    tot_vals = sum(len(v) for _s, _e, v in rows)
    print("=" * 78)
    print("ATTR %-18s -> %d kategoriaban, osszesen %d ertek-elofordulas"
          % (attr, len(rows), tot_vals))
    print("=" * 78)
    for slug, ent, vv in sorted(rows, key=lambda r: -len(r[2])):
        facets = ent.get("facets") or {}
        cat_size = fd._cat_size(facets)
        cat_key = fd._norm_key(slug)
        ok, drop = [], []
        for val, n in sorted(vv.items(), key=lambda kv: -int(kv[1] or 0)):
            if fd._usable(val, n, cat_size, cat_key):
                ok.append("%s(%s)" % (val, n))
            else:
                # miert esett ki
                v = str(val)
                nk = fd._norm_key(v)
                if len(v) < fd._MIN_LEN or v in fd._STOP_VALUES:
                    why = "stop/rovid"
                elif cat_key and len(nk) >= 4 and nk in cat_key:
                    why = "kat-fonev"
                elif v.replace("-", "").replace(".", "").isdigit():
                    why = "szamos"
                elif cat_size and int(n or 0) >= fd._COVER_MAX * cat_size:
                    why = "nem-szelektiv"
                else:
                    why = "n<=0"
                drop.append("%s(%s,%s)" % (val, n, why))
        print("  %-34s cat_size=%-5d ertek=%d" % (slug, cat_size, len(vv)))
        if ok:
            print("      HASZNALHATO(%d): %s" % (len(ok), ", ".join(ok[:14])))
        if drop:
            print("      KIESIK(%d):      %s" % (len(drop), ", ".join(drop[:14])))
    print()

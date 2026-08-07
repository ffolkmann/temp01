"""m82i/1 ADAT-LELET: a facet-map fedettsegi rese (handoff 3.4).

Kerdes: mely payload-kategoriak hianyoznak a crawl-terkepbol, MEKKORA az uzleti
sulyuk (elerheto termek), es MIERT maradtak ki -- a homepage-nav nem eri el oket,
vagy nincs sajat szuro-oldaluk? A sitemap az alternativ felderito forras.

Csak olvas. Futtatas:
  docker exec -i chatbot-api-prod python - < tools/m82i_catgap.py
"""
import json
import re
import sys
import urllib.request

sys.path.insert(0, "/app")

from app.services import facetdict as fd  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

CLIENT = "notebookstore"
BASE = "https://notebookstore.hu"
Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read().decode())


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


# ---------------------------------------------------------------- 1) payload
pts = []
offset = None
for _ in range(40):
    body = {"filter": {"must": [{"key": "client_id", "match": {"value": CLIENT}},
                                {"key": "type", "match": {"value": "product"}}]},
            "limit": 1000,
            "with_payload": ["category", "available", "facets", "url", "name"],
            "with_vector": False}
    if offset:
        body["offset"] = offset
    res = post("/collections/%s/points/scroll" % COLL, body)["result"]
    pts.extend(res.get("points", []))
    offset = res.get("next_page_offset")
    if not offset:
        break

per = {}
for pt in pts:
    p = pt.get("payload") or {}
    cat = p.get("category") or ""
    d = per.setdefault(cat, {"n": 0, "av": 0, "fx": 0, "avfx": 0, "ex": []})
    d["n"] += 1
    av = bool(p.get("available"))
    fx = bool(p.get("facets"))
    d["av"] += 1 if av else 0
    d["fx"] += 1 if fx else 0
    d["avfx"] += 1 if (av and fx) else 0
    if av and len(d["ex"]) < 2:
        d["ex"].append((p.get("name") or "")[:52] + " | " + (p.get("url") or ""))

print("termek: %d | distinct kategoria: %d" % (len(pts), len(per)))

# ---------------------------------------------------------------- 2) terkep
FMAP = load_map(CLIENT)
CATS = FMAP.get("categories") or {}
slug_by_key = {}
for slug, ent in CATS.items():
    slug_by_key[fd._norm_key(slug)] = (slug, ent)
print("terkep-kategoriak: %d | generalva: %s" % (len(CATS), FMAP.get("generated_at")))


def leaf(cat):
    return cat.split(">")[-1].strip()


hit, miss = [], []
for cat, d in per.items():
    key = fd._norm_key(leaf(cat))
    if key in slug_by_key:
        hit.append((cat, d, slug_by_key[key]))
    else:
        miss.append((cat, d, key))

print("parositva: %d | HIANYZIK a terkepbol: %d" % (len(hit), len(miss)))

print()
print("=" * 96)
print("HIANYZO KATEGORIAK (elerheto termek szerint)")
print("=" * 96)
print("%-46s %6s %6s %6s  %s" % ("kategoria", "ossz", "avail", "cimke", "norm-kulcs"))
tot_av = 0
for cat, d, key in sorted(miss, key=lambda r: -r[1]["av"]):
    tot_av += d["av"]
    print("%-46s %6d %6d %6d  %s" % (cat[-46:], d["n"], d["av"], d["fx"], key))
print("-> a hianyzo kategoriakban osszesen %d ELERHETO termek" % tot_av)

print()
print("peldak (elerheto termek a 8 legnagyobb hianyzo kategoriabol):")
for cat, d, key in sorted(miss, key=lambda r: -r[1]["av"])[:8]:
    print("  %s" % cat)
    for e in d["ex"]:
        print("      %s" % e)

# ------------------------------------------------- 3) miert maradt ki? nav+sitemap
RE_CAT = re.compile(r'href="(?:https?://[^"/]+)?((?:/[a-z0-9-]+)*/[a-z0-9-]+-c\d+)/?"')
RE_ANY_CAT = re.compile(r'((?:/[a-z0-9-]+)*/[a-z0-9-]+-c\d+)')


def slugkey(path):
    return fd._norm_key(re.sub(r"-c\d+$", "", path.rsplit("/", 1)[-1]))


nav_keys, nav_paths = set(), {}
try:
    home = http_get(BASE + "/")
    for m in RE_CAT.finditer(home):
        nav_paths.setdefault(slugkey(m.group(1)), m.group(1))
    nav_keys = set(nav_paths)
    print()
    print("homepage-nav kategoria-linkek: %d (a crawl innen indul)" % len(nav_keys))
except Exception as e:  # noqa: BLE001
    print("homepage HIBA:", str(e)[:120])

sm_paths = {}
sitemaps = [BASE + "/sitemap.xml"]
seen_sm = set()
while sitemaps:
    u = sitemaps.pop(0)
    if u in seen_sm or len(seen_sm) > 25:
        continue
    seen_sm.add(u)
    try:
        xml = http_get(u, timeout=40)
    except Exception as e:  # noqa: BLE001
        print("sitemap HIBA %s: %s" % (u, str(e)[:90]))
        continue
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
        if loc.endswith(".xml"):
            sitemaps.append(loc)
            continue
        m = RE_ANY_CAT.search(loc.split("?")[0])
        if m and re.search(r"-c\d+/?$", loc.split("?")[0]):
            sm_paths.setdefault(slugkey(m.group(1)), m.group(1))
print("sitemap-fajlok: %d | kategoria-URL a sitemapben: %d" % (len(seen_sm), len(sm_paths)))

print()
print("=" * 96)
print("A HIANYZOK FELDERITHETOSEGE")
print("=" * 96)
print("%-40s %6s  %-8s %-8s %s" % ("kategoria (level)", "avail", "nav?", "sitemap?", "URL"))
n_sm = 0
for cat, d, key in sorted(miss, key=lambda r: -r[1]["av"]):
    in_nav = "IGEN" if key in nav_keys else "nem"
    p = sm_paths.get(key)
    if p:
        n_sm += 1
    print("%-40s %6d  %-8s %-8s %s"
          % (leaf(cat)[:40], d["av"], in_nav, "IGEN" if p else "nem", p or ""))
print("-> a %d hianyzobol %d megvan a sitemapben" % (len(miss), n_sm))

print()
print("kontroll: a terkepben van, de a payloadban NINCS ilyen kategoria:")
hit_keys = set(fd._norm_key(leaf(c)) for c, _d, _s in hit)
orphan = [s for k, (s, _e) in slug_by_key.items() if k not in hit_keys]
print("  %d db: %s" % (len(orphan), ", ".join(sorted(orphan)[:25])))

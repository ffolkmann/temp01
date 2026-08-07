"""m82i/2: a crawl CSAK a homepage-nav kategoria-linkjeit jarja (85 db).
Kerdes: a 16 hianyzo kategoria eloerul-e, ha a 2. SZINTET is bejarjuk
(a kategoria-oldalakon levo tovabbi -cNN linkek), es van-e sajat szuro-oldaluk?

Csak olvas, ~85 HTTP GET. Futtatas:
  docker exec -i chatbot-api-prod python - < tools/m82i_navdepth.py
"""
import re
import sys
import time
import urllib.request

sys.path.insert(0, "/app")

from app.services import facetdict as fd  # noqa: E402

BASE = "https://notebookstore.hu"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# a d03 diag hianyzo listaja (norm-kulcs -> nev)
MISS = {
    "webkamera": "Webkamera (22 elerheto)",
    "tvesmonitortartoallvany": "TV- es monitortarto (2)",
    "vrszemuveg": "VR szemuveg (1)",
    "felujitotthasznaltnotebook": "Felujitott-hasznalt notebook (0)",
    "videokartya": "Videokartya (0)",
    "splitklima": "Split Klima (0)",
    "digitalizalotabla": "Digitalizalo tabla (0)",
    "internettelefon": "Internet telefon (0)",
    "szamitogephuto": "Szamitogep huto (0)",
    "notebookhuto": "Notebook huto (0)",
    "jatekszoftver": "Jatekszoftver (0)",
    "vrszemuvegeskiegeszito": "VR szemuveg es kiegeszito (0)",
    "okosora": "Okosora (0)",
    "lampa": "Lampa (0)",
    "digitaliskepkeret": "Digitalis kepkeret (0)",
}

RE_CAT = re.compile(r'href="(?:https?://[^"/]+)?((?:/[a-z0-9-]+)*/[a-z0-9-]+-c\d+)/?"')
RE_FACET = re.compile(
    r'href="[^"]*?((?:/[a-z0-9-]+)*/[a-z0-9-]+-c\d+)/([a-z0-9-]+):([a-z0-9.\-]+)"')


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def key_of(path):
    return fd._norm_key(re.sub(r"-c\d+$", "", path.rsplit("/", 1)[-1]))


home = http_get(BASE + "/")
lvl1 = []
seen = set()
for m in RE_CAT.finditer(home):
    p = m.group(1)
    if p not in seen:
        seen.add(p)
        lvl1.append(p)
print("1. szint (homepage-nav): %d kategoria" % len(lvl1))

lvl2 = {}
pages = {}
for i, path in enumerate(lvl1):
    try:
        page = http_get(BASE + path)
    except Exception as e:  # noqa: BLE001
        print("  FETCH HIBA %s %s" % (path, str(e)[:60]))
        continue
    pages[path] = page
    for m in RE_CAT.finditer(page):
        p = m.group(1)
        if p not in seen:
            lvl2.setdefault(p, path)
    time.sleep(0.3)

print("2. szint: %d UJ kategoria-link a kategoria-oldalakrol" % len(lvl2))
print()
print("%-34s %-46s %s" % ("uj kategoria-kulcs", "URL", "hol talaltuk"))
found = {}
for p, src in sorted(lvl2.items()):
    k = key_of(p)
    if k in MISS:
        found[k] = p
    print("%-34s %-46s %s%s" % (k, p, src, "   <== HIANYZO!" if k in MISS else ""))

print()
print("=" * 92)
print("A 16 HIANYZOBOL a 2. szinten eloerult: %d" % len(found))
print("=" * 92)
for k, nev in MISS.items():
    print("  %-30s %s" % (nev, found.get(k, "-- nincs kategoria-oldala --")))

# a megtalaltakon van-e szuro-link?
print()
for k, p in found.items():
    try:
        page = http_get(BASE + p)
    except Exception as e:  # noqa: BLE001
        print("%s: FETCH HIBA %s" % (k, str(e)[:60]))
        continue
    facets = {}
    for fm in RE_FACET.finditer(page):
        if fm.group(1) != p:
            continue
        facets.setdefault(fm.group(2), set()).add(fm.group(3))
    print("%s (%s): %d szuro-attributum -> %s"
          % (k, p, len(facets), {a: len(v) for a, v in facets.items()}))
    time.sleep(0.3)

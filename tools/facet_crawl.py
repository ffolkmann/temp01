"""m79b: webshop kategoria/szuro-terkep crawler -> JSON (facet_map_<cid>.json).

Cel: a chatbot zaro linkje LETEZO fasetta/SEO-szuro-oldalra mutathasson
(app/services/linkfacet.py olvassa). A homepage nav kategoria-linkjeibol
indul, minden kategoriaoldalrol a szuro-linkeket (attr:ertek) es a
darabszamukat gyujti az anchor-szovegbol ('Fekete 90'). Fail-safe: keves
kategoria vagy hiba -> nincs iras (a regi terkep marad). Uj webdoc-szeru
shopokra a SHOPS lista bovitesevel skalazik (usage_crawl minta).

Futtatas (a konteners /app/data bind-mountra ir):
    docker exec -i chatbot-api-prod python - < tools/facet_crawl.py
"""
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SHOPS = [
    {
        "client_id": "notebookstore",
        "base": "https://notebookstore.hu",
        "out": "/app/data/facet_map_notebookstore.json",
        "min_categories": 30,
    },
]

_RE_CAT = re.compile(r'href="(?:https?://[^"/]+)?((?:/[a-z0-9-]+)*/[a-z0-9-]+-c\d+)/?"')
# m80: marka-szuro linkek (URL: <kategoria>/<marka-slug>, attr nelkul) --
# a data-type="brand" li-horgony teszi egyertelmuve
_RE_BRAND = re.compile(
    r'data-type="brand" data-value="([a-z0-9-]+)">\s*<a href="[^"]*?((?:/[a-z0-9-]+)*/[a-z0-9-]+-c\d+)/[a-z0-9-]+"[^>]*>(?=(.{0,240}))',
    re.S,
)
_RE_FACET = re.compile(
    r'href="[^"]*?((?:/[a-z0-9-]+)*/[a-z0-9-]+-c\d+)/([a-z0-9-]+):([a-z0-9.\-]+)"[^>]*>(?=(.{0,240}))',
    re.S,
)


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def parse_count(ctx):
    """Az anchor 'Cimke N' alaku; a darabszam kulon tagben (pl. span) is lehet."""
    part = ctx.split("</a>")[0]
    txt = " ".join(re.sub(r"<[^>]+>", " ", part).split())
    m = re.search(r"(\d+)\s*$", txt)
    return int(m.group(1)) if m else 0


def crawl_shop(shop):
    base = shop["base"]
    html = http_get(base + "/")
    cats = []
    seen = set()
    for m in _RE_CAT.finditer(html):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            cats.append(path)
    print("kategoriak a nav-bol:", len(cats))
    out = {}
    for path in cats:
        slug_nosuffix = re.sub(r"-c\d+$", "", path.rsplit("/", 1)[-1])
        try:
            page = http_get(base + path)
        except Exception as e:  # noqa: BLE001
            print("  FETCH HIBA", path, str(e)[:80])
            continue
        facets = {}
        for fm in _RE_FACET.finditer(page):
            if fm.group(1) != path:
                continue  # mas kategoriara mutato szuro-link
            attr, val = fm.group(2), fm.group(3)
            facets.setdefault(attr, {})[val] = parse_count(fm.group(4))
        for bm in _RE_BRAND.finditer(page):
            if bm.group(2) != path:
                continue
            facets.setdefault("marka", {})[bm.group(1)] = parse_count(bm.group(3))
        out[slug_nosuffix] = {"url": path, "facets": facets}
        time.sleep(0.35)
    return out


def main():
    for shop in SHOPS:
        try:
            cats = crawl_shop(shop)
        except Exception as e:  # noqa: BLE001
            print("SHOP HIBA, kihagyva:", shop["client_id"], str(e)[:100])
            continue
        n_attr = sum(len(v["facets"]) for v in cats.values())
        print("shop:", shop["client_id"], "kategoriak:", len(cats), "facet-attr:", n_attr)
        if len(cats) < shop["min_categories"]:
            print("FAIL-SAFE: tul keves kategoria, nincs iras")
            continue
        data = {
            "client_id": shop["client_id"],
            "generated_at": int(time.time()),
            "categories": cats,
        }
        outp = shop["out"]
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        tmp = outp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True)
        os.replace(tmp, outp)
        print("irva:", outp)


if __name__ == "__main__":
    sys.exit(main())

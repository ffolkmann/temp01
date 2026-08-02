"""m76: webshop szuro-attributum crawler -> qdrant payload cimkek.

A bolt "Felhasznalas jellege" szurojenek listaoldalait bejarva url->cimke
terkepet epit, es a qdrant termek-pontok payloadjaba irja (usage: [..]),
UJRA-EMBEDDING NELKUL. Fail-safe: ha barmelyik ertek crawl-ja hibas/ures,
a regi cimkek maradnak (nincs torles).
"""
import json
import re
import sys
import time
import urllib.request

QDRANT = "http://qdrant:6333"
COLLECTION = "cx_chatbot_v2"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SHOPS = [
    {
        "client_id": "notebookstore",
        "base": "https://notebookstore.hu",
        "category": "/laptop-notebook/uj-notebook-c100",
        "attr": "felhasznalas-jellege",
        "max_pages": 80,
    },
]


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def qdrant_post(path, body):
    req = urllib.request.Request(
        QDRANT + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def ensure_index():
    req = urllib.request.Request(
        QDRANT + "/collections/%s/index" % COLLECTION,
        data=json.dumps({"field_name": "usage", "field_schema": "keyword"}).encode(),
        method="PUT", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print("usage index: created")
    except Exception as e:  # mar letezik -> ok
        print("usage index: exists/skip (%s)" % str(e)[:60])


def discover_values(shop):
    html = http_get(shop["base"] + shop["category"])
    vals = sorted(set(re.findall(r'%s:([a-z0-9-]+)"' % re.escape(shop["attr"]), html)))
    print("ertekek:", vals)
    return vals


def crawl_value(shop, val):
    urls = set()
    p = 1
    pat = re.compile(r'href="(%s/[a-z0-9-]+-p\d+)"' % re.escape(shop["base"]))
    while p <= shop["max_pages"]:
        page_url = "%s%s/%s:%s/?p=%d" % (shop["base"], shop["category"], shop["attr"], val, p)
        try:
            html = http_get(page_url)
        except Exception as e:
            print("  FETCH HIBA %s p%d: %s" % (val, p, str(e)[:80]))
            break
        found = set(m for m in pat.findall(html))
        new = found - urls
        if not new:
            break
        urls |= new
        p += 1
        time.sleep(0.4)
    print("  %s: %d termek (%d oldal)" % (val, len(urls), p - 1))
    return urls


def main():
    ensure_index()
    for shop in SHOPS:
        cid = shop["client_id"]
        print("== shop:", cid)
        try:
            values = discover_values(shop)
        except Exception as e:
            print("  DISCOVER HIBA, shop kihagyva:", str(e)[:100])
            continue
        if not values:
            print("  nincs ertek, shop kihagyva")
            continue
        vmap = {}
        ok = True
        for val in values:
            urls = crawl_value(shop, val)
            if not urls:
                ok = False
            vmap[val] = urls
        if not ok:
            print("  FAIL-SAFE: volt ures ertek -> regi cimkek maradnak, nincs iras")
            continue
        url_map = {}
        for val, urls in vmap.items():
            for u in urls:
                url_map.setdefault(u, []).append(val)
        # friss allapot: eloszor a regi usage-kulcs torlese a tenant pontjairol
        qdrant_post("/collections/%s/points/payload/delete" % COLLECTION, {
            "keys": ["usage"],
            "filter": {"must": [{"key": "client_id", "match": {"value": cid}}]},
            "wait": True,
        })
        n_ok = 0
        for u, vals in url_map.items():
            try:
                qdrant_post("/collections/%s/points/payload" % COLLECTION, {
                    "payload": {"usage": sorted(vals)},
                    "filter": {"must": [
                        {"key": "client_id", "match": {"value": cid}},
                        {"key": "url", "match": {"value": u}},
                    ]},
                    "wait": False,
                })
                n_ok += 1
            except Exception as e:
                print("  SET HIBA %s: %s" % (u[-40:], str(e)[:60]))
        print("  payload irva: %d/%d url" % (n_ok, len(url_map)))
    print("KESZ")


if __name__ == "__main__":
    sys.exit(main())

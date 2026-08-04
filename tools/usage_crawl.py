"""m76/m81: webshop szuro-attributum crawler -> qdrant payload cimkek.

A bolt szuro-listaoldalait bejarva url->cimke terkepet epit, es a qdrant
termek-pontok payloadjaba irja, UJRA-EMBEDDING NELKUL. Fail-safe: ha
barmelyik ertek crawl-ja hibas/ures, az adott JOB cimkei valtozatlanok
maradnak (nincs torles, nincs iras).

JOBS bejegyzesek:
  attr        - a shop facet-attributuma (URL-ben: <kategoria>/<attr>:<ertek>)
  payload_key - a qdrant payload kulcs (usage / p_kijelzo)
  kind        - "keyword": ertekek listaja cimkekent
                "int": az ertek szamma alakitva (kijelzo-meret 173 = 17.3"),
                       igy range-szures (gte/lte) is megy ra

m81: a kijelzo-meret JOB azert kellett, mert a meret eddig CSAK link-oldali
kulcs volt -- a pool szuretlen maradt, es a bot olyan gepet is ajanlhatott,
ami a bolt meret-szurojeben nincs benne (elo hiba: 221 990-es Aspire Go 17
a shop-szuro szerinti 259 900-as Lenovo V17 helyett).
"""
import json
import re
import sys
import time
import urllib.request

QDRANT = "http://qdrant:6333"
COLLECTION = "cx_chatbot_v2"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
JOBS = [
    {
        "client_id": "notebookstore",
        "base": "https://notebookstore.hu",
        "category": "/laptop-notebook/uj-notebook-c100",
        "attr": "felhasznalas-jellege",
        "payload_key": "usage",
        "kind": "keyword",
        "max_pages": 80,
    },
    {
        "client_id": "notebookstore",
        "base": "https://notebookstore.hu",
        "category": "/laptop-notebook/uj-notebook-c100",
        "attr": "kijelzo-meret",
        "payload_key": "p_kijelzo",
        "kind": "int",
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


def ensure_index(key, kind):
    schema = "integer" if kind == "int" else "keyword"
    req = urllib.request.Request(
        QDRANT + "/collections/%s/index" % COLLECTION,
        data=json.dumps({"field_name": key, "field_schema": schema}).encode(),
        method="PUT", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print("%s index (%s): created" % (key, schema))
    except Exception as e:  # mar letezik -> ok
        print("%s index (%s): exists/skip (%s)" % (key, schema, str(e)[:50]))


def discover_values(job):
    html = http_get(job["base"] + job["category"])
    vals = sorted(set(re.findall(r'%s:([a-z0-9-]+)"' % re.escape(job["attr"]), html)))
    print("  ertekek:", vals)
    return vals


def crawl_value(job, val):
    urls = set()
    p = 1
    pat = re.compile(r'href="(%s/[a-z0-9-]+-p\d+)"' % re.escape(job["base"]))
    while p <= job["max_pages"]:
        page_url = "%s%s/%s:%s/?p=%d" % (job["base"], job["category"], job["attr"], val, p)
        try:
            html = http_get(page_url)
        except Exception as e:
            print("    FETCH HIBA %s p%d: %s" % (val, p, str(e)[:80]))
            break
        found = set(pat.findall(html))
        new = found - urls
        if not new:
            break
        urls |= new
        p += 1
        time.sleep(0.4)
    print("    %s: %d termek (%d oldal)" % (val, len(urls), p - 1))
    return urls


def payload_value(job, vals):
    """A payloadba irando ertek a JOB tipusa szerint."""
    if job["kind"] == "int":
        nums = []
        for v in vals:
            try:
                nums.append(int(v))
            except (TypeError, ValueError):
                pass
        if not nums:
            return None
        return min(nums)  # egy termek egy meret; tobb talalatnal a legkisebb
    return sorted(vals)


def main():
    for job in JOBS:
        cid, key = job["client_id"], job["payload_key"]
        print("== job: %s / %s -> %s" % (cid, job["attr"], key))
        ensure_index(key, job["kind"])
        try:
            values = discover_values(job)
        except Exception as e:
            print("  DISCOVER HIBA, job kihagyva:", str(e)[:100])
            continue
        if not values:
            print("  nincs ertek, job kihagyva")
            continue
        vmap = {}
        ok = True
        for val in values:
            urls = crawl_value(job, val)
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
        # friss allapot: eloszor a regi kulcs torlese a tenant pontjairol
        qdrant_post("/collections/%s/points/payload/delete" % COLLECTION, {
            "keys": [key],
            "filter": {"must": [{"key": "client_id", "match": {"value": cid}}]},
            "wait": True,
        })
        n_ok = 0
        for u, vals in url_map.items():
            pv = payload_value(job, vals)
            if pv is None:
                continue
            try:
                qdrant_post("/collections/%s/points/payload" % COLLECTION, {
                    "payload": {key: pv},
                    "filter": {"must": [
                        {"key": "client_id", "match": {"value": cid}},
                        {"key": "url", "match": {"value": u}},
                    ]},
                    "wait": False,
                })
                n_ok += 1
            except Exception as e:
                print("    SET HIBA %s: %s" % (u[-40:], str(e)[:60]))
        print("  payload irva: %d/%d url" % (n_ok, len(url_map)))
    print("KESZ")


if __name__ == "__main__":
    sys.exit(main())

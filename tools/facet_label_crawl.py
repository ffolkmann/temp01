"""m82a: generikus facet-cimke crawl -- "a bolt szuroje = a bot szuroje".

A data/facet_map_<client>.json alapjan minden kategoria x attributum x ertek
listaoldalat bejarja, es a talalt termek-URL-ekre EGYETLEN `facets` keyword
listat ir a Qdrant payloadba (pl. ["marka:asus", "kijelzo-meret:173",
"felhasznalas-jellege:uzleti"]). Ujra-embedding NINCS.

Miert egy kulcs: attributumonkent kulon payload-kulcs seman-robbanast es
index-robbanast okozna (152 kategoria-attributum par, 691 ertek). Egy
`facets` keyword lista + egy index eleg a match ANY szuresekhez.
Szamszeru attributumok emellett p_<attr> integer mezot is kapnak
(m81 p_kijelzo mintaja), hogy a range (gte/lte) szures is menjen.

Fail-safe:
  - ertek-crawl 0 talalatot ad, holott a terkep szerint van termek ->
    az ADOTT kategoria+attributum teljesen kimarad (nincs fel-cimkezes)
  - ha a hibas jobok aranya > FAIL_RATIO, egyaltalan nincs iras
  - reszleges futasnal (--cat) nincs kulcs-torles, csak merge-jellegu iras

Futtatas (csak a konteneren belulrol, a qdrant a compose-halon el):
  docker exec -i chatbot-api-prod python - < tools/facet_label_crawl.py
  docker exec -i chatbot-api-prod python - < tools/facet_label_crawl.py -- --cat=uj-notebook
  docker exec -i chatbot-api-prod python - < tools/facet_label_crawl.py -- --dry --cat=monitor
"""
import json
import re
import sys
import time
import urllib.request

QDRANT = "http://qdrant:6333"
COLLECTION = "cx_chatbot_v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SHOPS = [
    {
        "client_id": "notebookstore",
        "base": "https://notebookstore.hu",
        "map": "/app/data/facet_map_notebookstore.json",
    },
]

# szamszeru attributumok -> integer payload kulcs (range-szureshez)
INT_ATTRS = {"kijelzo-meret": "p_kijelzo"}
# nem cimkezendo attributumok
SKIP_ATTRS = set()

MAX_PAGES = 80
SLEEP = 0.4
BATCH = 250
FAIL_RATIO = 0.05


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def qdrant_post(path, body, timeout=60):
    req = urllib.request.Request(
        QDRANT + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())


def ensure_index(key, schema):
    req = urllib.request.Request(
        QDRANT + "/collections/%s/index" % COLLECTION,
        data=json.dumps({"field_name": key, "field_schema": schema}).encode(),
        method="PUT", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print("index %s (%s): letrehozva" % (key, schema))
    except Exception as e:  # noqa: BLE001 -- mar letezik -> ok
        print("index %s (%s): letezik/skip (%s)" % (key, schema, str(e)[:40]))


def facet_path(base, cat_url, attr, val):
    """m80: a marka-szuro URL-je <kategoria>/<marka-slug>, attr-prefix nelkul."""
    if attr == "marka":
        return "%s%s/%s" % (base, cat_url, val)
    return "%s%s/%s:%s" % (base, cat_url, attr, val)


def crawl_value(base, cat_url, attr, val):
    urls = set()
    pat = re.compile(r'href="(%s/[a-z0-9-]+-p\d+)"' % re.escape(base))
    root = facet_path(base, cat_url, attr, val)
    p = 1
    while p <= MAX_PAGES:
        try:
            html = http_get("%s/?p=%d" % (root, p))
        except Exception as e:  # noqa: BLE001
            print("    FETCH HIBA %s:%s p%d: %s" % (attr, val, p, str(e)[:70]))
            return set()
        found = set(pat.findall(html))
        new = found - urls
        if not new:
            break
        urls |= new
        p += 1
        time.sleep(SLEEP)
    return urls


def parse_args(argv):
    opts = {"cats": [], "client": None, "dry": False, "verify": True}
    for a in argv:
        if a.startswith("--cat="):
            opts["cats"] = [x for x in a.split("=", 1)[1].split(",") if x]
        elif a.startswith("--client="):
            opts["client"] = a.split("=", 1)[1]
        elif a == "--dry":
            opts["dry"] = True
        elif a == "--no-verify":
            opts["verify"] = False
    return opts


def write_batch(cid, url_payload):
    """Qdrant batch update; ha a batch-vegpont nem megy, url-enkenti fallback."""
    def op(u, payload):
        return {"set_payload": {"payload": payload, "filter": {"must": [
            {"key": "client_id", "match": {"value": cid}},
            {"key": "url", "match": {"value": u}}]}}}

    items = list(url_payload.items())
    done = 0
    use_batch = True
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        if use_batch:
            try:
                qdrant_post("/collections/%s/points/batch?wait=false" % COLLECTION,
                            {"operations": [op(u, p) for u, p in chunk]}, timeout=120)
                done += len(chunk)
                continue
            except Exception as e:  # noqa: BLE001
                print("  batch vegpont nem hasznalhato (%s) -> url-enkenti iras"
                      % str(e)[:70])
                use_batch = False
        for u, p in chunk:
            try:
                qdrant_post("/collections/%s/points/payload" % COLLECTION,
                            {"payload": p, "filter": {"must": [
                                {"key": "client_id", "match": {"value": cid}},
                                {"key": "url", "match": {"value": u}}]},
                             "wait": False})
                done += 1
            except Exception as e:  # noqa: BLE001
                print("    SET HIBA %s: %s" % (u[-40:], str(e)[:50]))
    return done


def count_tag(cid, tag):
    body = {"filter": {"must": [
        {"key": "client_id", "match": {"value": cid}},
        {"key": "facets", "match": {"value": tag}}]}, "exact": True}
    return qdrant_post("/collections/%s/points/count" % COLLECTION, body)["result"]["count"]


def run_shop(shop, opts):
    cid, base = shop["client_id"], shop["base"]
    try:
        with open(shop["map"], encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        print("MAP HIBA (%s): %s" % (cid, str(e)[:90]))
        return
    cats = data.get("categories") or {}
    partial = bool(opts["cats"])
    if partial:
        cats = dict((k, v) for k, v in cats.items() if k in opts["cats"])
    print("== %s: %d kategoria (terkep: %s)"
          % (cid, len(cats), data.get("generated_at")))
    if not cats:
        print("  nincs kategoria, kihagyva")
        return

    url_facets, url_ints, tag_urls = {}, {}, {}
    rows, total, failed = [], 0, 0
    t0 = time.time()
    for slug in sorted(cats):
        cat_url = (cats[slug] or {}).get("url")
        facets = (cats[slug] or {}).get("facets") or {}
        if not cat_url or not facets:
            continue
        print("-- %s (%s) %d attr" % (slug, cat_url, len(facets)))
        for attr in sorted(facets):
            if attr in SKIP_ATTRS:
                continue
            vals, ok, got = facets[attr], True, {}
            for val in sorted(vals):
                total += 1
                urls = crawl_value(base, cat_url, attr, val)
                exp = vals[val] or 0
                rows.append((slug, attr, val, exp, len(urls)))
                if not urls and exp:
                    failed += 1
                    ok = False
                got[val] = urls
            n = sum(len(v) for v in got.values())
            if not ok:
                print("   %s: FAIL-SAFE kihagyva (volt ures ertek)" % attr)
                continue
            print("   %s: %d ertek, %d url" % (attr, len(got), n))
            for val, urls in got.items():
                tag = "%s:%s" % (attr, val)
                tag_urls.setdefault(tag, set()).update(urls)
                for u in urls:
                    url_facets.setdefault(u, set()).add(tag)
                    if attr in INT_ATTRS:
                        try:
                            iv = int(val)
                        except (TypeError, ValueError):
                            continue
                        url_ints.setdefault(u, {}).setdefault(
                            INT_ATTRS[attr], []).append(iv)

    el = time.time() - t0
    print("\nCRAWL KESZ: %d job, %d hiba, %d url, %.1f perc"
          % (total, failed, len(url_facets), el / 60.0))
    print("ELTERESEK (terkep vs crawl, csak ahol nem egyezik):")
    diff = [r for r in rows if r[3] != r[4]]
    for r in diff[:40]:
        print("  %s / %s:%s  terkep=%d crawl=%d" % r)
    print("  osszesen %d elteres / %d ertek" % (len(diff), len(rows)))

    if opts["dry"]:
        print("DRY: nincs iras")
        return
    if total and failed > FAIL_RATIO * total:
        print("FAIL-SAFE: hibaarany %.1f%% > %.0f%% -> NINCS IRAS"
              % (100.0 * failed / total, 100 * FAIL_RATIO))
        return
    if not url_facets:
        print("nincs cimke, nincs iras")
        return

    ensure_index("facets", "keyword")
    for k in sorted(set(INT_ATTRS.values())):
        ensure_index(k, "integer")

    if not partial:
        qdrant_post("/collections/%s/points/payload/delete" % COLLECTION, {
            "keys": ["facets"],
            "filter": {"must": [{"key": "client_id", "match": {"value": cid}}]},
            "wait": True,
        })
        print("regi facets kulcs torolve (teljes futas)")
    else:
        print("reszleges futas (--cat): nincs kulcs-torles")

    payloads = {}
    for u, tags in url_facets.items():
        p = {"facets": sorted(tags)}
        for k, nums in (url_ints.get(u) or {}).items():
            if nums:
                p[k] = min(nums)
        payloads[u] = p
    done = write_batch(cid, payloads)
    print("payload irva: %d/%d url" % (done, len(payloads)))

    if not opts["verify"]:
        return
    time.sleep(3)
    print("\nELLENORZES (qdrant count vs crawl, cimkenkent GLOBALISAN):")
    bad = 0
    for tag in sorted(tag_urls):
        n = len(tag_urls[tag])
        if not n:
            continue
        try:
            c = count_tag(cid, tag)
        except Exception as e:  # noqa: BLE001
            print("  COUNT HIBA %s: %s" % (tag, str(e)[:50]))
            continue
        if c != n:
            bad += 1
            if bad <= 25:
                print("  %s  crawl=%d qdrant=%d" % (tag, n, c))
    print("  eltero cimke: %d / %d" % (bad, len(tag_urls)))


def main():
    opts = parse_args(sys.argv[1:])
    for shop in SHOPS:
        if opts["client"] and shop["client_id"] != opts["client"]:
            continue
        run_shop(shop, opts)
    print("KESZ")


if __name__ == "__main__":
    sys.exit(main())

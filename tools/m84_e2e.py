"""m84 ELES E2E: a bot altal MEGNEVEZETT termekek tenyleg kaphatok-e?

Bizonyitek nem a jol hangzo valasz: a valaszbol kiszedjuk a termek-URL-eket, es
a Qdrantbol lekerdezzuk az `available` mezojuket. A kivalasztott esetek azok,
ahol az elomeres (tools/m82i_avail_ctx.py) MIND-KIFUTO kontextust mert.

A konteneren belul fut (chat: belso 127.0.0.1:8000, Qdrant: qdrant:6333):
  docker exec -i chatbot-api-prod python - < tools/m84_e2e.py
"""
import json
import re
import time
import urllib.error
import urllib.request

CHAT = "http://127.0.0.1:8000/chat"
Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
SID = "m84-%d" % int(time.time())

CASES = [
    ("kellegyszerszam", "bontokalapács benzines", "elomeres: 8 termek / 0 kaphato"),
    ("kellegyszerszam", "Ryobi akkus fúrót keresek", "elomeres: 8 / 2"),
    ("4mfrigo", "1/2 col 3/8 col szűkítőt keresek", "elomeres: 8 / 4"),
    ("fishingoutlet", "Esetleg pellet?", "elomeres: 8 / 0"),
    ("notebookstore", "Van MSI laptopotok?", "KONTROLL (webdoc available, nem valtozott)"),
    ("teslashop", "Van üléshuzatotok?", "KONTROLL (Sellvio: nincs keszlet-adat)"),
]


def post(url, body, timeout=120, qdrant=False):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", "User-Agent": "cx-e2e/m84"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def avail_of(client_id, urls):
    """url -> available (a Qdrant payloadbol), csak a talalt URL-ekre."""
    out = {}
    for u in urls:
        body = {"filter": {"must": [{"key": "client_id", "match": {"value": client_id}},
                                    {"key": "type", "match": {"value": "product"}},
                                    {"key": "url", "match": {"value": u}}]},
                "limit": 1, "with_payload": ["available", "stock", "name"],
                "with_vector": False}
        try:
            pts = post("%s/collections/%s/points/scroll" % (Q, COLL), body)["result"]["points"]
        except Exception:  # noqa: BLE001
            continue
        if pts:
            p = pts[0].get("payload") or {}
            out[u] = (p.get("available"), p.get("stock"), str(p.get("name"))[:48])
    return out


RE_URL = re.compile(r"https?://[^\s\)\]\"'<>]+")

rows = []
for i, (cid, msg, note) in enumerate(CASES, 1):
    t0 = time.time()
    try:
        data = post(CHAT, {"client_id": cid, "session_id": "%s-%d" % (SID, i),
                           "message": msg, "history": []})
        reply = data.get("reply") or ""
        err = None
    except urllib.error.HTTPError as e:
        reply, err = "", "HTTP %s: %s" % (e.code, e.read()[:200])
    except Exception as e:  # noqa: BLE001
        reply, err = "", "%s: %s" % (type(e).__name__, e)
    dt = time.time() - t0

    print("=" * 96)
    print("[%d/%d] %-16s %.1f s   (%s)" % (i, len(CASES), cid, dt, note))
    print("  K: %s" % msg)
    if err:
        print("  HIBA: %s" % err)
        rows.append((cid, msg, 0, 0, 0))
        continue
    print("  V: %s" % reply[:260].replace("\n", " "))

    urls = []
    for u in RE_URL.findall(reply):
        u = u.rstrip(".,;:")
        if u not in urls:
            urls.append(u)
    got = avail_of(cid, urls)
    n_av = sum(1 for v in got.values() if v[0] is True)
    n_oos = sum(1 for v in got.values() if v[0] is False)
    n_none = sum(1 for v in got.values() if v[0] is None)
    print("  megnevezett termek: %d (ebbol Qdrantban azonositva: %d)" % (len(urls), len(got)))
    for u, (av, st, nm) in got.items():
        print("      %-9s stock=%-5s %s" % ("KAPHATO" if av is True else
                                            ("KIFUTO" if av is False else "nincs adat"),
                                            st, nm))
    rows.append((cid, msg, n_av, n_oos, n_none))
    time.sleep(1)

print()
print("=" * 96)
print("VERDIKT — a bot altal megnevezett termekek keszlet-statusza")
ok = bad = 0
for cid, msg, n_av, n_oos, n_none in rows:
    if cid == "teslashop":
        print("  INFO  %-16s %-38s nincs keszlet-adat (Sellvio) -> nem ertekelheto" % (cid, msg[:38]))
        continue
    if n_oos == 0 and (n_av > 0 or n_none > 0):
        print("  OK    %-16s %-38s kaphato=%d kifuto=0" % (cid, msg[:38], n_av))
        ok += 1
    elif n_av == 0 and n_oos == 0:
        print("  INFO  %-16s %-38s nem nevezett meg termeket" % (cid, msg[:38]))
    else:
        print("  BUKO  %-16s %-38s kaphato=%d KIFUTO=%d" % (cid, msg[:38], n_av, n_oos))
        bad += 1
print("  ---- OK: %d | BUKO: %d" % (ok, bad))

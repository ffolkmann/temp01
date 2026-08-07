"""m86 FP-DIAG: mely Shoprenter-termekekbol nyer ki kategoriat a zarojeles ag, es miert.

A dry-run 24 kinyerest mutatott a 4 SR tenanton (4mfrigo 4, copygo 9, fishingoutlet 11),
holott az SR builder SEHOL nem ir kategoriat -> ezek FALSE POSITIVE-ok. A kapu-ertek
igy keszlet/marketing-szoveg lenne, es a m86 kapu ezekre a torzs-ertekekre tuzelne.

  docker run --rm -i --network container:chatbot-api-prod \\
    -v "$PWD/app:/app/app" -w /app chatbot-prod-api:latest python - < tools/m86_fpdiag.py
"""
import json
import re
import sys
import urllib.request

sys.path.insert(0, "/app")
from app.services.paramextract import extract_params, _RE_CAT_PAREN  # noqa: E402

Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
SR = ["4mfrigo", "copygo", "ecowindoor", "fishingoutlet"]
CHECK_TAGS = ["kellegyszerszam", "teslashop", "nagyonallatshop", "smartzilla"]


def post(path, body, timeout=300):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def scroll(client, keys):
    off = None
    while True:
        body = {"limit": 1000, "with_payload": keys, "with_vector": False,
                "filter": {"must": [{"key": "client_id", "match": {"value": client}},
                                    {"key": "type", "match": {"value": "product"}}]}}
        if off is not None:
            body["offset"] = off
        res = post("/collections/%s/points/scroll" % COLL, body)["result"]
        pts = res.get("points") or []
        for p in pts:
            yield p
        off = res.get("next_page_offset")
        if not off or not pts:
            return


print("=== SHOPRENTER FALSE POSITIVE-ok (a teljes text a dontes megertesehez) ===")
for client in SR:
    for p in scroll(client, ["text", "name"]):
        t = (p.get("payload") or {}).get("text") or ""
        got = extract_params("", t)
        if not got.get("category"):
            continue
        m = _RE_CAT_PAREN.search(t)
        print("\n[%s] cat=%r" % (client, got["category"]))
        print("   tags = %r" % (got.get("cat_tags"),))
        print("   ILLESZKEDO RESZ: ...%s..." % t[max(0, m.start() - 70):m.end() + 20].replace("\n", " "))

print("\n\n=== MINTA cat_tags a cel-tenantokon (elso 6 termek) ===")
for client in CHECK_TAGS:
    print("\n--- %s ---" % client)
    k = 0
    for p in scroll(client, ["text", "name"]):
        got = extract_params("", (p.get("payload") or {}).get("text") or "")
        if not got.get("category"):
            continue
        print("   %-46s -> %r" % (((p.get("payload") or {}).get("name") or "")[:46], got["cat_tags"]))
        k += 1
        if k >= 6:
            break

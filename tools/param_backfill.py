"""m79c: parameter-payload backfill meglevo pontokra (set_payload MERGE, ujra-embedding nelkul).

Futtatas (a repo gyokerebol, az UJ image-u kontenerrel):
    docker exec -i chatbot-api-prod python - <client_id> < tools/param_backfill.py
"""
import json
import sys
import urllib.request

sys.path.insert(0, "/app")
from app.services.paramextract import extract_params  # noqa: E402

BASE = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
cid = sys.argv[1] if len(sys.argv) > 1 else "notebookstore"


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req))


ops = []
updated = 0
scanned = 0
stats = {}


def flush():
    global updated, ops
    if not ops:
        return
    post(f"/collections/{COLL}/points/batch?wait=true",
         {"operations": [{"set_payload": {"payload": pl, "points": [pid]}} for pl, pid in ops]})
    updated += len(ops)
    ops = []


offset = None
while True:
    body = {"limit": 500, "with_payload": ["name", "text", "type"],
            "filter": {"must": [{"key": "client_id", "match": {"value": cid}}]}}
    if offset is not None:
        body["offset"] = offset
    r = post(f"/collections/{COLL}/points/scroll", body)
    pts = r["result"]["points"]
    scanned += len(pts)
    for p in pts:
        pl = p.get("payload") or {}
        if pl.get("type") != "product":
            continue
        ex = extract_params(pl.get("name") or "", pl.get("text") or "")
        if not ex:
            continue
        for k in ex:
            stats[k] = stats.get(k, 0) + 1
        ops.append((ex, p["id"]))
        if len(ops) >= 100:
            flush()
    offset = r["result"].get("next_page_offset")
    if offset is None:
        break
flush()
print("client:", cid, "scanned:", scanned, "updated:", updated, "stats:", stats)

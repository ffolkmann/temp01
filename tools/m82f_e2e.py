"""m82f éles E2E — a szülő-szintű kategória-feloldás igazolása a prod API-n.

Bizonyíték: a `m82b facet filter … cat='Laptop, Notebook > ÚJ Notebook'` log-sor
és az, hogy a válasz NOTEBOOKOKAT ad (nem RAM-modulokat).

Futtatás a VPS-ről (a hoston):  python3 tools/m82f_e2e.py
"""
import json
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8095/chat"
CLIENT = "notebookstore"
SID = "m82f-%d" % int(time.time())

CASES = [
    ("SZULO-FELOLDAS", "Van 32 GB memóriával laptopotok?",
     "NOTEBOOKOK 32 GB RAM-mal; log: cat='… ÚJ Notebook' ['memoria-meret:32gb'] "
     "(előtte RAM-modulokat adott)"),
    ("SZULO-FELOLDAS2", "Milyen laptopokat ajánlotok?",
     "notebookok, a kapu az ÚJ Notebook"),
    ("OSSZETETELI-JELZO", "Van laptop táskátok?",
     "TÁSKÁK (nem notebookok) — a 'laptop' itt összetételi jelző"),
    ("REGRESSZIO", "Milyen notebook hűtőt ajánlotok?",
     "notebook hűtő (a levél erősebb a szülőnél)"),
]


def ask(msg, sid):
    body = json.dumps({"client_id": CLIENT, "session_id": sid,
                       "message": msg, "history": []}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "cx-e2e/m82f"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8")), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, "HTTP %s: %s" % (e.code, e.read()[:300])
    except Exception as e:  # noqa: BLE001
        return None, time.time() - t0, "%s: %s" % (type(e).__name__, e)


for i, (tag, msg, expect) in enumerate(CASES, 1):
    sid = "%s-%d" % (SID, i)
    data, dt, err = ask(msg, sid)
    print("=" * 78)
    print("[%s] %s" % (tag, msg))
    print("  várt : %s" % expect)
    print("  sid  : %s | %.1f mp" % (sid, dt))
    if err:
        print("  HIBA : %s" % err)
        continue
    print("  válasz: %s" % str((data or {}).get("reply") or "")[:460].replace("\n", " "))
print("=" * 78)
print("SESSION-PREFIX: %s" % SID)

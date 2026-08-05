"""m82d éles E2E — a nem-szuperlatívusz facets-szűrés igazolása a prod API-n.

A bizonyíték a LOG-sor (`m82b facet filter ... mode=plain`), nem a válasz szövege:
a lézernyomtató-eset óta tudjuk, hogy a jól hangzó válasz nem igazolja a szűrő futását.

Futtatás a VPS-ről (a publikus domain hairpin miatt nem megy):
  python3 tools/m82d_e2e.py
"""
import json
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8095/chat"
CLIENT = "notebookstore"
SID = "m82d-%d" % int(time.time())

CASES = [
    # (címke, kérdés, mit várunk)
    ("PLAIN-1", "Gamer laptopot szeretnék venni, mit ajánlasz?",
     "mode=plain, felhasznalas-jellege:gamer"),
    ("PLAIN-2", "Milyen 4K monitorokat ajánlotok?",
     "mode=plain, felbontas:3840x2160"),
    ("PLAIN-3", "Keresek egy IPS paneles monitort",
     "mode=plain, panel-tipus:ips"),
    ("NEGATIV", "Mennyibe kerül a szállítás?",
     "NINCS facet filter sor, KB-válasz (DPD/MPL)"),
    ("SUPER",   "Melyik a legolcsóbb lézernyomtató?",
     "mode=super, nyomtatasi-technologia:lezer (m82c/4 regresszió)"),
]


def ask(msg, sid):
    body = json.dumps({
        "client_id": CLIENT,
        "session_id": sid,
        "message": msg,
        "history": [],
    }).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "cx-e2e/m82d"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data, time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, "HTTP %s: %s" % (e.code, e.read()[:400])
    except Exception as e:  # noqa: BLE001
        return None, time.time() - t0, "%s: %s" % (type(e).__name__, e)


for i, (tag, msg, expect) in enumerate(CASES, 1):
    sid = "%s-%d" % (SID, i)   # futásonként ÉS esetenként egyedi session
    data, dt, err = ask(msg, sid)
    print("=" * 78)
    print("[%s] %s" % (tag, msg))
    print("  várt : %s" % expect)
    print("  sid  : %s | %.1f mp" % (sid, dt))
    if err:
        print("  HIBA : %s" % err)
        continue
    reply = str((data or {}).get("reply") or "")
    if not reply:
        print("  !! nincs 'reply' kulcs, válasz-kulcsok: %s" % list((data or {}).keys()))
    print("  válasz: %s" % reply[:500].replace("\n", " "))
print("=" * 78)
print("SESSION-PREFIX: %s   (log-szűréshez)" % SID)

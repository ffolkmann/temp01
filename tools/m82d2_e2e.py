"""m82d/2 éles E2E — a 4 betűs toldalék és a "pro" szinonima igazolása a prod API-n.

A bizonyíték a LOG-sor (`m82b facet filter ... mode=plain`), nem a válasz szövege.

Futtatás a VPS-ről:  python3 tools/m82d2_e2e.py
"""
import json
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8095/chat"
CLIENT = "notebookstore"
SID = "m82d2-%d" % int(time.time())

CASES = [
    ("TOLDALEK", "Milyen lézernyomtatóitok vannak?",
     "mode=plain, nyomtatasi-technologia:lezer (+4 toldalék, m82d/2)"),
    ("SZINONIMA", "Windows 11 Pro-s laptopot keresek",
     "mode=plain, operacios-rendszer:windows-11-professional"),
    ("NEGATIV", "Professzionális tanácsot kérek, mit vegyek?",
     "NINCS operacios-rendszer címke (a 'pro' csak windows 11 után hat)"),
]


def ask(msg, sid):
    body = json.dumps({"client_id": CLIENT, "session_id": sid,
                       "message": msg, "history": []}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "cx-e2e/m82d2"})
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
    print("  válasz: %s" % str((data or {}).get("reply") or "")[:420].replace("\n", " "))
print("=" * 78)
print("SESSION-PREFIX: %s" % SID)

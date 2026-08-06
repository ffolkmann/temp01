"""m82e éles E2E — a jelzői (-s képzős) kategória-név nem viszi el a kaput.

A bizonyíték a LOG-sor (`m82b facet filter ... mode=plain|super`) és az, hogy a
válasz a kérdés FEJÉRŐL szól (notebook), nem a jelzőről (videokártya).

Futtatás a VPS-ről (a hoston):  python3 tools/m82e_e2e.py
"""
import json
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8095/chat"
CLIENT = "notebookstore"
SID = "m82e-%d" % int(time.time())

CASES = [
    ("JELZO-FIX", "Van NVIDIA videokártyás notebookotok?",
     "NOTEBOOKOK (nem videokártyák); log: mode=plain ['grafikus-vezerlo-gyarto:nvidia']"),
    ("JELZO-FIX2", "Van webkamerás monitorotok?",
     "MONITOROK (nem webkamerák); a kapu a Monitor kategória"),
    ("REGRESSZIO-SUPER", "Melyik a legolcsóbb lézernyomtató?",
     "mode=super, nyomtatasi-technologia:lezer -> Brother 33 090 Ft (m82c/4 sértetlen)"),
    ("REGRESSZIO-PLAIN", "Gamer laptopot szeretnék venni",
     "mode=plain, felhasznalas-jellege:gamer -> gamer notebookok (m82d sértetlen)"),
    ("NEGATIV-POLICY", "Mennyibe kerül a szállítás?",
     "NINCS facet-sor, helyes KB-válasz (m82d policy-kapu sértetlen)"),
]


def ask(msg, sid):
    body = json.dumps({"client_id": CLIENT, "session_id": sid,
                       "message": msg, "history": []}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "cx-e2e/m82e"})
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
    print("  válasz: %s" % str((data or {}).get("reply") or "")[:500].replace("\n", " "))
print("=" * 78)
print("SESSION-PREFIX: %s" % SID)

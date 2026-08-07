"""m87 ELES E2E: rendes kerdesekre NEM szabad tuzelnie az orsegnek.

A bizonyitek a `m87 langguard` log-sor HIANYA (a merve 0,27%-os tuzelesi arany miatt
normal forgalomban nem szabad megjelennie), plusz hogy a valaszok epek.

Futtatas a VPS-rol (a HOSTON):  python3 tools/m87_e2e.py
"""
import json
import subprocess
import time
import urllib.request

SID = "m87e2e-%d" % int(time.time())
CASES = [
    ("notebookstore", "Melyik a legolcs\u00f3bb rakt\u00e1ron l\u00e9v\u0151 notebook?"),
    ("notebookstore", "Milyen MSI laptopotok van?"),
    ("teslashop", "Van \u00fcl\u00e9shuzatotok?"),
    ("kellegyszerszam", "Akkus kis l\u00e1ncf\u0171r\u00e9sz"),
]

for i, (client, q) in enumerate(CASES):
    body = json.dumps({"client_id": client, "session_id": "%s-%d" % (SID, i),
                       "message": q, "history": []}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8095/chat", data=body,
        headers={"Content-Type": "application/json", "User-Agent": "cx-e2e/m87"})
    t0 = time.time()
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=120).read().decode("utf-8"))
        rep = (d.get("reply") or "").replace("\n", " ")
    except Exception as e:  # noqa: BLE001
        rep = "HIBA: %s" % e
    print("\n[%s] %s  (%.1f s)" % (client, q, time.time() - t0))
    print("   %s" % rep[:170])

out = subprocess.run(["docker", "logs", "chatbot-api-prod", "--since", "600s"],
                     capture_output=True, text=True)
lines = [ln for ln in (out.stdout + out.stderr).splitlines() if "m87 langguard" in ln]
print("\n\nm87 langguard log-sor az elmult 10 percben: %d  (a vart: 0)" % len(lines))
for ln in lines[:5]:
    print("   " + ln[:170])

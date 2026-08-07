"""m86 ELES E2E — a kategoria-kapu igazolasa a prod API-n.

Bizonyitek NEM a jol hangzo valasz, hanem a `m86 category gate: cat=... -> N hit`
log-sor MEGLETE (pozitiv esetek) ill. HIANYA (negativ esetek: policy-kerdes, es a
notebookstore, ahol a hatokor-kapu miatt a m82-es sav a gazda).

Futtatas a VPS-rol (a HOSTON):  python3 tools/m86_e2e.py
"""
import json
import subprocess
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8095/chat"
SID = "m86-%d" % int(time.time())

# (tag, client_id, uzenet, elvart kategoria-kulcsszo vagy None ha NEM szabad tuzelnie)
CASES = [
    ("TESLA-super", "teslashop", "Melyik a legolcs\u00f3bb rakt\u00e1ron l\u00e9v\u0151 telefontart\u00f3?", "Telefontart"),
    ("TESLA-plain", "teslashop", "Van \u00fcl\u00e9shuzatotok?", "\u00dcl\u00e9shuzat"),
    ("TESLA-napellenzo", "teslashop", "model s napellenz\u0151", "Napellenz"),
    ("KELL-lancfuresz", "kellegyszerszam", "Akkus kis l\u00e1ncf\u0171r\u00e9sz", "L\u00e1ncf\u0171r\u00e9sz"),
    ("KELL-FP-csavarhuzo", "kellegyszerszam", "Csavarh\u00faz\u00f3 k\u00e9szlet", "Csavar"),
    ("ALLAT-macskatap", "nagyonallatshop", "Melyik a legolcs\u00f3bb macskat\u00e1p egys\u00e9g\u00e1ron", "Macska"),
    ("ALLAT-nyul", "nagyonallatshop", "Ny\u00fal eles\u00e9get szeretn\u00e9k rendelni", "Ny\u00fal"),
    ("NEG-policy", "teslashop", "Mennyi a sz\u00e1ll\u00edt\u00e1si id\u0151?", None),
    ("NEG-notebookstore", "notebookstore", "Aj\u00e1nlj egy laptopot egyetemre, 400 ezerig.", None),
    ("NEG-shoprenter", "fishingoutlet", "Milyen s\u00e1tratok van?", None),
]


def ask(client, msg, sid):
    body = json.dumps({"client_id": client, "session_id": sid,
                       "message": msg, "history": []}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "cx-e2e/m86"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8")), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, "HTTP %s: %s" % (e.code, e.read().decode()[:160])
    except Exception as e:  # noqa: BLE001
        return None, time.time() - t0, "%s: %s" % (type(e).__name__, e)


def gate_lines(seconds):
    out = subprocess.run(
        ["docker", "logs", "chatbot-api-prod", "--since", "%ds" % seconds],
        capture_output=True, text=True).stderr or ""
    out2 = subprocess.run(
        ["docker", "logs", "chatbot-api-prod", "--since", "%ds" % seconds],
        capture_output=True, text=True).stdout or ""
    return [ln for ln in (out + out2).splitlines()
            if "m86 category gate" in ln or "m82b facet filter" in ln]


ok = bad = 0
for tag, client, msg, expect in CASES:
    d, dt, err = ask(client, msg, "%s-%s" % (SID, tag))
    lines = gate_lines(25)
    gate = [ln for ln in lines if "m86 category gate" in ln]
    gate_txt = gate[-1].split("m86 category gate")[-1].strip() if gate else ""
    if expect is None:
        good = not gate
    else:
        good = bool(gate) and expect.lower() in gate_txt.lower()
    ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
    print("\n[%s] %s  (%.1f s)  client=%s" % ("OK " if good else "!! ", tag, dt, client))
    print("   kerdes : %s" % msg)
    print("   elvart : %s" % (expect or "(NEM szabad tuzelnie)"))
    print("   kapu   : %s" % (gate_txt or "NINCS log-sor"))
    if err:
        print("   HIBA   : %s" % err)
    elif d:
        print("   valasz : %s" % (d.get("reply") or "")[:200].replace("\n", " "))

print("\n\nEREDMENY: %d/%d" % (ok, ok + bad))

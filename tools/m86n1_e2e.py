"""m86/1 ELES E2E — a szimmetrikus kategoria-illesztes igazolasa a prod API-n.

Bizonyitek NEM a jol hangzo valasz, hanem a LOG-SOR:
  - a m86-os tenantokon  `m86 category gate: cat=... -> N hit`
  - a notebookstore-on   `m82b facet filter [...] cat=...`  (ott a m82-es sav a gazda)

Ket iranyban merunk:
  (1) NYERESEG: a tobbes szamu kategorianev mostantol nyer a generikus rovid ellen
  (2) REGRESSZIO: a m82e / m82g / m82f esetek valtozatlanul allnak, es a rovid to
      (_CAT_STEM_MIN=6) NEM ad hamis feloldast a "kellene" tipusu szavakra

Futtatas a VPS-rol (a HOSTON):  python3 tools/m86n1_e2e.py
"""
import json
import subprocess
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8095/chat"
SID = "m86n1-%d" % int(time.time())

# (tag, client, uzenet, ELVART reszlet a kapu-sorban vagy None, TILTOTT reszlet vagy None)
CASES = [
    ("NYER-csavarhuzo", "kellegyszerszam",
     "Csavarh\u00faz\u00f3 k\u00e9szlet", "Csavarh\u00faz\u00f3k", None),
    ("NYER-sarokcsiszolo", "kellegyszerszam",
     "Melyik a legolcs\u00f3bb rakt\u00e1ron l\u00e9v\u0151 sarokcsiszol\u00f3?", "Sarokcsiszol\u00f3k", None),
    ("NYER-furoszar", "kellegyszerszam",
     "Sds max f\u00far\u00f3sz\u00e1rat keresek 20-25 \u00e1tm\u00e9r\u0151ben", "F\u00far\u00f3sz\u00e1r", None),
    ("NYER-macskaeledel", "nagyonallatshop",
     "Nedves macskaeledelt keresek olcs\u00f3n, nagy t\u00e9telben", "eledelek", "cat='Eledel'"),
    ("NYER-kutyaeledel", "nagyonallatshop",
     "mi a legjobb kutyaeledel egy 10 kil\u00f3s kuty\u00e1nak?", "eledelek", "cat='Eledel'"),
    ("REG-kellene", "kellegyszerszam",
     "Olyan hossz\u00fa csipesz kellene ami 6mm-es lyukba bef\u00e9r", None, "Kell\u00e9k"),
    ("REG-m82e-nvidia", "notebookstore",
     "Van NVIDIA videok\u00e1rty\u00e1s notebookotok?", "\u00daJ Notebook", None),
    ("REG-m82g-hatizsak", "notebookstore",
     "Milyen sz\u00fcrke h\u00e1tizs\u00e1kotok van?", "szin:szurke", None),
    ("REG-m82f-laptop", "notebookstore",
     "Van 32 GB mem\u00f3ri\u00e1val laptopotok?", "\u00daJ Notebook", None),
    ("NEG-policy", "teslashop", "Mennyi a sz\u00e1ll\u00edt\u00e1si id\u0151?", None, None),
]

MARKERS = ("m86 category gate", "m82b facet filter", "m82f category link")


def ask(client, msg, sid):
    body = json.dumps({"client_id": client, "session_id": sid,
                       "message": msg, "history": []}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "cx-e2e/m86n1"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8")), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, "HTTP %s: %s" % (e.code, e.read().decode()[:160])
    except Exception as e:  # noqa: BLE001
        return None, time.time() - t0, "%s: %s" % (type(e).__name__, e)


def gate_lines(seconds):
    p = subprocess.run(["docker", "logs", "chatbot-api-prod", "--since", "%ds" % seconds],
                       capture_output=True, text=True)
    blob = (p.stdout or "") + (p.stderr or "")
    return [ln for ln in blob.splitlines() if any(m in ln for m in MARKERS)]


ok = bad = 0
for tag, client, msg, expect, forbid in CASES:
    d, dt, err = ask(client, msg, "%s-%s" % (SID, tag))
    lines = gate_lines(25)
    txt = " || ".join(lines)
    good = True
    if expect is not None and expect.lower() not in txt.lower():
        good = False
    if expect is None and lines:
        good = False
    if forbid is not None and forbid.lower() in txt.lower():
        good = False
    ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
    print("\n[%s] %s  (%.1f s)  client=%s" % ("OK " if good else "!! ", tag, dt, client))
    print("   kerdes : %s" % msg)
    print("   elvart : %s%s" % (expect or "(NEM szabad tuzelnie)",
                                "  | tiltott: %s" % forbid if forbid else ""))
    print("   kapu   : %s" % (txt[-300:] if txt else "NINCS log-sor"))
    if err:
        print("   HIBA   : %s" % err)
    elif d:
        print("   valasz : %s" % (d.get("reply") or "")[:180].replace("\n", " "))

print("\n\nEREDMENY: %d/%d" % (ok, ok + bad))

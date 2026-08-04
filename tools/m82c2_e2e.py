"""m82c/2 E2E: kategoria-szandek a kerdesbol, az ELES chat-uton.

Futtatas (a VPS-en, deploy UTAN):
    docker exec -i chatbot-api-prod python - < tools/m82c2_e2e.py

Csak KIIR (nincs beegetett ar-assert): a valasz elso sorait, a felismert
minimum-arat es a zaro-linket. A permanens regresszio-kaput a
tools/onboarding_test.py adja.
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime

BASE = "http://127.0.0.1:8000"
CID = "notebookstore"
SIDP = datetime.now().strftime("%H%M%S") + "-m82c2-"


def chat(msg, sid):
    body = {"client_id": CID, "session_id": SIDP + sid, "message": msg}
    req = urllib.request.Request(BASE + "/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=150).read().decode()).get("reply", "")


def link(r):
    m = re.search(r"\]\((https?://[^)]+)\)\s*$", (r or "").strip())
    return m.group(1) if m else ""


CASES = [
    # (kerdes, mire figyelunk)
    ("Melyik a legolcsóbb gamer asztali számítógép?",
     "UJ: kategoria-szandek -> asztali gep (6 db), NEM notebook"),
    ("Melyik a legolcsóbb gamer laptop?",
     "REGRESSZIO: maradjon notebook (157 db)"),
    ("Melyik a legolcsóbb üzleti notebook?",
     "REGRESSZIO: uzleti notebook (643 db)"),
    ("legolcsóbb 32 GB memóriás laptop",
     "REGRESSZIO: 32gb memoria (211 db)"),
    ("Melyik a legolcsóbb üzleti asztali számítógép?",
     "kategoria felismerve, de nincs ra szuro-ertek -> szuretlen pool"),
]

for i, (q, note) in enumerate(CASES, 1):
    try:
        r = chat(q, "e2e-%d" % i)
    except Exception as e:  # noqa: BLE001
        print("%d. %s\n   HIBA: %r\n" % (i, q, e))
        continue
    body = re.sub(r"\[([^\]]*)\]\((https?://[^)]+)\)", r"\1", r).strip()
    prices = re.findall(r"\d[\d\u00a0 ]{4,}(?=\s*Ft)", r)
    print("%d. %s" % (i, q))
    print("   [%s]" % note)
    print("   arak a valaszban: %s" % (", ".join(p.strip() for p in prices[:4]) or "-"))
    print("   link: %s" % (link(r) or "-"))
    print("   valasz: %s" % body[:300].replace("\n", " "))
    print()
    sys.stdout.flush()
    time.sleep(2)

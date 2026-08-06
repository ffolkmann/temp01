"""m82h/3 éles E2E — a márkanév nélküli embed igazolása a prod API-n.

Bizonyíték: a `m82h3 brand-free embed` log-sor + a válaszban tényleg az
ALTÍPUS jelenik meg (sátor / szárazeledel / fúró), nem a márka bármely terméke.

Futtatás a VPS-ről:  python3 tools/m82h3_e2e.py
"""
import json
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8095/chat"
SID = "m82h3-%d" % int(time.time())

CASES = [
    ("CEL-sator", "fishingoutlet", "Milyen Delphin sátratok van?", ["sator"]),
    ("CEL-szaraz", "nagyonallatshop", "Whiskas száraz tápot kerestek?", ["szaraz"]),
    ("CEL-furo", "kellegyszerszam", "Ryobi akkus fúrót keresek", ["furo"]),
    ("KONTROLL-patron", "notebookstore", "Milyen HP tintapatronotok van?", ["tintapatron"]),
    ("KONTROLL-marka", "notebookstore", "Van MSI laptopotok?", ["msi"]),
]


def fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c))


def ask(client, msg, sid):
    body = json.dumps({"client_id": client, "session_id": sid,
                       "message": msg, "history": []}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "cx-e2e/m82h3"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8")), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, "HTTP %s: %s" % (e.code, e.read()[:200])
    except Exception as e:  # noqa: BLE001
        return None, time.time() - t0, "%s: %s" % (type(e).__name__, e)


res = []
for i, (tag, client, msg, words) in enumerate(CASES, 1):
    data, dt, err = ask(client, msg, "%s-%d" % (SID, i))
    reply = (data or {}).get("reply") or ""
    hit = sum(1 for w in words if w in fold(reply))
    print("=" * 92)
    print("[%d/%d] %-16s %-16s %.1f s | altipus a valaszban: %s"
          % (i, len(CASES), tag, client, dt, "IGEN" if hit else "NEM"))
    print("  K: %s" % msg)
    print("  V: %s" % (err or reply[:260].replace("\n", " ")))
    res.append((tag, bool(hit), err))
    time.sleep(1)

time.sleep(2)
log = subprocess.run(["docker", "logs", "chatbot-api-prod", "--since", "5m"],
                     capture_output=True, text=True)
lines = [l for l in (log.stdout + log.stderr).split("\n") if "m82h3 brand-free embed" in l]
print()
print("=" * 92)
print("LOG-BIZONYITEK (m82h3 brand-free embed):")
for l in lines:
    print("   " + l.strip()[-170:])

print()
print("VERDIKT")
ok = 0
for tag, hit, err in res:
    if err:
        print("  BUKO  %-16s API-hiba" % tag)
    elif hit:
        print("  OK    %-16s az altipus megjelent a valaszban" % tag)
        ok += 1
    else:
        print("  FIGYELEM %-13s az altipus NEM jelent meg" % tag)
print("  ---- %d/%d" % (ok, len(res)))

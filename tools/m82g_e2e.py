"""m82g éles E2E — a `szin` kivezetése + téma-kapu igazolása a prod API-n.

Bizonyíték nem a jól hangzó válasz, hanem a `m82b facet filter … ['szin:…'] mode=plain`
log-sor megléte (pozitív esetek) ill. HIÁNYA (negatív eset).

Futtatás a VPS-ről (a hoston):  python3 tools/m82g_e2e.py
"""
import json
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8095/chat"
CLIENT = "notebookstore"
SID = "m82g-%d" % int(time.time())

CASES = [
    ("UJ-NYEREMENY", "Van fekete filamentetek?",
     "FEKETE filamentek; log: ['szin:fekete'] mode=plain — eddig SEMMI nem szűrt a filamentre"),
    ("UJ-NYEREMENY2", "Milyen világoszöld filamentetek van?",
     "log: ['szin:vilagos-zold'] — 103 crawl-olt szín érhető el"),
    ("PARITAS", "Milyen szürke hátizsákotok van?",
     "SZÜRKE hátizsákok; log: ['szin:szurke'] — a régi bag-gate paritása"),
    ("OSSZETETT-SZO", "Kék laptoptáskát keresek",
     "KÉK táskák; a téma-kapu a 'taska' résszóra illeszkedik a 'laptoptáska'-ban"),
    ("NEGATIV", "Zöld energiával működik a bolt?",
     "NINCS szin: szűrés — nincs kategória-témajel a kérdésben"),
    ("NEGATIV2", "Sárga csekket kaptam, mit csináljak?",
     "NINCS szin: szűrés"),
    ("REGRESSZIO-m82f", "Van 32 GB memóriával laptopotok?",
     "notebookok; log: cat='… ÚJ Notebook' ['memoria-meret:32gb'] — a téma-kapu NEM érinti"),
    ("REGRESSZIO-m82c4", "Melyik a legolcsóbb lézernyomtató?",
     "log: ['nyomtatasi-technologia:lezer'] mode=super"),
]


def ask(msg, sid):
    body = json.dumps({"client_id": CLIENT, "session_id": sid,
                       "message": msg, "history": []}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "cx-e2e/m82g"})
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

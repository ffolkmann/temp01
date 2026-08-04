"""Onboarding / funkcio-teszt a CX chatbothoz (m80c, showcase-bol emelve).

Hasznalat (a VPS-en, api-konteneren belul vagy azt exec-elve):
    docker exec -i chatbot-api-prod python - < tools/onboarding_test.py            # notebookstore
    docker exec -i chatbot-api-prod python - < tools/onboarding_test.py -- copygo  # masik tenant

Tenant-specifikus keszlet a TESTS dict-ben; ismeretlen tenantra a GENERIC
keszlet fut (valasz-erkezik / zaro-link / KB-szallitas / follow-up smoke).
Elvart arakat NE egess be — a keszlet-fuggo assertek a valasz SZERKEZETET
(link-vegzodes, kulcsszo) ellenorizzek; ar-minimumot a Qdrantbol szamolj,
ha kell (lasd az A-teszt din_min kapcsolojat).
"""
import json
import re
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def chat(client, msg, sid, history=None):
    body = {"client_id": client, "session_id": sid, "message": msg}
    if history:
        body["history"] = history
    req = urllib.request.Request(BASE + "/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=150).read().decode()).get("reply", "")


def link(r):
    m = re.search(r"\]\((https?://[^)]+)\)\s*$", (r or "").strip())
    return m.group(1) if m else ""


def qdrant_min(client, must_extra):
    """Dinamikus ar-minimum a Qdrantbol (available=true + extra must)."""
    body = {"filter": {"must": [
        {"key": "client_id", "match": {"value": client}},
        {"key": "available", "match": {"value": True}},
    ] + must_extra}, "limit": 1000, "with_payload": ["price"], "with_vector": False}
    req = urllib.request.Request("http://qdrant:6333/collections/cx_chatbot_v2/points/scroll",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    pts = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())["result"]["points"]
    prices = []
    for p in pts:
        try:
            v = float(p["payload"].get("price") or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            prices.append(int(v))
    return min(prices) if prices else None


def hu(n):
    return f"{n:,}".replace(",", " ") if n else ""


def run_notebookstore(client):
    R = []

    def check(cat, label, cond, note=""):
        R.append((cat, label, bool(cond)))
        print("%-3s %-40s %s  %s" % (cat, label, "PASS" if cond else "FAIL", note[:80]))

    # A-D: szuperlativusz + follow-up lanc + policy (dinamikus ar-elvaras)
    min_uzleti = qdrant_min(client, [{"key": "usage", "match": {"any": ["uzleti"]}}])
    min_asus_uz = qdrant_min(client, [{"key": "usage", "match": {"any": ["uzleti"]}},
                                      {"key": "brand", "match": {"any": ["Asus", "ASUS", "asus"]}}])
    q1 = "Melyik a legolcs\u00f3bb \u00fczleti notebook?"
    r1 = chat(client, q1, "onb-1"); time.sleep(2)
    check("A", "keszlet-szuperlativusz + usage-link",
          (hu(min_uzleti) in r1) and link(r1).endswith("felhasznalas-jellege:uzleti"),
          "min=" + hu(min_uzleti))
    h = [{"role": "user", "content": q1}, {"role": "assistant", "content": r1}]
    q2 = "\u00e9s ASUS m\u00e1rk\u00e1j\u00faak k\u00f6z\u00fcl?"
    r2 = chat(client, q2, "onb-1", h); time.sleep(2)
    check("B", "follow-up marka-orokles (ASUS)",
          (hu(min_asus_uz) in r2) and link(r2).endswith("/asus"), "min=" + hu(min_asus_uz))
    h += [{"role": "user", "content": q2}, {"role": "assistant", "content": r2}]
    r3 = chat(client, "\u00e9s Lenovo?", "onb-1", h); time.sleep(2)
    check("C", "lanc 2. szint (Lenovo)", "Lenovo" in r3 and link(r3).endswith("/lenovo"), "")
    h += [{"role": "user", "content": "\u00e9s Lenovo?"}, {"role": "assistant", "content": r3}]
    r4 = chat(client, "\u00e9s mennyibe ker\u00fcl a sz\u00e1ll\u00edt\u00e1s?", "onb-1", h); time.sleep(2)
    check("D", "policy follow-up termekes historyval", ("DPD" in r4 or "MPL" in r4), "")

    # E-H: usage / meret / taska
    r5 = chat(client, "Melyik a legolcs\u00f3bb gamer laptop?", "onb-2"); time.sleep(2)
    check("E", "usage-szures (gamer)", link(r5).endswith("felhasznalas-jellege:gamer"), "")
    r6 = chat(client, "Melyik a legolcs\u00f3bb 17 colos laptop?", "onb-3"); time.sleep(2)
    check("F", "kijelzomeret-szures (17 -> :173)", link(r6).endswith("kijelzo-meret:173"), "")
    r7 = chat(client, "Melyik a legolcs\u00f3bb t\u00e1ska 17\"-os laptophoz?", "onb-4"); time.sleep(2)
    check("G", "taska colmeret-szures", "maximalis-notebook-meret:170" in link(r7), "")
    r8 = chat(client, "Melyik a legolcs\u00f3bb fekete h\u00e1tizs\u00e1k laptopnak?", "onb-5"); time.sleep(2)
    check("H", "taska-tipus szures (hatizsak)", "taska-tipusa:hatizsak" in link(r8), "")

    # I-K: marka direkt / nem-laptop / guard
    r9 = chat(client, "Melyik a legolcs\u00f3bb Acer notebook rakt\u00e1rr\u00f3l?", "onb-6"); time.sleep(2)
    check("I", "direkt marka + monitor-zaj szures",
          "Acer" in r9 and "uj-notebook-c100/acer" in link(r9) and "onitor" not in r9, "")
    r10 = chat(client, "HP toner \u00e1rak?", "onb-7"); time.sleep(2)
    check("J", "nem-laptop marka (HP toner)",
          "HP" in r10 and ("tintapatron-toner" in link(r10) or "termek-kereses" in link(r10)), "")
    r11 = chat(client, "Windows 11-es laptopot keresek, mit aj\u00e1nlasz?", "onb-8"); time.sleep(2)
    check("K", "windows-guard (11 nem colmeret)", "kijelzo-meret" not in link(r11), "")

    # L-O: KB / MSI / beillesztett nev
    r12 = chat(client, "Mennyibe ker\u00fcl a sz\u00e1ll\u00edt\u00e1s?", "onb-9"); time.sleep(2)
    check("L", "KB: szallitasi dijak", ("DPD" in r12 or "MPL" in r12) and "1 590" in r12, "")
    r13 = chat(client, "Mennyi garancia van a laptopokra?", "onb-10"); time.sleep(2)
    check("M", "KB: garancia", "garanci" in r13.lower(), "")
    r14 = chat(client, "MSI laptopot n\u00e9zn\u00e9k, mi a legolcs\u00f3bb?", "onb-11"); time.sleep(2)
    check("N", "MSI marka (slug-alias)", "MSI" in r14, "")
    r15 = chat(client, "ne mez? Asus Vivobook Go 15 Notebook (E1504FA-BQ2345) - 15.6\" FullHD, "
                       "AMD Ryzen 3-7320U, 8GB RAM, 512GB SSD", "onb-12")
    check("O", "beillesztett termeknev guard", "kijelzo-meret" not in link(r15), "")
    return R


def run_generic(client):
    """Uj tenant smoke: valasz erkezik, zaro-link van, KB-kerdes megy, follow-up nem torik."""
    R = []

    def check(cat, label, cond):
        R.append((cat, label, bool(cond)))
        print("%-3s %-40s %s" % (cat, label, "PASS" if cond else "FAIL"))

    r1 = chat(client, "Melyik a legolcs\u00f3bb term\u00e9ketek?", "onbg-1"); time.sleep(2)
    check("G1", "szuperlativusz valaszol + Ft-ar", "Ft" in r1)
    check("G2", "zaro link jelen", bool(link(r1)))
    h = [{"role": "user", "content": "Melyik a legolcs\u00f3bb term\u00e9ketek?"},
         {"role": "assistant", "content": r1}]
    r2 = chat(client, "\u00e9s mennyibe ker\u00fcl a sz\u00e1ll\u00edt\u00e1s?", "onbg-1", h); time.sleep(2)
    check("G3", "KB: szallitas follow-upban", "sz\u00e1ll\u00edt" in r2.lower())
    r3 = chat(client, "Milyen fizet\u00e9si m\u00f3dok vannak?", "onbg-2")
    check("G4", "KB: fizetesi modok", len(r3) > 40)
    return R


TESTS = {"notebookstore": run_notebookstore}

if __name__ == "__main__":
    client = sys.argv[-1] if len(sys.argv) > 1 and not sys.argv[-1].endswith(".py") and sys.argv[-1] != "--" else "notebookstore"
    print("=== CX onboarding teszt: %s ===" % client)
    results = TESTS.get(client, run_generic)(client)
    npass = sum(1 for _, _, c in results if c)
    print()
    print("OSSZESEN: %d/%d PASS" % (npass, len(results)))
    sys.exit(0 if npass == len(results) else 1)

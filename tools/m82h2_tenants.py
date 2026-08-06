"""m82h/2 MÉRÉS 2 — a márkaszótár TENANT-SZINTEN, és a toldalék-tűrés ára.

A m82h2_branddict.py a notebookstore-t mérte, és a valódi kérdés-korpuszt
STRESSZ-módban (a notebookstore szótárával MINDEN tenant kérdésén). Ez a lépés
a PRODUKCIÓS képet adja: minden tenant a SAJÁT szótárával a SAJÁT kérdésein.

  A) tenant-szintű leltár: distinct brand, elérhető termék, gyanús (köznyelvi) értékek
  B) a mai kézi 26-os lista fedettsége tenantonként
  C) DIFF a saját korpuszon: mai `_BRANDS` vs. jelölt szótár (v1 szigorú határ,
     v2 = v1 + toldalék-tűrés a >=7 karakteres kulcsokon, a facetdict _SUF mintája)
  D) recall: realisztikus márka-kérdések (a m82h_sweep 12-ese + a ma elérhetetlen
     filament-márkák)

Bemenet: data/m82h2_qtsv.txt  (client_id \t question)
Futtatás: docker exec -i chatbot-api-prod python - < tools/m82h2_tenants.py
"""
import json
import re
import sys
import unicodedata
import urllib.request

sys.path.insert(0, "/app")

Q = "http://qdrant:6333"
C = "cx_chatbot_v2"
QTSV = "/app/data/m82h2_qtsv.txt"

# szótár-higiénia jelölt: köznyelvi/töltelék brand-értékek
STOP = {"egyeb", "egyéb", "other", "n/a", "na", "nincs", "ismeretlen", "-", "no name",
        "noname", "general", "generic", "univerzalis", "univerzális"}

SUF_MIN = 7      # a facetdict mintája: csak hosszú kulcson tűrünk toldalékot
SUF_MAX = 4


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=120).read().decode())


def fold(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def keyform(raw):
    f = fold(raw)
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", f)
    if m:
        return [re.sub(r"\s+", " ", m.group(1)).strip(),
                re.sub(r"\s+", " ", m.group(2)).strip()]
    return [re.sub(r"\s+", " ", f).strip()]


def brands_of(client):
    """{payload ertek: (ossz, elerheto)} egy tenantra."""
    inv = {}
    offset = None
    for _ in range(120):
        body = {"filter": {"must": [{"key": "client_id", "match": {"value": client}},
                                    {"key": "type", "match": {"value": "product"}}]},
                "limit": 1000, "with_payload": ["brand", "available", "stock"],
                "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % C, body)["result"]
        for pt in res.get("points", []):
            p = pt.get("payload") or {}
            b = str(p.get("brand") or "").strip()
            if not b:
                continue
            av = p.get("available")
            if av is None:
                av = p.get("stock")
            d = inv.setdefault(b, [0, 0])
            d[0] += 1
            d[1] += 1 if av else 0
        offset = res.get("next_page_offset")
        if not offset:
            break
    return inv


def build_keys(inv):
    keys = {}
    for b, (n, av) in inv.items():
        for k in keyform(b):
            if not k or k in STOP or len(k) < 2:
                continue
            e = keys.setdefault(k, {"vals": set(), "n": 0, "av": 0})
            e["vals"].add(b)
            e["n"] += n
            e["av"] += av
    return keys


def make_rx(keys, suffix):
    rx = {}
    for k in keys:
        tail = r"(?![a-z0-9])"
        if suffix and len(k) >= SUF_MIN:
            tail = r"[a-z]{0,%d}(?![a-z0-9])" % SUF_MAX
        try:
            rx[k] = re.compile(r"(?<![a-z0-9])" + re.escape(k) + tail)
        except re.error:
            pass
    return rx


def detect(rx, fm):
    best = ""
    for k, r in rx.items():
        if r.search(fm) and len(k) > len(best):
            best = k
    return best


def main():
    from app.services.paramextract import _BRANDS
    manrx = {b: re.compile(r"\b" + re.escape(b) + r"\b") for b in _BRANDS}

    def detect_old(fm):
        for b in _BRANDS:
            if manrx[b].search(fm):
                return b
        return ""

    qs = {}
    try:
        with open(QTSV, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if "\t" not in ln:
                    continue
                cid, q = ln.split("\t", 1)
                q = q.strip()
                if q:
                    qs.setdefault(cid.strip(), set()).add(q)
    except OSError as exc:
        print("NINCS korpusz: %s" % exc)

    clients = sorted(set(qs) | set(json.load(open("/app/data/m82h2_clients.json"))))

    print("=" * 100)
    print("A/B) TENANT-SZINTU LELTAR ES A MAI KEZI LISTA FEDETTSEGE")
    print("=" * 100)
    print("  %-18s %7s %7s %7s   %-28s %s"
          % ("tenant", "brand#", "kulcs#", "kerdes#", "mai lista elerne (elerheto termek)", "gyanus/rovid kulcsok"))
    inv_all, keys_all = {}, {}
    for cid in clients:
        inv = brands_of(cid)
        if not inv:
            continue
        keys = build_keys(inv)
        inv_all[cid] = inv
        keys_all[cid] = keys
        av_tot = sum(v[1] for v in inv.values())
        av_man = 0
        for b, (n, av) in inv.items():
            f = fold(b)
            if any(re.search(r"\b" + re.escape(mb) + r"\b", f) for mb in _BRANDS):
                av_man += av
        short = sorted([k for k in keys if len(k) <= 3])
        dropped = sorted({b for b in inv if any(k in STOP for k in keyform(b))})
        print("  %-18s %7d %7d %7d   %5d/%-5d (%5.1f%%)          %s%s"
              % (cid, len(inv), len(keys), len(qs.get(cid, ())), av_man, av_tot,
                 100.0 * av_man / max(av_tot, 1), ",".join(short[:8]) or "-",
                 ("  KISZURT: " + ",".join(dropped)) if dropped else ""))

    print()
    print("=" * 100)
    print("C) DIFF A SAJAT KORPUSZON (produkcios kep): mai _BRANDS vs jelolt szotar")
    print("=" * 100)
    for variant, suffix in (("v1 szigoru hatar", False), ("v2 + toldalek-tures (>=%d kulcs)" % SUF_MIN, True)):
        print()
        print("--- %s ---" % variant)
        tot_same = tot_diff = 0
        rows = []
        for cid, keys in keys_all.items():
            corpus = qs.get(cid) or set()
            if not corpus:
                continue
            rx = make_rx(keys, suffix)
            same = 0
            diffs = []
            for q in corpus:
                fm = fold(q)
                new, old = detect(rx, fm), detect_old(fm)
                agree = new == old or (new and old and (new.startswith(old) or old.startswith(new)))
                if agree:
                    same += 1
                else:
                    diffs.append((old or "-", new or "-", q))
            tot_same += same
            tot_diff += len(diffs)
            rows.append((cid, same, diffs))
        print("  osszesen: azonos %d | ELTERES %d" % (tot_same, tot_diff))
        for cid, same, diffs in sorted(rows, key=lambda r: -len(r[2])):
            if not diffs:
                continue
            print("  [%s] azonos %d, elteres %d" % (cid, same, len(diffs)))
            agg = {}
            for old, new, q in diffs:
                agg.setdefault((old, new), []).append(q)
            for (old, new), qq in sorted(agg.items(), key=lambda kv: -len(kv[1]))[:12]:
                print("     %-14s -> %-24s %3d db | %s"
                      % (old, new, len(qq), qq[0][:70].replace("\n", " ")))

    print()
    print("=" * 100)
    print("D) RECALL: realisztikus marka-kerdesek (notebookstore szotarral)")
    print("=" * 100)
    keys = keys_all.get("notebookstore") or {}
    rx1 = make_rx(keys, False)
    rx2 = make_rx(keys, True)
    QS = [
        "legolcsobb ASUS laptop", "van HP nyomtatotok?", "Lenovo notebookot keresek",
        "Dell monitort szeretnek", "es ASUS markajuak kozul?", "milyen HP termekeitek vannak?",
        "van Brother tonerotok?", "Apple termeket keresek", "mit tudsz a Lenovorol?",
        "van Targus taskatok?", "Epson nyomtato ara", "csak Dellt szeretnek",
        "MSI laptopot keresek", "van LG monitorotok?",
        # ma ELERHETETLEN markak (a kezi listaban nincsenek)
        "Fiberlogy filamentet keresek", "van Spectrum filamentetek?",
        "Prusa nyomtatot szeretnek", "Creality alkatresz",
        "Western Digital merevlemez", "van Intel processzorotok?",
        "HPE szervert keresek", "Synology NAS-t szeretnek",
        "Xerox tonert keresek", "Samsonite taskatok van?",
    ]
    print("  %-38s %-22s %-22s %s" % ("kerdes", "mai _BRANDS", "v1 szigoru", "v2 toldalek"))
    for q in QS:
        fm = fold(q)
        print("  %-38s %-22s %-22s %s"
              % (q[:38], detect_old(fm) or "-", detect(rx1, fm) or "-", detect(rx2, fm) or "-"))


main()

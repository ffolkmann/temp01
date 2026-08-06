"""m82h/2 ADATFELVÉTEL — a kézi `_BRANDS` helyett a VALÓDI Qdrant `brand` értékek.

A m82h/1 mérés verdiktje: NE a szűrő-utat váltsuk (a `facets:marka` út kötelezően
kategória-kapus, és 12 márka-kérdésből csak 6-ban oldódik fel kategória), hanem
CSAK A SZÓTÁRAT — a kérdés-oldali márkafelismerés a Qdrant valódi `brand`
payload-értékeiből épüljön, a szűrés maradjon a `brand` payload must-feltétel.

Ez a script CSAK MÉR, nem javasol és nem patchel:
  A) márka-leltár: distinct `brand` értékek, darabszám, elérhető-darabszám, alak-típusok
  B) a kézi 26-os lista fedettsége: mit NEM ér el ma (recall-nyereség számokban)
  C) kulcs-képzés: a payload-értékből milyen illesztési kulcs lenne, ütközések
  D) FP-KOCKÁZAT: a jelölt kulcsok illesztése (1) a m82h negatív korpuszon,
     (2) a VALÓDI kérdés-korpuszon (data/m82h2_questions.txt, minden tenant
     `messages.question`-je) — a mai _BRANDS viselkedéséhez képest DIFF-ként

Futtatás:  docker exec -i chatbot-api-prod python - < tools/m82h2_branddict.py
"""
import json
import re
import sys
import unicodedata
import urllib.request

sys.path.insert(0, "/app")

CLIENT = "notebookstore"
Q = "http://qdrant:6333"
C = "cx_chatbot_v2"
QUESTIONS = "/app/data/m82h2_questions.txt"


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read().decode())


def fold(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def scroll(client):
    pts = []
    offset = None
    for _ in range(40):
        body = {"filter": {"must": [{"key": "client_id", "match": {"value": client}},
                                    {"key": "type", "match": {"value": "product"}}]},
                "limit": 1000,
                "with_payload": ["category", "brand", "available", "stock", "name"],
                "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % C, body)["result"]
        pts.extend(res.get("points", []))
        offset = res.get("next_page_offset")
        if not offset:
            break
    return pts


def keyform(raw):
    """A payload-értékből képzett illesztési kulcs(ok) — JELÖLT szabály.

    - fold
    - a zárójeles rész külön alias ("MSI (Micro-Star International)" -> "msi"
      ÉS "micro-star international")
    - a maradék szóköz-normalizálva
    """
    f = fold(raw)
    keys = []
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", f)
    if m:
        keys.append(re.sub(r"\s+", " ", m.group(1)).strip())
        keys.append(re.sub(r"\s+", " ", m.group(2)).strip())
    else:
        keys.append(re.sub(r"\s+", " ", f).strip())
    return [k for k in keys if k]


def main():
    from app.services.paramextract import _BRANDS

    pts = scroll(CLIENT)
    rows = []
    for pt in pts:
        p = pt.get("payload") or {}
        av = p.get("available")
        if av is None:
            av = p.get("stock")
        rows.append((str(p.get("brand") or ""), str(p.get("category") or ""), bool(av)))

    n = len(rows)
    inv = {}
    for brand, cat, av in rows:
        if not brand:
            continue
        d = inv.setdefault(brand, {"n": 0, "av": 0, "cats": set()})
        d["n"] += 1
        d["av"] += 1 if av else 0
        d["cats"].add(cat)

    print("=" * 96)
    print("A) MARKA-LELTAR (%s)" % CLIENT)
    print("=" * 96)
    print("  termek osszesen        : %d" % n)
    print("  van `brand` payload    : %d" % sum(1 for r in rows if r[0]))
    print("  distinct brand ertek   : %d" % len(inv))
    print("  distinct FOLD-olt kulcs: %d" % len({fold(b) for b in inv}))
    shapes = {"tobbszavas": 0, "zarojeles": 0, "kotojeles": 0, "pontos": 0,
              "1-2 karakter": 0, "szamot tartalmaz": 0}
    for b in inv:
        f = fold(b)
        if "(" in f:
            shapes["zarojeles"] += 1
        if " " in f.replace("(", " "):
            shapes["tobbszavas"] += 1
        if "-" in f:
            shapes["kotojeles"] += 1
        if "." in f:
            shapes["pontos"] += 1
        if len(f) <= 2:
            shapes["1-2 karakter"] += 1
        if re.search(r"\d", f):
            shapes["szamot tartalmaz"] += 1
    print("  alakok: %s" % ", ".join("%s=%d" % (k, v) for k, v in shapes.items()))

    print()
    print("  --- MIND a distinct ertek (elerheto szerint rendezve) ---")
    print("  %-38s %6s %6s %5s" % ("brand payload ertek", "ossz", "elerh", "kat"))
    for b, d in sorted(inv.items(), key=lambda kv: (-kv[1]["av"], -kv[1]["n"])):
        print("  %-38s %6d %6d %5d" % (b[:38], d["n"], d["av"], len(d["cats"])))

    # --- B) a kezi lista fedettsege ---
    man = set(_BRANDS)
    hit_manual = set()
    for b in inv:
        f = fold(b)
        for mb in man:
            if re.search(r"\b" + re.escape(mb) + r"\b", f):
                hit_manual.add(b)
                break
    miss = {b: d for b, d in inv.items() if b not in hit_manual}
    av_tot = sum(d["av"] for d in inv.values())
    av_man = sum(inv[b]["av"] for b in hit_manual)
    print()
    print("=" * 96)
    print("B) A KEZI 26-os _BRANDS FEDETTSEGE")
    print("=" * 96)
    print("  a kezi lista elerne   : %d/%d distinct marka, %d/%d elerheto termek (%.1f%%)"
          % (len(hit_manual), len(inv), av_man, av_tot, 100.0 * av_man / max(av_tot, 1)))
    print("  NEM ismert marka      : %d (ebbol elerheto termekkel: %d)"
          % (len(miss), sum(1 for d in miss.values() if d["av"])))
    print("  --- top 40 NEM ismert marka (elerheto termekszam szerint) ---")
    for b, d in sorted(miss.items(), key=lambda kv: -kv[1]["av"])[:40]:
        print("  %-38s %6d ossz %6d elerheto  %d kat" % (b[:38], d["n"], d["av"], len(d["cats"])))

    # --- C) kulcs-kepzes + utkozes ---
    keys = {}
    for b, d in inv.items():
        for k in keyform(b):
            e = keys.setdefault(k, {"vals": set(), "n": 0, "av": 0})
            e["vals"].add(b)
            e["n"] += d["n"]
            e["av"] += d["av"]
    print()
    print("=" * 96)
    print("C) JELOLT ILLESZTESI KULCSOK")
    print("=" * 96)
    print("  distinct kulcs: %d" % len(keys))
    multi = {k: e for k, e in keys.items() if len(e["vals"]) > 1}
    print("  tobb payload-ertekre mutato kulcs: %d" % len(multi))
    for k, e in sorted(multi.items(), key=lambda kv: -kv[1]["av"])[:15]:
        print("    %-24s -> %s" % (k, sorted(e["vals"])[:4]))
    short = sorted([k for k in keys if len(k) <= 3], key=lambda k: -keys[k]["av"])
    print("  <=3 karakteres kulcs: %d  -> %s" % (len(short), short[:30]))

    # --- D) FP-kockazat ---
    rx = {}
    for k in keys:
        try:
            rx[k] = re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])")
        except re.error:
            pass
    manrx = {b: re.compile(r"\b" + re.escape(b) + r"\b") for b in _BRANDS}

    def detect_new(fm):
        best = ""
        for k, r in rx.items():
            if r.search(fm) and len(k) > len(best):
                best = k
        return best

    def detect_old(fm):
        for b in _BRANDS:
            if manrx[b].search(fm):
                return b
        return ""

    NEG = [
        "melyik a legjobb intelligens megoldas?", "intelligens keresot szeretnek",
        "mennyibe kerul a szallitas?", "van ra 3 ev garancia?", "nem szeretnek dragat",
        "melyik a legolcsobb laptop?", "hogyan tudok reklamalni?", "van szemelyes atvetel?",
        "szamlat tudtok adni?", "mikor erkezik meg a csomag?", "melyik a legolcsobb monitor?",
        "van keszleten?", "mennyi az arres?", "visszakuldhetem 14 napon belul?",
        "fekete pentek akcio?", "zold energiaval mukodik a bolt?", "sarga csekket kaptam",
        "kerhetek arajanlatot 5 gepre?", "hogyan mukodik a reszletfizetes?",
        "van uzletetek budapesten?", "mikor lesz ujra keszleten?",
        "milyen fizetesi modok vannak?", "tudtok szamlazni ceges nevre?",
        "hol tart a rendelesem?", "van ingyenes szallitas?", "mennyi a garancialis atfutas?",
    ]
    print()
    print("=" * 96)
    print("D1) FP-SCAN a m82h negativ korpuszon (%d mondat)" % len(NEG))
    print("=" * 96)
    bad = 0
    for q in NEG:
        fm = fold(q)
        new, old = detect_new(fm), detect_old(fm)
        if new or old:
            bad += 1 if new else 0
            print("  %-44s uj=%-20s mai=%s" % (q[:44], new or "-", old or "-"))
    print("  UJ szotar talalat a negativ korpuszon: %d/%d" % (bad, len(NEG)))

    print()
    print("=" * 96)
    print("D2) VALODI KERDES-KORPUSZ (messages.question, minden tenant)")
    print("=" * 96)
    try:
        with open(QUESTIONS, encoding="utf-8", errors="replace") as fh:
            qs = [ln.strip() for ln in fh if ln.strip()]
    except OSError as exc:
        print("  NINCS korpusz-fajl (%s): %s" % (QUESTIONS, exc))
        return
    print("  kerdes osszesen: %d (distinct: %d)" % (len(qs), len(set(qs))))
    diff = {}
    same = agree = 0
    for q in set(qs):
        fm = fold(q)
        new, old = detect_new(fm), detect_old(fm)
        if new == old or (new and old and (new.startswith(old) or old.startswith(new))):
            same += 1
            agree += 1 if new else 0
            continue
        diff.setdefault((old or "-", new or "-"), []).append(q)
    print("  azonos verdikt: %d (ebbol markat talalt: %d) | ELTERES: %d kerdes, %d parban"
          % (same, agree, sum(len(v) for v in diff.values()), len(diff)))
    print()
    print("  --- ELTERESEK (mai -> uj), gyakorisag szerint ---")
    for (old, new), qq in sorted(diff.items(), key=lambda kv: -len(kv[1])):
        print("  [%s -> %s]  %d kerdes" % (old, new, len(qq)))
        for q in qq[:3]:
            print("      %s" % q[:110].replace("\n", " "))


main()

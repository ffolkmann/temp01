"""m82h/2 IGAZOLAS: "modul == shadow" a LEGENERALT teljes terkepeken.

A mero-tool shadow-ja (m82h2_05_shadow.detect) es a PRODUCTION modul
(app/services/branddict.detect_brand) ugyanazt kell adja minden valodi
kerdesre; plusz kimerito FP-scan a negativ korpuszon MINDEN tenant
szotaraval, es a mai kezi _BRANDS listahoz kepesti diff.

Futtatas (mountolt app/ + data/, Qdrant NEM kell):
  docker run --rm -i -v "$PWD/app:/app/app" -v "$PWD/data:/app/data" -w /app \
    chatbot-prod-api:latest python - < tools/m82h2_06_verify.py
"""
import glob
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, "/app")

from app.services.branddict import detect_brand, load_map  # noqa: E402
from app.services.paramextract import _BRANDS, build_filter_conditions, detect_constraints  # noqa: E402

QTSV = "/app/data/m82h2_qtsv.txt"
MAPDIR = "/app/data"

_RE_MAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\b")
_RE_URL = re.compile(
    r"(?:https?://|www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:hu|com|net|org|eu|io))(/\S*)?")
_RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c)).strip()


def norm(s):
    return _RE_NONALNUM.sub(" ", s).strip()


def clean(fm):
    fm = _RE_MAIL.sub(" ", fm)

    def _u(m):
        return " " + _RE_NONALNUM.sub(" ", m.group(2) or "") + " "
    return _RE_URL.sub(_u, fm)


def shadow_detect(message, brands, maxw):
    """A m82h2_05_shadow.detect masolata (a mero-tool logikaja)."""
    toks = norm(clean(fold(message))).split()
    best = ""
    for i in range(len(toks)):
        for n in range(1, maxw + 1):
            if i + n > len(toks):
                break
            cand = " ".join(toks[i:i + n])
            if cand in brands and len(cand) > len(best):
                best = cand
    return best


NEG = [
    "Mennyi a szállítási idő?", "Hogyan tudok visszaküldeni egy terméket?",
    "Milyen garancia jár a termékekre?", "Van bolti átvétel?", "Elfogadtok utánvétet?",
    "Élő ügyintézővel szeretnék beszélni", "Élő ügyintézőt kérek", "Mi a top 3 ajánlatod?",
    "Prémium tagságot szeretnék", "Orsóhoz van alkatrész?", "Kaphatok számlát a rendelésről?",
    "Hol van a boltotok?", "Mikor vagytok nyitva?", "Szeretnék egy árajánlatot kérni",
    "Nem kaptam meg a csomagom", "Hogyan tudok regisztrálni?", "Van részletfizetési lehetőség?",
    "Mennyibe kerül a kiszállítás Budapestre?",
    "Küldjetek egy visszaigazolást a vitox98@t-online.hu címre",
    "Írjatok a kapcsolat@valami.hu email címre", "Jó napot kívánok!", "Köszönöm a segítséget",
    "Milyen fizetési módok vannak?", "Cserélhető a termék, ha nem jó a méret?",
    "Mennyi az 1000 Ft feletti kedvezmény?", "Van ingyenes szállítás?", "Meddig tart a jótállás?",
    "Kaphatok kedvezményt nagyobb rendelésnél?", "Hol tudom követni a rendelésem?",
    "Melyik a legolcsóbb termék nálatok?", "Egyéb kérdésem lenne", "Kérek egy no name terméket",
]


def main():
    manrx = {b: re.compile(r"\b" + re.escape(b) + r"\b") for b in _BRANDS}

    def detect_old(fm):
        for b in _BRANDS:
            if manrx[b].search(fm):
                return b
        return ""

    maps = {}
    for path in sorted(glob.glob(os.path.join(MAPDIR, "brand_map_*.json"))):
        cid = os.path.basename(path)[len("brand_map_"):-len(".json")]
        m = load_map(cid, MAPDIR)
        if m:
            maps[cid] = m
    print("betoltott terkep: %d (%s)" % (len(maps), ", ".join(sorted(maps))))

    qs = {}
    with open(QTSV, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if "\t" not in ln:
                continue
            cid, q = ln.split("\t", 1)
            if q.strip():
                qs.setdefault(cid.strip(), set()).add(q.strip())

    print()
    print("=" * 96)
    print("1) MODUL == SHADOW a valodi kerdes-korpuszon")
    print("=" * 96)
    mismatch = tot = 0
    for cid, m in sorted(maps.items()):
        brands = m["brands"]
        maxw = int(m.get("max_words") or 4)
        for q in qs.get(cid) or ():
            tot += 1
            a = detect_brand(q, m)[0]
            b = shadow_detect(q, brands, maxw)
            if a != b:
                mismatch += 1
                if mismatch <= 10:
                    print("   ELTERES [%s] modul=%r shadow=%r | %s" % (cid, a, b, q[:60]))
    print("   %d kerdes | ELTERES: %d  -> %s" % (tot, mismatch, "OK" if not mismatch else "BUKO"))

    print()
    print("=" * 96)
    print("2) DIFF a mai kezi _BRANDS listahoz kepest (a TELJES terkeppel)")
    print("=" * 96)
    tot_same = tot_new = tot_lost = tot_chg = 0
    lost_ex = []
    for cid, m in sorted(maps.items()):
        same = new = lost = chg = 0
        for q in qs.get(cid) or ():
            old = detect_old(fold(q))
            best = detect_brand(q, m)[0]
            if best == old or (best and old and (best.startswith(old) or old.startswith(best))):
                same += 1
            elif not old and best:
                new += 1
            elif old and not best:
                lost += 1
                if len(lost_ex) < 12:
                    lost_ex.append("[%s] %s -> - | %s" % (cid, old, q[:56]))
            else:
                chg += 1
        tot_same += same
        tot_new += new
        tot_lost += lost
        tot_chg += chg
        if qs.get(cid):
            print("   [%-16s] azonos %4d | UJ %3d | ELVESZETT %2d | VALTOZOTT %2d"
                  % (cid, same, new, lost, chg))
    print("   OSSZESEN: azonos %d | UJ %d | ELVESZETT %d | VALTOZOTT %d"
          % (tot_same, tot_new, tot_lost, tot_chg))
    for e in lost_ex:
        print("     ELVESZETT: " + e)

    print()
    print("=" * 96)
    print("3) KIMERITO FP-SCAN: negativ korpusz x MINDEN tenant szotara")
    print("=" * 96)
    fp = 0
    for cid, m in sorted(maps.items()):
        for q in NEG:
            k = detect_brand(q, m)[0]
            if k:
                fp += 1
                print("   FP [%s] %-24s <- %s" % (cid, k, q))
    print("   FP: %d / %d par -> %s" % (fp, len(maps) * len(NEG), "OK" if not fp else "BUKO"))

    print()
    print("=" * 96)
    print("4) VEGPONT: detect_constraints + build_filter_conditions (Qdrant-feltetel)")
    print("=" * 96)
    for cid, q in (("notebookstore", "Van HP nyomtatotok?"),
                   ("notebookstore", "es ASUS markajuak kozul?"),
                   ("notebookstore", "Van MSI laptopotok?"),
                   ("fishingoutlet", "Carp expert quick change erdekelne"),
                   ("kellegyszerszam", "Ryobi ONE+ akkus polirozo"),
                   ("nagyonallatshop", "Whiskas csirkes szaraz tap"),
                   ("copygo", "https://copygo.hu/xiaomi-mesh-system-ax3000-3-db"),
                   ("notebookstore", "Mennyi a szallitasi ido?")):
        cons = detect_constraints(q, cid)
        must = build_filter_conditions(cons)
        bv = (cons.get("brand"), [x[:34] for x in (cons.get("brand_vals") or [])])
        print("   [%-15s] %-46s -> brand=%-14s vals=%s" % (cid, q[:46], bv[0] or "-", bv[1] or "-"))
        for c in must:
            print("        must: %s" % json.dumps(c, ensure_ascii=False)[:110])

    return 0 if (not mismatch and not fp and not tot_lost) else 1


sys.exit(main())

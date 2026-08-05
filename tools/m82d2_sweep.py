"""m82d/2 sweep: toldalek-hossz (_SUF_MAX 3->4) + "pro" szinonima merese a VALODI terkepen.

Futtatas a PATCHELT (mountolt) app/-bol, Qdrant nem kell:
  docker run --rm -i -v "$PWD/app:/app/app" -v "$PWD/data:/app/data" -w /app \
    chatbot-prod-api:latest python - < tools/m82d2_sweep.py

Nem modosit semmit. Ugyanazon a fajlon fut a patch ELOTT (baseline) es UTAN.

Miert ez a ket valtozas (m82d elomeres, tools/m82d_nonsuper.py):
  "Milyen lezernyomtatoitok vannak?"  -> nincs cimke: a birtokos tobbes 4 karakteres
                                         toldalek, a _SUF_MAX viszont 3
  "Windows 11 Pro-s gepet szeretnek"  -> nincs cimke: a "pro" nem vezetheto le a
                                         "windows-11-professional" slugbol
A +4 valodi hatokore a magyar 4 betus toldalekok: -okat/-eket/-akat (targyeset tobbes)
es -itok/-atok (birtokos tobbes). A rovid (<7 karakteres) ertekeket tovabbra is a
_SUF_MIN kapu vedi (intel -> "intelligens", pla -> "plazma").
"""
import sys

sys.path.insert(0, "/app")

from app.services import facetdict as fd  # noqa: E402
from app.services.facetdict import detect_facet_tags  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

CID = "notebookstore"
FMAP = load_map(CID)

CAT_NB = "Laptop, Notebook > ÚJ Notebook"
CAT_MON = "Monitor, Projektor, TV > Monitor"
CAT_NYO = "Nyomtató > Nyomtató"
CAT_FIL = "Nyomtató > 3D nyomtató filament"
CAT_TAB = "Tablet > Tablet"

# (kerdes, kategoria, elvart cimke VAGY None = nem szabad semmit felismerni)
POS = [
    # --- UJ: 4 karakteres toldalek (ma NEM illeszkedik) ---
    ("milyen lezernyomtatoitok vannak?", CAT_NYO, "nyomtatasi-technologia:lezer"),
    ("milyen tintasugarasokat arultok?", CAT_NYO, "nyomtatasi-technologia:tintasugaras"),
    # HATAR (tudatos): a +6 karakteres toldalek ("...itokat") mar NEM cel --
    # 5-6 betunel a szo-utkozes kockazata gyorsan no, ezert a _SUF_MAX 4.
    ("a lezernyomtatoitokat nezegetem", CAT_NYO, None),
    # --- UJ: "pro" szinonima (ma NEM illeszkedik) ---
    ("windows 11 pro-s gepet szeretnek", CAT_NB, "operacios-rendszer:windows-11-professional"),
    ("windows 11 pro laptopot keresek", CAT_NB, "operacios-rendszer:windows-11-professional"),
    # --- REGRESSZIO: ezeknek ma is mukodniuk kell ---
    ("windows 11 professional laptop", CAT_NB, "operacios-rendszer:windows-11-professional"),
    ("legolcsobb lezernyomtato", CAT_NYO, "nyomtatasi-technologia:lezer"),
    ("tintasugarasat keresek", CAT_NYO, "nyomtatasi-technologia:tintasugaras"),
    ("erintokepernyos laptop", CAT_NB, "erintokepernyo:10-point-multi-touch"),
    ("legolcsobb 4K monitor", CAT_MON, "felbontas:3840x2160"),
    ("ips paneles monitor", CAT_MON, "panel-tipus:ips"),
    ("legolcsobb 32 GB memorias laptop", CAT_NB, "memoria-meret:32gb"),
    ("nvidia videokartyas gep", CAT_NB, "grafikus-vezerlo-gyarto:nvidia"),
    ("ujjlenyomat-olvasos uzleti laptop", CAT_NB, "extrak:ujjlenyomat-olvaso"),
    ("pla filament", CAT_FIL, "anyag:pla"),
    ("nfc-s laptop", CAT_NB, "extrak:nfc"),
    ("adatvedelmi-kamerafedeles gep", CAT_NB, None),   # szelektivitas-kapu ejti ki
]

# NEGATIV: egyiknek sem szabad cimket adnia (a patch utan sem!)
# Az elso 20 a m82c/3 korpusza valtozatlanul; a vegen az UJ, toldalekos csapdak.
NEG = [
    ("melyik a legjobb intelligens megoldas?", CAT_NB),
    ("intelligens keresot szeretnek", CAT_NB),
    ("van plazma tevetek?", CAT_FIL),
    ("mennyibe kerul a szallitas?", CAT_NB),
    ("van ra 3 ev garancia?", CAT_NB),
    ("fekete pentek akcio?", CAT_NB),
    ("nem szeretnek dragat", CAT_NB),
    ("melyik a legolcsobb laptop?", CAT_NB),
    ("legolcsobb 17 colos laptop", CAT_NB),
    ("legolcsobb ASUS laptop", CAT_NB),
    ("hogyan tudok reklamalni?", CAT_NB),
    ("van szemelyes atvetel?", CAT_NB),
    ("szamlat tudtok adni?", CAT_NB),
    ("mikor erkezik meg a csomag?", CAT_NB),
    ("legolcsobb tintasugaras nyomtato", CAT_NYO),
    ("melyik a legolcsobb monitor?", CAT_MON),
    ("van keszleten?", CAT_NB),
    ("tudtok segiteni valasztani?", CAT_TAB),
    ("mennyi az arres?", CAT_NB),
    ("visszakuldhetem 14 napon belul?", CAT_NB),
    # --- UJ csapdak, amiket a +4 nyithatna ki ---
    ("milyen intelligensebb megoldasokat ajanlotok?", CAT_NB),
    ("plazmatevetek van?", CAT_FIL),
    ("professzionalis tanacsot kerek", CAT_NB),
    ("milyen szallitasokat vallaltok?", CAT_NB),
    ("milyen garanciakat adtok a gepekre?", CAT_NB),
    ("monitorozast tudtok vallalni?", CAT_MON),
]

print("facet_map kategoriak: %d | _SUF_MIN=%d _SUF_MAX=%d"
      % (len((FMAP.get("categories") or {})), fd._SUF_MIN, fd._SUF_MAX))

# --- DIAG: mit erint egyaltalan a +4 (hany ertek >= _SUF_MIN karakter) ---
vals = set()
for _slug, ent in (FMAP.get("categories") or {}).items():
    for attr, vv in (ent.get("facets") or {}).items():
        for v in (vv or {}):
            vals.add((attr, str(v)))
long_vals = [v for a, v in vals if len(fd._norm_key(v)) >= fd._SUF_MIN]
print("kulonbozo attr:ertek par: %d, ebbol >= %d karakter (a lazitas hatokore): %d"
      % (len(vals), fd._SUF_MIN, len(long_vals)))

# --- DIAG: az erintett attributumok valodi ertekei ---
for slug, attr in (("uj-notebook", "operacios-rendszer"), ("nyomtato", "nyomtatasi-technologia")):
    ent = (FMAP.get("categories") or {}).get(slug) or {}
    got = (ent.get("facets") or {}).get(attr) or {}
    print("  %-18s / %-24s -> %s" % (slug, attr, sorted(got)[:12]))

print()
print("=== POZITIV (recall) ===")
pos_ok = 0
for q, cat, exp in POS:
    tags = detect_facet_tags(q, [cat] * 5, FMAP, category=cat)
    got = ",".join(tags) or "-"
    ok = (exp in tags) if exp else (not tags)
    pos_ok += 1 if ok else 0
    print("%s %-44s %-42s %s" % (" " if ok else "!", q[:44], exp or "(semmi)", got[:44]))
print("\nPOZITIV: %d/%d" % (pos_ok, len(POS)))

print()
print("=== NEGATIV (false positive kapu) ===")
neg_ok = 0
for q, cat in NEG:
    tags = detect_facet_tags(q, [cat] * 5, FMAP, category=cat)
    allowed = {"nyomtatasi-technologia:tintasugaras"} if "legolcsobb tintasugaras" in q else set()
    bad = [t for t in tags if t not in allowed]
    neg_ok += 1 if not bad else 0
    print("%s %-46s %s" % (" " if not bad else "!", q[:46], ",".join(bad) or "tiszta"))
print("\nNEGATIV: %d/%d" % (neg_ok, len(NEG)))

print()
print("=== KIMERITO FP-SCAN: a NEGATIV korpusz MIND a kategorian ===")
print("(a m82c/3 ota kotelezo kapu minden szotar-boviteshez)")
allcats = list((FMAP.get("categories") or {}).items())
scan_bad = 0
scan_n = 0
for q, _c in NEG:
    allowed = {"nyomtatasi-technologia:tintasugaras"} if "legolcsobb tintasugaras" in q else set()
    for slug, _ent in allcats:
        scan_n += 1
        fake_cat = slug.replace("-", " ")
        tags = detect_facet_tags(q, [], FMAP, category=fake_cat)
        bad = [t for t in tags if t not in allowed]
        if bad:
            scan_bad += 1
            print("  ! %-38s [%s] -> %s" % (q[:38], slug, ",".join(bad)))
print("  ellenorzott kerdes x kategoria par: %d, ebbol talalatot adott: %d" % (scan_n, scan_bad))

print()
print("OSSZESITES: pozitiv %d/%d, negativ %d/%d, FP-scan %d/%d"
      % (pos_ok, len(POS), neg_ok, len(NEG), scan_bad, scan_n))

"""m82c/3 sweep: ragozas-/szinonima-tures merese a VALODI terkepen.

Futtatas: docker exec -i chatbot-api-prod python - < tools/m82c3_sweep.py
Nem modosit semmit. Ugyanazon a fajlon fut a patch ELOTT (baseline) es UTAN.

A POZITIV esetek a ma ismert recall-reseket irjak le (ragozott alak, koznyelvi
szinonima). A NEGATIV korpusz a false positive kapu: ezeknek a patch utan is
URESNEK kell maradniuk. Kiemelt csapdak, amiket a toldalek-tures elronthat:
  intel      -> "intelligens"   (grafikus-vezerlo-gyarto:intel, 496 db)
  pla        -> "plazma"        (3d-nyomtato-filament:pla, 64 db)
  lezer      -> "lezerszintezo"
  nyomtato   -> kategoria-fonev (mar tiltva a _usable cat_key agaval)
"""
import sys

sys.path.insert(0, "/app")

from app.services.facetdict import detect_category, detect_facet_tags  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

CID = "notebookstore"
FMAP = load_map(CID)

CAT_NB = "Laptop, Notebook > ÚJ Notebook"
CAT_MON = "Monitor, Projektor, TV > Monitor"
CAT_NYO = "Nyomtató > Nyomtató"
CAT_TAS = "Kiegészítők > Notebook táska, hátizsák"
CAT_FIL = "Nyomtató > 3D nyomtató filament"
CAT_TAB = "Tablet > Tablet"

# (kerdes, kategoria, elvart cimke VAGY None = nem szabad semmit felismerni)
POS = [
    # --- ragozott alakok (ma NEM illeszkednek) ---
    ("ujjlenyomat-olvasos uzleti laptop", CAT_NB, "extrak:ujjlenyomat-olvaso"),
    ("van olyan laptop ujjlenyomat-olvasoval?", CAT_NB, "extrak:ujjlenyomat-olvaso"),
    ("tintasugarasat keresek", CAT_NYO, "nyomtatasi-technologia:tintasugaras"),
    # a ragozas ILLESZKEDNE, de a szelektivitas-kapu helyesen kiejti:
    # adatvedelmi-kamerafedel 868 / 958 termek = 91%% lefedettseg -> nem szuro
    ("adatvedelmi-kamerafedeles gep", CAT_NB, None),
    ("erintoceruzaval hasznalhato notebook", CAT_NB, "extrak:erintoceruza"),
    ("valltaskakezitaskat keresek", CAT_TAS, None),          # taska-tipusa SKIP_ATTRS
    # --- koznyelvi szinonimak (ma NEM illeszkednek) ---
    ("legolcsobb 4K monitor", CAT_MON, "felbontas:3840x2160"),
    ("2K felbontasu monitort keresek", CAT_MON, "felbontas:2560x1440"),
    ("full hd monitor", CAT_MON, "felbontas:1920x1080"),
    ("erintokepernyos laptop", CAT_NB, "erintokepernyo:10-point-multi-touch"),
    ("legolcsobb lezernyomtato", CAT_NYO, "nyomtatasi-technologia:lezer"),
    # --- ezeknek MA IS mukodniuk kell (regresszio) ---
    ("legolcsobb 32 GB memorias laptop", CAT_NB, "memoria-meret:32gb"),
    ("windows 11 professional laptop", CAT_NB, "operacios-rendszer:windows-11-professional"),
    ("nvidia videokartyas gep", CAT_NB, "grafikus-vezerlo-gyarto:nvidia"),
    ("ips paneles monitor", CAT_MON, "panel-tipus:ips"),
    ("pla filament", CAT_FIL, "anyag:pla"),
    ("nfc-s laptop", CAT_NB, "extrak:nfc"),
]

# NEGATIV: egyiknek sem szabad cimket adnia (a patch utan sem!)
NEG = [
    ("melyik a legjobb intelligens megoldas?", CAT_NB),      # intel csapda
    ("intelligens keresot szeretnek", CAT_NB),               # intel csapda
    ("van plazma tevetek?", CAT_FIL),                        # pla csapda
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
    ("legolcsobb tintasugaras nyomtato", CAT_NYO),           # kat-fonev: csak a technologia jojjon
    ("melyik a legolcsobb monitor?", CAT_MON),
    ("van keszleten?", CAT_NB),
    ("tudtok segiteni valasztani?", CAT_TAB),
    ("mennyi az arres?", CAT_NB),
    ("visszakuldhetem 14 napon belul?", CAT_NB),
]

print("facet_map kategoriak:", len((FMAP.get("categories") or {})))
print()
print("=== POZITIV (recall) ===")
print("%-46s %-34s %-34s %s" % ("kerdes", "elvart", "kapott", ""))
print("-" * 120)
pos_ok = 0
for q, cat, exp in POS:
    tags = detect_facet_tags(q, [cat] * 5, FMAP, category=cat)
    got = ",".join(tags) or "-"
    ok = (exp in tags) if exp else (not tags)
    pos_ok += 1 if ok else 0
    print("%s %-46s %-34s %-34s" % (" " if ok else "!", q[:46], exp or "(semmi)", got[:34]))
print("\nPOZITIV: %d/%d" % (pos_ok, len(POS)))

print()
print("=== NEGATIV (false positive kapu) ===")
neg_ok = 0
for q, cat in NEG:
    tags = detect_facet_tags(q, [cat] * 5, FMAP, category=cat)
    # a "tintasugaras nyomtato" eset kivetel: ott a technologia HELYES
    allowed = {"nyomtatasi-technologia:tintasugaras"} if "tintasugaras" in q else set()
    bad = [t for t in tags if t not in allowed]
    neg_ok += 1 if not bad else 0
    print("%s %-46s %s" % (" " if not bad else "!", q[:46], ",".join(bad) or "tiszta"))
print("\nNEGATIV: %d/%d" % (neg_ok, len(NEG)))

print()
print("=== KATEGORIA-SZANDEK (m82c/2 regresszio) ===")
CATS = [c for c in (
    CAT_NB, CAT_MON, CAT_NYO, CAT_TAS, CAT_FIL, CAT_TAB,
    "Asztali PC, AiO, Konzol > Asztali számítógép",
)]
for q, exp in (
    ("Melyik a legolcsóbb gamer asztali számítógép?", "Asztali számítógép"),
    ("legolcsóbb 4K monitor", "Monitor"),
    ("Melyik a legolcsóbb gamer laptop?", ""),
):
    got = detect_category(q, CATS)
    mark = " " if (exp in got if exp else got == "") else "!"
    print("%s %-46s -> %s" % (mark, q[:46], got or "(nincs)"))

print()
print("=== KIMERITO FP-SCAN: a NEGATIV korpusz MIND a 85 kategorian ===")
print("(a toldalek-tures kereszt-kategoria hatasat meri; csak a talalatokat listazza)")
allcats = []
for slug, ent in (FMAP.get("categories") or {}).items():
    allcats.append((slug, ent))
scan_bad = 0
scan_n = 0
for q, _c in NEG:
    allowed = {"nyomtatasi-technologia:tintasugaras"} if "tintasugaras" in q else set()
    for slug, _ent in allcats:
        scan_n += 1
        # a kapu a SLUG-bol keszul: a payload-kategoria helyett kozvetlenul
        fake_cat = slug.replace("-", " ")
        tags = detect_facet_tags(q, [], FMAP, category=fake_cat)
        bad = [t for t in tags if t not in allowed]
        if bad:
            scan_bad += 1
            print("  ! %-38s [%s] -> %s" % (q[:38], slug, ",".join(bad)))
print("  ellenorzott kerdes x kategoria par: %d, ebbol talalatot adott: %d" % (scan_n, scan_bad))

print()
print("OSSZESITES: pozitiv %d/%d, negativ %d/%d" % (pos_ok, len(POS), neg_ok, len(NEG)))

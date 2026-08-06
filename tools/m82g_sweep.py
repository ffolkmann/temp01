"""m82g/1 sweep: a `szin` attributum kivezetese a _SKIP_ATTRS-bol (kezi _COLORS helyett).

SHADOW = PONTOSAN a javasolt production-logika: a modul valtozatlan, csak a
_SKIP_ATTRS-bol vesszuk ki a "szin"-t. Ezert patch elott tervezesre, patch utan
igazolasra UGYANEZ a script fut ("modul == shadow, 0 elteres").

Qdrant NEM kell. Futtatas:
  docker run --rm -i -v "$PWD/app:/app/app" -v "$PWD/data:/app/data" -w /app \
    chatbot-prod-api:latest python - < tools/m82g_sweep.py
"""
import sys

sys.path.insert(0, "/app")

from app.services import facetdict as fd  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

CID = "notebookstore"
FMAP = load_map(CID)
CATS = (FMAP.get("categories") or {})

FIL = "3d nyomtato filament"
TAS = "notebook taska hatizsak"
DVD = "kulso dvd iro"
NB = "uj notebook"
NYO = "nyomtato"
MON = "monitor"


def tags(q, cat):
    return fd.detect_facet_tags(q, [], FMAP, category=cat)


# (kerdes, kategoria, elvart cimke VAGY None = semmit nem szabad)
POS = [
    # --- filament: MA SEMMI (a _COLORS bag-gate-elt, ide sosem er el) ---
    ("van fekete filamentetek?", FIL, "szin:fekete"),
    ("piros PLA filamentet keresek", FIL, "szin:piros"),
    ("tengereszkek filament", FIL, "szin:tengereszkek"),
    ("antracit szurke filamentet szeretnek", FIL, "szin:antracit-szurke"),
    ("vilagos zold filament ara?", FIL, "szin:vilagos-zold"),
    ("naturalis filamentetek van?", FIL, "szin:naturalis"),
    # --- taska: ma a p_szin (bag-gate) adja, cel a PARITAS ---
    ("fekete notebook taskat keresek", TAS, "szin:fekete"),
    ("van szurke hatizsakotok?", TAS, "szin:szurke"),
    ("kek laptoptaska", TAS, "szin:kek"),
    ("barna taskatok van?", TAS, "szin:barna"),
    # --- kulso dvd iro: ma semmi ---
    ("ezust kulso dvd irot keresek", DVD, "szin:ezust"),
]

# NEGATIV: egyiknek sem szabad szin-cimket adnia
NEG = [
    # m82c/3 korpusz (valtozatlanul, regresszio)
    ("melyik a legjobb intelligens megoldas?", NB),
    ("intelligens keresot szeretnek", NB),
    ("mennyibe kerul a szallitas?", NB),
    ("van ra 3 ev garancia?", NB),
    ("nem szeretnek dragat", NB),
    ("melyik a legolcsobb laptop?", NB),
    ("hogyan tudok reklamalni?", NB),
    ("van szemelyes atvetel?", NB),
    ("szamlat tudtok adni?", NB),
    ("mikor erkezik meg a csomag?", NB),
    ("melyik a legolcsobb monitor?", MON),
    ("van keszleten?", NB),
    ("mennyi az arres?", NB),
    ("visszakuldhetem 14 napon belul?", NB),
    # --- UJ szin-csapdak (amit a kivezetes nyithatna ki) ---
    ("fekete pentek akcio?", FIL),
    ("fekete pentek akcio?", TAS),
    ("black friday ajanlatok?", FIL),
    ("zold energiaval mukodik a bolt?", FIL),
    ("a piros lampa villog a nyomtaton", FIL),
    ("feher pontok vannak a kijelzon", TAS),
    ("van fekete-feher nyomtatasotok?", NYO),
    ("arany garanciacsomagot vettem", TAS),
    ("sarga csekket kaptam", TAS),
    ("zold utat kaptam a rendelesre?", FIL),
    ("kek szamlat kertem", DVD),
    ("a szurke zonaban van a szallitasi hatarido", TAS),
]


def run(label):
    print()
    print("### %s  (_SKIP_ATTRS=%s)" % (label, sorted(fd._SKIP_ATTRS)))
    print("=== POZITIV (recall) ===")
    pos_ok = 0
    for q, cat, exp in POS:
        got = tags(q, cat)
        ok = (exp in got) if exp else (not got)
        pos_ok += 1 if ok else 0
        print("%s %-42s %-24s -> %s" % (" " if ok else "!", q[:42], exp or "(semmi)",
                                        ",".join(got) or "-"))
    print("POZITIV: %d/%d" % (pos_ok, len(POS)))

    print()
    print("=== NEGATIV (szin-cimke tilos) ===")
    neg_ok = 0
    for q, cat in NEG:
        got = [t for t in tags(q, cat) if t.startswith("szin:")]
        neg_ok += 1 if not got else 0
        print("%s %-46s %s" % (" " if not got else "!", q[:46], ",".join(got) or "tiszta"))
    print("NEGATIV: %d/%d" % (neg_ok, len(NEG)))

    print()
    print("=== KIMERITO FP-SCAN: NEGATIV korpusz x MIND a 85 kategoria (csak szin:) ===")
    bad = n = 0
    for q, _c in NEG:
        for slug in CATS:
            n += 1
            got = [t for t in tags(q, slug.replace("-", " ")) if t.startswith("szin:")]
            if got:
                bad += 1
                print("  ! %-40s [%s] -> %s" % (q[:40], slug, ",".join(got)))
    print("  par: %d, ebbol szin-talalat: %d" % (n, bad))
    return pos_ok, neg_ok, bad


base = run("BASELINE (mai modul)")
fd._SKIP_ATTRS = frozenset(x for x in fd._SKIP_ATTRS if x != "szin")
shadow = run("SHADOW (szin kivezetve)")

print()
print("OSSZEVETES  pozitiv %d -> %d | negativ %d -> %d | FP-scan %d -> %d"
      % (base[0], shadow[0], base[1], shadow[1], base[2], shadow[2]))

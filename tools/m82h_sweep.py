"""m82h/1 SWEEP — kivezethető-e a `marka` a generikus szótárba, és mi az ára?

Három változatot mér a VALÓDI crawl-térképen (85 kategória):
  v0  = a mai modul (marka a _SKIP_ATTRS-ben)  -> baseline
  v1  = marka kivezetve, _MIN_LEN=3 változatlan -> a 2 betűs márkák (hp/lg/fs) kiesnek
  v2  = marka kivezetve + RÖVID-ENGEDMÉNY a marka attribútumon (min 2 karakter)
        ^ EZ a javaslat; a shadow PONTOSAN a javasolt production-logika, ezért
          patch után ugyanez a script igazol is ("modul == v2, 0 eltérés").

Plusz: (C) a 2. blokkoló mérése — a m80-as márkaág ma kategória-kapu NÉLKÜL fut,
a facets-út viszont kötelezően kapus. Hány realisztikus márka-kérdésből oldódik
fel egyáltalán kategória?

Futtatás:  docker exec -i chatbot-api-prod python - < tools/m82h_sweep.py
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from app.services import facetdict as fd  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

CID = "notebookstore"
FMAP = load_map(CID) or {}
CATS = (FMAP.get("categories") or {})
SHORT_OK = frozenset({"marka"})


def _usable2(attr, val, n, cat_size, cat_key, short_ok):
    """A javasolt _usable: rövid-engedmény CSAK a SHORT_OK attribútumokon."""
    v = str(val or "")
    minlen = 2 if (short_ok and attr in SHORT_OK) else fd._MIN_LEN
    if len(v) < minlen or v in fd._STOP_VALUES:
        return False
    if len(v) < fd._MIN_LEN:
        nk = fd._norm_key(v)
        if cat_key and len(nk) >= 4 and nk in cat_key:
            return False
        if v.replace("-", "").replace(".", "").isdigit():
            return False
        if int(n or 0) <= 0:
            return False
        if cat_size and int(n) >= fd._COVER_MAX * cat_size:
            return False
        return True
    return fd._usable(val, n, cat_size, cat_key)


def shadow(message, category, skip_marka, short_ok):
    """A mai detect_facet_tags, két kapcsolóval. Minden más SZÓ SZERINT azonos."""
    slug, ent = fd._category_entry([], FMAP, category)
    if not ent:
        return []
    cat_key = fd._norm_key(slug)
    facets = ent.get("facets") or {}
    if not facets:
        return []
    cat_size = fd._cat_size(facets)
    fm = fd._fold(message)
    skip = set(fd._SKIP_ATTRS)
    if not skip_marka:
        skip.discard("marka")
    else:
        skip.add("marka")
    out = []
    topic = None
    for attr in sorted(facets):
        if attr in skip:
            continue
        if attr in fd._TOPIC_REQ_ATTRS:
            if topic is None:
                topic = fd._topic_hit(slug, fm)
            if not topic:
                continue
        best = ""
        for val, n in (facets[attr] or {}).items():
            if not _usable2(attr, val, n, cat_size, cat_key, short_ok):
                continue
            rx = fd._rx(val)
            hit = rx is not None and rx.search(fm)
            if not hit:
                hit = fd._syn_hit(attr, val, fm)
            if hit and fd._is_trap(val, fm):
                hit = False
            if hit and len(str(val)) > len(best):
                best = str(val)
        if best:
            out.append("%s:%s" % (attr, best))
            if len(out) >= fd._MAX_ATTRS:
                break
    return out


NB, MON, NYO, TIN, TAS, ROU = ("uj notebook", "monitor", "nyomtato",
                               "tintapatron toner", "notebook taska hatizsak", "router")

POS = [
    ("legolcsobb asus laptop", NB, "marka:asus"),
    ("lenovo notebookot keresek", NB, "marka:lenovo"),
    ("van dell monitorotok?", MON, "marka:dell"),
    ("acer monitort szeretnek", MON, "marka:acer"),
    ("brother nyomtato", NYO, "marka:brother"),
    ("epson nyomtatot keresek", NYO, "marka:epson"),
    ("targus taskat keresek", TAS, "marka:targus"),
    ("apple laptopotok van?", NB, "marka:apple"),
    # --- A ROVID-ENGEDMENY celpontjai (v1-ben MIND kiesik) ---
    ("van hp nyomtatotok?", NYO, "marka:hp"),
    ("hp tintapatront keresek", TIN, "marka:hp"),
    ("hp laptopotok van?", NB, "marka:hp"),
    # --- ISMERT HATAR: az osszevont slug nem illeszkedik a rovid alakra ---
    ("msi laptopot keresek", NB, "marka:msi-micro-star-international"),
]

NEG = [
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
    ("fekete pentek akcio?", NB),
    ("zold energiaval mukodik a bolt?", NB),
    ("sarga csekket kaptam", TAS),
    ("kerhetek arajanlatot 5 gepre?", NB),
    ("hogyan mukodik a reszletfizetes?", NB),
    ("van uzletetek budapesten?", NB),
    ("mikor lesz ujra keszleten?", MON),
    ("milyen fizetesi modok vannak?", NB),
    ("tudtok szamlazni ceges nevre?", NB),
    ("hol tart a rendelesem?", NB),
    ("van ingyenes szallitas?", ROU),
    ("mennyi a garancialis atfutas?", NYO),
]

VARIANTS = (("v0 MAI", True, False), ("v1 marka, min3", False, False),
            ("v2 marka + rovid-engedmeny", False, True))

print("facet_map kategoriak: %d | _MIN_LEN=%d | SHORT_OK=%s\n"
      % (len(CATS), fd._MIN_LEN, sorted(SHORT_OK)))

res = {}
for label, skip_marka, short_ok in VARIANTS:
    print("=" * 88)
    print("### %s" % label)
    print("=" * 88)
    pos_ok = 0
    for q, cat, exp in POS:
        got = shadow(q, cat, skip_marka, short_ok)
        ok = exp in got
        pos_ok += 1 if ok else 0
        print("%s %-38s %-38s %s" % (" " if ok else "!", q[:38], exp, ",".join(got) or "-"))
    print("POZITIV: %d/%d" % (pos_ok, len(POS)))

    bad = n = 0
    hits = []
    for q, _c in NEG:
        for slug in CATS:
            n += 1
            got = [t for t in shadow(q, slug.replace("-", " "), skip_marka, short_ok)
                   if t.startswith("marka:")]
            if got:
                bad += 1
                hits.append("  ! %-38s [%s] -> %s" % (q[:38], slug, ",".join(got)))
    print("FP-SCAN (marka: cimke a negativ korpuszon x %d kategoria): %d/%d"
          % (len(CATS), bad, n))
    for h in hits[:20]:
        print(h)
    res[label] = (pos_ok, bad, n)
    print()

print("=" * 88)
print("OSSZEVETES")
for label, (p, b, n) in res.items():
    print("  %-30s pozitiv %2d/%2d | FP %d/%d" % (label, p, len(POS), b, n))


async def catgate():
    from app.services.retrieval import category_catalog
    catalog = await category_catalog(CID)
    print()
    print("=" * 88)
    print("C) 2. BLOKKOLO: felold-e a kerdes kategoriat? (a facets-ut KOTELEZO kapuja)")
    print("=" * 88)
    QS = [
        "legolcsobb ASUS laptop", "van HP nyomtatotok?", "Lenovo notebookot keresek",
        "Dell monitort szeretnek", "es ASUS markajuak kozul?", "milyen HP termekeitek vannak?",
        "van Brother tonerotok?", "Apple termeket keresek", "mit tudsz a Lenovorol?",
        "van Targus taskatok?", "Epson nyomtato ara", "csak Dellt szeretnek",
    ]
    ok = 0
    for q in QS:
        c = fd.detect_category(q, catalog)
        ok += 1 if c else 0
        print("  %-40s -> %s" % (q[:40], fd._leaf(c) or "(NINCS -> talalat-alapu fallback)"))
    print("  kategoria feloldva: %d/%d" % (ok, len(QS)))

asyncio.run(catgate())

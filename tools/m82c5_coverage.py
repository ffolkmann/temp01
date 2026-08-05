"""m82c/5 FEDETTSEG-SWEEP: hol marad NEMAN el a facets-szures?

Futtatas: docker exec -i chatbot-api-prod python - < tools/m82c5_coverage.py
Nem modosit semmit.

Miert: a lezernyomtatos hibat (m82c/4) veletlenul talaltuk meg -- a valasz
folyekony es hihetó volt, csak eppen 102 990 Ft-ot mondott 33 090 helyett,
mert a szuro nem futott le. A valasz minosegebol ez NEM latszik. Ez a sweep
szisztematikusan vegigmegy a teljes terkepen, es megmutatja:

  A) KATEGORIA-KAPU: minden kategoriara a termeszetes kerdes ("Melyik a
     legolcsobb X?") beallitja-e a kaput. Ami nem, ott a talalat-alapu
     fallbackre esunk -- pont ez volt a lezernyomtato.
  B) ERTEK-FEDETTSEG: a szotar minden HASZNALHATO erteke elerheto-e a
     kanonikus, illetve a ragozott alakjabol.
  C) AR-HATAS: ahol szur, ott valtozik-e egyaltalan a legolcsobb termek.
     Ha nem valtozik, a szuro felesleges; ha sokat valtozik, eddig rossz
     valaszt adtunk.
"""
import json
import sys
import urllib.request

sys.path.insert(0, "/app")

from app.services import facetdict as fd  # noqa: E402
from app.services.linkfacet import load_map  # noqa: E402

Q = "http://qdrant:6333"
C = "cx_chatbot_v2"
CID = "notebookstore"
FMAP = load_map(CID)


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read().decode())


BASE = [{"key": "client_id", "match": {"value": CID}},
        {"key": "type", "match": {"value": "product"}}]


def min_price(conds):
    """A legolcsobb ar a szurt halmazban (None ha ures)."""
    body = {"filter": {"must": BASE + list(conds)}, "limit": 1000,
            "with_payload": ["price"], "with_vector": False}
    best = None
    offset = None
    for _ in range(6):
        b = dict(body)
        if offset:
            b["offset"] = offset
        res = post("/collections/%s/points/scroll" % C, b)["result"]
        for pt in res.get("points", []):
            try:
                p = float((pt.get("payload") or {}).get("price") or 0)
            except (TypeError, ValueError):
                continue
            if p > 0 and (best is None or p < best):
                best = p
        offset = res.get("next_page_offset")
        if not offset:
            break
    return best


# --- valodi payload-kategoriak ---
cats = {}
offset = None
for _ in range(20):
    body = {"filter": {"must": BASE}, "limit": 1000,
            "with_payload": ["category"], "with_vector": False}
    if offset:
        body["offset"] = offset
    res = post("/collections/%s/points/scroll" % C, body)["result"]
    for pt in res.get("points", []):
        c = (pt.get("payload") or {}).get("category")
        if c:
            cats[c] = cats.get(c, 0) + 1
    offset = res.get("next_page_offset")
    if not offset:
        break
CATS = sorted(cats)


def leaf_simple(cat):
    """A kategoria-nev termeszetes, kerdesbe illo alakja."""
    lf = fd._leaf(cat)
    return lf.split(",")[0].strip()


print("payload-kategoria: %d | terkep-kategoria: %d" % (len(CATS), len(FMAP.get("categories") or {})))

# ======================= A) KATEGORIA-KAPU FEDETTSEG =======================
print()
print("=== A) KATEGORIA-KAPU: 'Melyik a legolcsobb <kategoria>?' ===")
a_ok = a_miss = a_wrong = 0
miss_rows = []
for cat in CATS:
    q = "Melyik a legolcsobb %s?" % leaf_simple(cat)
    got = fd.detect_category(q, CATS)
    if got == cat:
        a_ok += 1
    elif not got:
        a_miss += 1
        miss_rows.append(("NINCS", leaf_simple(cat), cats[cat], ""))
    else:
        a_wrong += 1
        miss_rows.append(("MASIK", leaf_simple(cat), cats[cat], fd._leaf(got)))
print("  eltalalt: %d | nem allt be: %d | MASIK kategoriara allt: %d" % (a_ok, a_miss, a_wrong))
if miss_rows:
    miss_rows.sort(key=lambda r: -r[2])
    print("  --- a legnagyobb erintett kategoriak (termekszam szerint) ---")
    for kind, name, n, other in miss_rows[:20]:
        print("    %-6s %-34s %5d db %s" % (kind, name[:34], n, ("-> " + other) if other else ""))

# ======================= B) ERTEK-FEDETTSEG =======================
print()
print("=== B) ERTEK-FEDETTSEG: elerheto-e minden hasznalhato ertek? ===")
per_attr = {}
tot = can_hit = inf_hit = 0
unreachable = []
digit_miss = []
alpha_miss = []
for slug, ent in (FMAP.get("categories") or {}).items():
    facets = ent.get("facets") or {}
    if not facets:
        continue
    cat_size = fd._cat_size(facets)
    cat_key = fd._norm_key(slug)
    payload_cat = next((c for c in CATS if fd._norm_key(fd._leaf(c)) == cat_key), "")
    if not payload_cat:
        continue
    for attr, vals in facets.items():
        if attr in fd._SKIP_ATTRS:
            continue
        for val, n in (vals or {}).items():
            if not fd._usable(val, n, cat_size, cat_key):
                continue
            tot += 1
            d = per_attr.setdefault(attr, [0, 0, 0, 0])
            d[0] += 1
            canon = str(val).replace("-", " ")
            tags = fd.detect_facet_tags("Melyik a legolcsobb %s?" % canon, [], FMAP,
                                        category=payload_cat)
            hit_c = ("%s:%s" % (attr, val)) in tags
            can_hit += 1 if hit_c else 0
            d[1] += 1 if hit_c else 0
            # ragozott alak KETFELE:
            #  - kotojellel ("16 GB-os") -- a magyar igy irja a szamot/roviditest
            #  - kozvetlenul ("lezeres") -- a betuszavaknal ez a termeszetes
            suff = "t" if canon[-1:] in "aeiou" else "os"
            tag_want = "%s:%s" % (attr, val)
            hit_h = tag_want in fd.detect_facet_tags(
                "Melyik a legolcsobb %s-%s?" % (canon, suff), [], FMAP, category=payload_cat)
            hit_d = tag_want in fd.detect_facet_tags(
                "Melyik a legolcsobb %s%s?" % (canon, suff), [], FMAP, category=payload_cat)
            hit_i = hit_h or hit_d
            inf_hit += 1 if hit_i else 0
            d[2] += 1 if hit_i else 0
            d[3] += 1 if hit_d else 0
            has_digit = any(ch.isdigit() for ch in str(val))
            if not hit_d:
                (digit_miss if has_digit else alpha_miss).append(
                    (slug, attr, val, n, len(fd._norm_key(val)), hit_h))
            if not hit_c:
                unreachable.append((slug, attr, val, n))
print("  hasznalhato ertek osszesen: %d" % tot)
print("  kanonikus alakbol elerheto: %d (%.1f%%)" % (can_hit, 100.0 * can_hit / max(tot, 1)))
print("  ragozott alakbol elerheto : %d (%.1f%%)" % (inf_hit, 100.0 * inf_hit / max(tot, 1)))
print("  --- attributumonkent (osszes / kanonikus / barmely ragozott / KOZVETLEN) ---")
for attr in sorted(per_attr, key=lambda a: -per_attr[a][0])[:18]:
    t, c1, c2, c3 = per_attr[attr]
    flag = "  <-- RES" if c2 < t else ""
    print("    %-30s %4d / %4d / %4d / %4d%s" % (attr[:30], t, c1, c2, c3, flag))

print()
print("  === A KOZVETLEN TOLDALEK RESEI (itt szamit a _SUF_MIN=7 kapu) ===")
print("  SZAMJEGYES ertekek (16gb, 128gb...): %d db" % len(digit_miss))
print("    -> ezeknel a kotojeles alak ('16 GB-os') mar MA IS mukodik:  %d / %d"
      % (sum(1 for r in digit_miss if r[5]), len(digit_miss)))
for slug, attr, val, n, ln, hh in digit_miss[:8]:
    print("      %-22s %-22s %-14s hossz=%d kotojellel=%s" % (slug[:22], attr[:22], str(val)[:14], ln, "OK" if hh else "NEM"))
print("  BETUS ertekek (lezer, ips, intel...): %d db" % len(alpha_miss))
print("    -> ezek a VALODI resek; a 7 karakteres kapu vedi oket a szo-utkozestol")
for slug, attr, val, n, ln, hh in sorted(alpha_miss, key=lambda r: -r[3])[:12]:
    print("      %-22s %-22s %-16s hossz=%d  %d db" % (slug[:22], attr[:22], str(val)[:16], ln, n))
if unreachable:
    print("  --- kanonikus alakbol SEM elerheto (elso 15) ---")
    for slug, attr, val, n in unreachable[:15]:
        print("    %-26s %-26s %-24s %d db" % (slug[:26], attr[:26], str(val)[:24], n))

# ======================= C) AR-HATAS =======================
print()
print("=== C) AR-HATAS: valtozik-e a legolcsobb termek, ha szurunk? ===")
print("  (a 12 legnagyobb kategoria, kategoriankent a legszelektivebb ertek)")
big = sorted(((n, c) for c, n in cats.items()), reverse=True)[:12]
print("  %-30s %-34s %10s %10s" % ("kategoria", "szuro", "szures nelkul", "szurve"))
print("  " + "-" * 92)
for n, cat in big:
    slug_ent = None
    ck = fd._norm_key(fd._leaf(cat))
    for slug, ent in (FMAP.get("categories") or {}).items():
        if fd._norm_key(slug) == ck:
            slug_ent = (slug, ent)
            break
    if not slug_ent:
        continue
    slug, ent = slug_ent
    facets = ent.get("facets") or {}
    cat_size = fd._cat_size(facets)
    cand = []
    for attr, vals in facets.items():
        if attr in fd._SKIP_ATTRS:
            continue
        for val, cnt in (vals or {}).items():
            if fd._usable(val, cnt, cat_size, fd._norm_key(slug)):
                cand.append((cnt, attr, val))
    if not cand:
        continue
    cand.sort()
    cnt, attr, val = cand[0]          # a legszelektivebb
    base = [{"key": "category", "match": {"value": cat}}]
    tag = "%s:%s" % (attr, val)
    p0 = min_price(base)
    p1 = min_price(base + [{"key": "facets", "match": {"value": tag}}])
    mark = "" if (p0 and p1 and abs(p0 - p1) < 1) else "   <-- VALTOZIK"
    print("  %-30s %-34s %10s %10s%s" % (
        fd._leaf(cat)[:30], tag[:34],
        ("%.0f" % p0) if p0 else "-", ("%.0f" % p1) if p1 else "-", mark))

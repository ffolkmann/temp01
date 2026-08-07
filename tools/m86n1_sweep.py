# -*- coding: utf-8 -*-
"""m86 NYITOTT #1 — SHADOW v2: SZIMMETRIKUS ILLESZTÉS ADDITÍV ALTERNÁCIÓVAL.

Az első kör (tő-CSERE) lelete: a tő rövidebb, mint a teljes név, ezért MEGESZI a
záró rag-keretet (`_CAT_SUFFIX`=4). "notebookotok": a "notebo" tő után 6 karakter
marad -> a lookahead elbukik -> a m82e/m82g esetek ELVESZTEK (4 db a
notebookstore-on). Ezért a tő nem CSERE, hanem ALTERNATÍVA:

    utolso_token -> (?:teljes|to)      # a teljes alak van elol, azt probalja eloszor

Így a mai illeszkedés bitre változatlan (a teljes alak ugyanott, ugyanannyi rag-
kerettel illeszkedik), és CSAK ÚJ illeszkedés jöhet be. Maradó kockázat: az új
jelölt HOLTVERSENYT csinálhat egy másik kategóriával -> "" (ezt méri a
kockázat-térkép).

  a6 = additiv alternacio, to >= 6 normalizalt karakter
  a5 = additiv alternacio, to >= 5
  r6 = az ELSO kor (tő-CSERE, to >= 6) — referenciaként, hogy latszodjon a kulonbseg

A shadow a PRODUCTION detect_category-t hívja, csak a `_cat_rx`-et cseréli.
"""
import json
import re
import sys
import urllib.request
from collections import defaultdict

sys.path.insert(0, "/app")
import app.services.facetdict as fd  # noqa: E402

QDRANT = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
QFILE = "/app/data/m86n1_q.tsv"
LIMIT = 400
HEAD_PARTS = 120
SHOW = 40

TENANTS = [
    ("kellegyszerszam", "cat_tags"),
    ("teslashop", "cat_tags"),
    ("nagyonallatshop", "cat_tags"),
    ("smartzilla", "cat_tags"),
    ("plcomfort", "cat_tags"),
    ("mastercool", "cat_tags"),
    ("rmweb", "cat_tags"),
    ("notebookstore", "category"),
]

NEG = [
    "Mennyibe kerül a szállítás?", "Milyen garancia jár a termékekre?",
    "Hogyan tudok elállni a vásárlástól?", "Fizethetek utánvéttel?",
    "Hol van a boltotok?", "Nyitva vagytok szombaton?",
    "Milyen fekete péntek akcióitok lesznek?", "Mikor érkezik meg a csomagom?",
    "Szeretnék panaszt tenni egy termékre", "Milyen fizetési módok vannak?",
    "Nem szeretnék regisztrálni, úgy is tudok rendelni?", "Hol tart a rendelésem?",
]

TARGET = {
    "kellegyszerszam": [
        "Csavarhúzó készlet", "Milyen csavarhúzóitok vannak?",
        "Milyen anyagból van?", "Betonba szeretnék fúrni",
        "Van láncfűrészetek?", "Milyen vasalatot ajánlotok?",
    ],
    "nagyonallatshop": [
        "Milyen kutyatápot ajánlotok?", "Van macskaeledeletek?",
        "Nyúlnak való szénát keresek", "Milyen jutalomfalatot ajánlotok?",
    ],
    "teslashop": ["Milyen üléshuzatotok van?", "Telefontartót keresek"],
    "notebookstore": [
        "Melyik a legolcsóbb lézernyomtató?", "Van 32 GB memóriával laptopotok?",
        "Van NVIDIA videokártyás notebookotok?", "Milyen 4K monitorokat ajánlotok?",
        "Milyen szürke hátizsákotok van?", "Melyik a legolcsóbb notebooktáska?",
        "És hátizsákban mi a legolcsóbb 17 colos géphez?",
        "és notebooknál mennyibe kerül egy rambővítés?",
    ],
}

# ezekre a kerdesekre jelolt-diagnosztika keszul (miert valtozott?)
DIAG = {
    "notebookstore": ["Van NVIDIA videokártyás notebookotok?",
                      "Milyen szürke hátizsákotok van?",
                      "és notebooknál mennyibe kerül egy rambővítés?"],
    "kellegyszerszam": ["Csavarhúzó készlet", "Milyen anyagból van?"],
}


def post(path, body, timeout=300):
    r = urllib.request.Request(QDRANT + path, data=json.dumps(body).encode(),
                               method="POST", headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def catalog(client, key):
    body = {"key": key, "limit": LIMIT, "exact": True,
            "filter": {"must": [{"key": "client_id", "match": {"value": client}},
                                {"key": "type", "match": {"value": "product"}}]}}
    hits = (post("/collections/%s/facet" % COLL, body).get("result") or {}).get("hits") or []
    vals = [str(h["value"]) for h in hits if h.get("value")]
    cnt = {str(h["value"]): int(h.get("count") or 0) for h in hits}
    return vals, cnt


# ---------------------------------------------------------------- shadow
_ORIG_RX = fd._cat_rx
_VOWELS = set("aeiou")


def stem_of(part, stem_min):
    """(tokenek, a levagott tovu utolso token) — vagy az eredeti utolso token."""
    toks = [t for t in str(part).split(" ") if t]
    if not toks:
        return None, None
    last = toks[-1]
    if fd._fold(last).endswith("k") and len(last) >= 2:
        b1 = last[:-1]
        f1 = fd._fold(b1)
        if f1 and f1[-1] in _VOWELS and len(b1) >= 2:
            b2 = b1[:-1]
            if len(fd._norm_key(" ".join(toks[:-1] + [b2]))) >= stem_min:
                return toks, b2
        if len(fd._norm_key(" ".join(toks[:-1] + [b1]))) >= stem_min:
            return toks, b1
    return toks, last


def make_rx(stem_min, additive):
    cache = {}

    def rx(part):
        if part in cache:
            return cache[part]
        toks, base = stem_of(part, stem_min)
        if not toks:
            cache[part] = None
            return None
        last = toks[-1]
        if base != last:
            lastpat = ("(?:%s|%s)" % (re.escape(last), re.escape(base))) if additive \
                else re.escape(base)
        else:
            lastpat = re.escape(last)
        pref = (r"(?:[a-z]{2,%d})?" % fd._CAT_PREFIX_MAX) \
            if len(fd._norm_key(part)) >= fd._CAT_COMPOUND_MIN else r""
        r = re.compile(r"(?<![a-z0-9])" + pref
                       + r"[\s\-]*".join([re.escape(t) for t in toks[:-1]] + [lastpat])
                       + r"(?![a-z0-9]{%d,})" % (fd._CAT_SUFFIX + 1))
        cache[part] = r
        return r
    return rx


VARIANTS = [("a6", make_rx(6, True)), ("a5", make_rx(5, True)), ("r6", make_rx(6, False))]


def run_pass(rxfn, qmap, cats):
    fd._cat_rx = rxfn
    fd._crx_cache.clear()
    out = {}
    for client, qs in qmap.items():
        cat = cats[client][0]
        out[client] = [fd.detect_category(q, cat) for q in qs]
    fd._cat_rx = _ORIG_RX
    fd._crx_cache.clear()
    return out


def classify(base, new):
    if base == new:
        return None
    if base and not new:
        return "VESZTES"
    if not base and new:
        return "UJ"
    return "VALTOZOTT"


def diffs(qmap, base, new):
    out = defaultdict(list)
    for client, qs in qmap.items():
        for i, q in enumerate(qs):
            k = classify(base[client][i], new[client][i])
            if k:
                out[client].append((k, q, base[client][i], new[client][i]))
    return out


def cands(message, cat, rxfn):
    """Jelolt-diagnosztika: mely kategoria-nev-reszek illeszkednek es hogyan."""
    fm = fd._fold(message)
    out = []
    for c in cat:
        for p in fd._cat_parts(str(c or "")):
            rx = rxfn(p)
            if rx is None:
                continue
            for m in rx.finditer(fm):
                t = fd._CAT_TAIL.match(fm, m.end())
                t = t.group(0) if t else ""
                out.append((p, m.group(0), t, "JELZO" if (t and fd._CAT_ADJ.match(t)) else "fej", c))
    return out


# ---------------------------------------------------------------- korpuszok
questions = defaultdict(list)
seen = defaultdict(set)
with open(QFILE, encoding="utf-8", errors="replace") as fh:
    for ln in fh:
        if "\t" not in ln:
            continue
        c, q = ln.rstrip("\n").split("\t", 1)
        q = q.strip()
        if q and q not in seen[c]:
            seen[c].add(q)
            questions[c].append(q)

cats = {}
for client, key in TENANTS:
    cats[client] = catalog(client, key)

real = {c: questions.get(c, []) for c, _k in TENANTS}
head = {}
for client, _k in TENANTS:
    vals, cnt = cats[client]
    top = sorted(vals, key=lambda v: -cnt.get(v, 0))[:HEAD_PARTS]
    parts = sorted({p for v in top for p in fd._cat_parts(v)})
    hq = []
    for p in parts:
        hq += ["Milyen %sok vannak?" % p, "Keresek egy %st" % p, "Van %s készleten?" % p]
    head[client] = hq
neg = {c: list(NEG) for c, _k in TENANTS}
tgt = {c: list(TARGET.get(c, [])) for c, _k in TENANTS}

base = {"real": run_pass(_ORIG_RX, real, cats), "head": run_pass(_ORIG_RX, head, cats),
        "neg": run_pass(_ORIG_RX, neg, cats), "tgt": run_pass(_ORIG_RX, tgt, cats)}
res = {}
for name, rxfn in VARIANTS:
    res[name] = {k: run_pass(rxfn, v, cats) for k, v in
                 (("real", real), ("head", head), ("neg", neg), ("tgt", tgt))}

print("=" * 100)
print("1) FELOLDAS A VALODI KERDES-KORPUSZON")
print("=" * 100)
print("%-17s %7s %6s | %s" % ("tenant", "kerdes", "ma", "   ".join("%-6s" % n for n, _ in VARIANTS)))
for client, _k in TENANTS:
    row = "%-17s %7d %6d |" % (client, len(real[client]), sum(1 for r in base["real"][client] if r))
    for name, _rx in VARIANTS:
        row += " %8d" % sum(1 for r in res[name]["real"][client] if r)
    print(row)

print("\n%-17s | %s" % ("ELTERES (ma vs)", "  ".join("%-16s" % n for n, _ in VARIANTS)))
for client, _k in TENANTS:
    row = "%-17s |" % client
    for name, _rx in VARIANTS:
        d = diffs(real, base["real"], res[name]["real"]).get(client, [])
        row += " %-17s" % ("%d (U%d/V%d/C%d)" % (
            len(d), sum(1 for x in d if x[0] == "UJ"),
            sum(1 for x in d if x[0] == "VESZTES"),
            sum(1 for x in d if x[0] == "VALTOZOTT")))
    print(row)

print("\n" + "=" * 100)
print("2) FEJ-REGRESSZIO + NEGATIV KORPUSZ (V = elveszett feloldas)")
print("=" * 100)
for client, _k in TENANTS:
    row = "%-17s |" % client
    for name, _rx in VARIANTS:
        dh = diffs(head, base["head"], res[name]["head"]).get(client, [])
        dn = diffs(neg, base["neg"], res[name]["neg"]).get(client, [])
        row += " %s: fej %3d(V%d) neg %d |" % (
            name, len(dh), sum(1 for x in dh if x[0] == "VESZTES"), len(dn))
    print(row)

print("\n" + "=" * 100)
print("3) CEL-ESETEK")
print("=" * 100)
for client, _k in TENANTS:
    if not tgt[client]:
        continue
    print("\n--- %s ---" % client)
    for i, q in enumerate(tgt[client]):
        line = "   %-46s ma=%-26s" % (q[:46], (base["tgt"][client][i] or "-")[:26])
        for name, _rx in VARIANTS:
            line += " | %s=%-26s" % (name, (res[name]["tgt"][client][i] or "-")[:26])
        print(line)

print("\n" + "=" * 100)
print("4) KOCKAZAT-TERKEP — a6 (a jelolt) MINDEN eltérése a valodi korpuszon")
print("=" * 100)
d = diffs(real, base["real"], res["a6"]["real"])
for client, _k in TENANTS:
    rows = d.get(client) or []
    if not rows:
        continue
    print("\n--- %s (%d) ---" % (client, len(rows)))
    for kind, q, b, n in rows[:SHOW]:
        print("   %-9s %-72s %s -> %s" % (kind, q[:72], b or "-", n or "-"))
    if len(rows) > SHOW:
        print("   ... es meg %d" % (len(rows) - SHOW))

print("\n" + "=" * 100)
print("5) a5 TOBBLETE az a6-hoz kepest (mit nyer/veszit a lazabb kuszob)")
print("=" * 100)
d5 = diffs(real, res["a6"]["real"], res["a5"]["real"])
for client, _k in TENANTS:
    rows = d5.get(client) or []
    if not rows:
        continue
    print("\n--- %s (%d) ---" % (client, len(rows)))
    for kind, q, b, n in rows[:SHOW]:
        print("   %-9s %-72s %s -> %s" % (kind, q[:72], b or "-", n or "-"))
    if len(rows) > SHOW:
        print("   ... es meg %d" % (len(rows) - SHOW))

print("\n" + "=" * 100)
print("6) JELOLT-DIAGNOSZTIKA (ma vs a6)")
print("=" * 100)
for client, qs in DIAG.items():
    cat = cats[client][0]
    for q in qs:
        print("\n[%s] %s" % (client, q))
        for label, rxfn in (("ma", _ORIG_RX), ("a6", dict(VARIANTS)["a6"])):
            cs = cands(q, cat, rxfn)
            txt = " | ".join("%s~%s+%s[%s]" % (p, mt, t or "-", k) for p, mt, t, k, _c in cs) or "(nincs)"
            fd._cat_rx = rxfn
            fd._crx_cache.clear()
            r = fd.detect_category(q, cat)
            fd._cat_rx = _ORIG_RX
            fd._crx_cache.clear()
            print("   %-3s -> %-30s  jeloltek: %s" % (label, r or "(nincs)", txt[:300]))

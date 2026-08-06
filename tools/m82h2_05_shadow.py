"""m82h/2 MÉRÉS 5 — a JAVASOLT PRODUCTION-LOGIKA shadow-ja.

Ez a script PONTOSAN azt a szabályrendszert implementálja, ami a kódba kerül
(app/services/branddict.py + paramextract), hogy patch után ugyanez a script
igazolhassa: "modul == shadow, 0 eltérés".

SZÓTÁR (tenantonként, a Qdrant VALÓDI `brand` payload-értékeiből):
  - keyform: fold + "X (Y)" -> [x, y]  (pl. "MSI (Micro-Star International)")
  - min 2 karakter; H1 STOP-lista (kategória-szerű töltelék brand-értékek)
  - H3 köznyelvi-kapu: RÖVID kulcs (<= _SHORT_MAX) ÉS kereszt-tenant df >= _DF_MIN -> ki
    (a df = hány MÁSIK tenant KB-szövegében fordul elő a kulcs)
  - kulcs -> a hozzá tartozó NYERS payload-értékek (ezek mennek a Qdrant match-any-be,
    így a kézi _BRAND_PAYLOAD_ALIASES is magától kiváltódik)

KÉRDÉS-OLDAL:
  - fold + H2': e-mail ki, URL HOST ki (az útvonal-tokenek MARADNAK — a beillesztett
    termék-URL útvonalában ott a márka)
  - token/n-gram illesztés (nem alfanumerikus -> szóköz), leghosszabb kulcs nyer

Futtatás: docker exec -i chatbot-api-prod python - < tools/m82h2_05_shadow.py
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
CLIENTS = "/app/data/m82h2_clients.json"

# --- a javasolt production-konstansok -------------------------------------
_MIN_LEN = 2
_SHORT_MAX = 4          # eddig a hosszig "rövid" a kulcs
_DF_MIN = 3             # ennyi MÁSIK tenant KB-je teszi köznyelvivé
_MAX_WORDS = 4          # a leghosszabb márkakulcs szó-száma
_STOP = frozenset({
    "egyeb", "egyeb marka", "other", "n/a", "na", "nincs", "ismeretlen",
    "no name", "noname", "general", "generic", "univerzalis",
    "alkatresz", "alkatreszek", "premium", "kiegeszito", "kiegeszitok",
    "akcio", "outlet", "csomag", "keszlet",
    "top", "import", "home", "profi", "standard",
})

_RE_MAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\b")
_RE_URL = re.compile(
    r"(?:https?://|www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:hu|com|net|org|eu|io))(/\S*)?")
_RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def fold(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def clean(fm):
    """H2': e-mail ki; URL: a HOST ki, az útvonal tokenekre bontva marad."""
    fm = _RE_MAIL.sub(" ", fm)

    def _u(m):
        return " " + _RE_NONALNUM.sub(" ", m.group(2) or "") + " "
    return _RE_URL.sub(_u, fm)


def norm(s):
    return _RE_NONALNUM.sub(" ", s).strip()


def keyform(raw):
    f = fold(raw)
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", f)
    parts = [m.group(1), m.group(2)] if m else [f]
    return [k for k in (norm(p) for p in parts) if k]


def detect(fm, keys):
    """token/n-gram illesztés, leghosszabb kulcs nyer."""
    toks = norm(clean(fm)).split()
    best = ""
    for i in range(len(toks)):
        for n in range(1, _MAX_WORDS + 1):
            if i + n > len(toks):
                break
            cand = " ".join(toks[i:i + n])
            if cand in keys and len(cand) > len(best):
                best = cand
    return best


def post(path, body):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=120).read().decode())


def scroll(client, fields, product=True):
    out = []
    offset = None
    must = [{"key": "client_id", "match": {"value": client}}]
    flt = {"must": must}
    if product:
        must.append({"key": "type", "match": {"value": "product"}})
    else:
        flt["must_not"] = [{"key": "type", "match": {"value": "product"}}]
    for _ in range(120):
        body = {"filter": flt, "limit": 500, "with_payload": fields, "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % C, body)["result"]
        out.extend(pt.get("payload") or {} for pt in res.get("points", []))
        offset = res.get("next_page_offset")
        if not offset:
            break
    return out


NEG = [
    "Mennyi a szállítási idő?",
    "Hogyan tudok visszaküldeni egy terméket?",
    "Milyen garancia jár a termékekre?",
    "Van bolti átvétel?",
    "Elfogadtok utánvétet?",
    "Élő ügyintézővel szeretnék beszélni",
    "Élő ügyintézőt kérek",
    "Mi a top 3 ajánlatod?",
    "Prémium tagságot szeretnék",
    "Orsóhoz van alkatrész?",
    "Kaphatok számlát a rendelésről?",
    "Hol van a boltotok?",
    "Mikor vagytok nyitva?",
    "Szeretnék egy árajánlatot kérni",
    "Nem kaptam meg a csomagom",
    "Hogyan tudok regisztrálni?",
    "Van részletfizetési lehetőség?",
    "Mennyibe kerül a kiszállítás Budapestre?",
    "Küldjetek egy visszaigazolást a vitox98@t-online.hu címre",
    "Írjatok a kapcsolat@valami.hu email címre",
    "Jó napot kívánok!",
    "Köszönöm a segítséget",
    "Milyen fizetési módok vannak?",
    "Cserélhető a termék, ha nem jó a méret?",
    "Mennyi az 1000 Ft feletti kedvezmény?",
    "Van ingyenes szállítás?",
    "Meddig tart a jótállás?",
    "Kaphatok kedvezményt nagyobb rendelésnél?",
    "Hol tudom követni a rendelésem?",
    "Melyik a legolcsóbb termék nálatok?",
]


def main():
    from app.services.paramextract import _BRANDS
    manrx = {b: re.compile(r"\b" + re.escape(b) + r"\b") for b in _BRANDS}

    def detect_old(fm):
        for b in _BRANDS:
            if manrx[b].search(fm):
                return b
        return ""

    qs = {}
    with open(QTSV, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if "\t" not in ln:
                continue
            cid, q = ln.split("\t", 1)
            if q.strip():
                qs.setdefault(cid.strip(), set()).add(q.strip())

    clients = sorted(set(qs) | set(json.load(open(CLIENTS))))

    inv_all, kb_all = {}, {}
    for cid in clients:
        inv = {}
        for p in scroll(cid, ["brand", "available", "stock"], True):
            b = str(p.get("brand") or "").strip()
            if not b:
                continue
            av = p.get("available")
            if av is None:
                av = p.get("stock")
            d = inv.setdefault(b, [0, 0])
            d[0] += 1
            d[1] += 1 if av else 0
        if inv:
            inv_all[cid] = inv
        kb_all[cid] = fold(" ".join(str(p.get("text") or "")
                                    for p in scroll(cid, ["text"], False)))

    # --- kereszt-tenant df (csak a ROVID kulcsokra van rá szükség) ---
    allkeys = set()
    for inv in inv_all.values():
        for b in inv:
            for k in keyform(b):
                if len(k) >= _MIN_LEN and k not in _STOP:
                    allkeys.add(k)
    df = {}
    for k in allkeys:
        if len(k) > _SHORT_MAX:
            df[k] = set()
            continue
        rx = re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])")
        df[k] = {cid for cid, t in kb_all.items() if t and rx.search(t)}

    # --- szótár-építés tenantonként ---
    maps, drops_all = {}, {}
    for cid, inv in inv_all.items():
        keys, drops = {}, {}
        for b, (n, av) in inv.items():
            for k in keyform(b):
                if len(k) < _MIN_LEN:
                    drops.setdefault(b, "rovid(<%d)" % _MIN_LEN)
                    continue
                if k in _STOP:
                    drops[b] = "H1 stop"
                    continue
                own = 1 if cid in df.get(k, ()) else 0
                if len(k) <= _SHORT_MAX and len(df.get(k, ())) - own >= _DF_MIN:
                    drops[b] = "H3 koznyelvi (df=%d)" % (len(df.get(k, ())) - own)
                    continue
                e = keys.setdefault(k, {"vals": [], "n": 0, "av": 0})
                if b not in e["vals"]:
                    e["vals"].append(b)
                e["n"] += n
                e["av"] += av
        maps[cid] = keys
        drops_all[cid] = drops

    print("=" * 100)
    print("A) SZOTAR (H1 stop + H3 rovid<=%d ES df>=%d)" % (_SHORT_MAX, _DF_MIN))
    print("=" * 100)
    for cid in sorted(maps):
        d = drops_all[cid]
        print("  [%-16s] kulcs=%4d | kiejtve=%d %s"
              % (cid, len(maps[cid]), len(d),
                 ("-> " + "; ".join("%s (%s)" % (k, v) for k, v in sorted(d.items()))) if d else ""))
    mw = max((len(k.split()) for m in maps.values() for k in m), default=0)
    print("  leghosszabb kulcs szo-szama: %d  (_MAX_WORDS=%d)" % (mw, _MAX_WORDS))

    print()
    print("=" * 100)
    print("B) DIFF a VALODI kerdes-korpuszon (mai _BRANDS vs javasolt szotar)")
    print("=" * 100)
    tot_same = tot_new = tot_lost = tot_chg = 0
    newkey_freq = {}
    for cid in sorted(qs):
        keys = maps.get(cid) or {}
        if not keys:
            continue
        same = new = lost = chg = 0
        pairs = {}
        for q in qs[cid]:
            f = fold(q)
            old = detect_old(f)
            best = detect(f, keys)
            if best == old or (best and old and (best.startswith(old) or old.startswith(best))):
                same += 1
                continue
            if not old and best:
                new += 1
                newkey_freq[best] = newkey_freq.get(best, 0) + 1
            elif old and not best:
                lost += 1
            else:
                chg += 1
            pairs.setdefault((old or "-", best or "-"), []).append(q)
        tot_same += same
        tot_new += new
        tot_lost += lost
        tot_chg += chg
        print("  [%-16s] azonos %4d | UJ %3d | ELVESZETT %2d | VALTOZOTT %2d"
              % (cid, same, new, lost, chg))
        for (o, nk), qq in sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:6]:
            print("       %-14s -> %-22s %3d db | %s"
                  % (o, nk, len(qq), qq[0][:56].replace("\n", " ")))
        for (o, nk), qq in sorted(pairs.items()):
            if o != "-" :
                print("       !! REGRESSZIO-JELOLT %-12s -> %-18s %3d db | %s"
                      % (o, nk, len(qq), qq[0][:56].replace("\n", " ")))
    print("  OSSZESEN: azonos %d | UJ %d | ELVESZETT %d | VALTOZOTT %d"
          % (tot_same, tot_new, tot_lost, tot_chg))

    print()
    print("=" * 100)
    print("C) UJ FELISMERESEK gyakorisag szerint (kezi FP-atnezesre)")
    print("=" * 100)
    for k, n in sorted(newkey_freq.items(), key=lambda kv: (-kv[1], kv[0])):
        print("   %4d  %s" % (n, k))

    print()
    print("=" * 100)
    print("D) NEGATIV KORPUSZ (elvart: 0 markafelismeres) minden tenant szotaraval")
    print("=" * 100)
    fp = 0
    for cid in sorted(maps):
        for q in NEG:
            b = detect(fold(q), maps[cid])
            if b:
                fp += 1
                print("   FP [%s] %-28s <- %s" % (cid, b, q))
    print("   FP osszesen: %d / %d par" % (fp, len(maps) * len(NEG)))

    print()
    print("=" * 100)
    print("E) RECALL: a mai 26 kezi marka felismerese az UJ szotarral (notebookstore)")
    print("=" * 100)
    keys = maps.get("notebookstore") or {}
    miss = []
    for b in _BRANDS:
        if not detect(fold("Van %s termeketek?" % b), keys):
            miss.append(b)
    print("   felismert %d/%d | hianyzik: %s" % (len(_BRANDS) - len(miss), len(_BRANDS),
                                                 ", ".join(miss) or "-"))

    print()
    print("=" * 100)
    print("F) NYERESEG: elerheto termekek a szotar altal lefedve")
    print("=" * 100)
    for cid in sorted(maps):
        keys = maps[cid]
        av_new = sum(e["av"] for e in keys.values())
        av_old = 0
        for k, e in keys.items():
            if any(re.search(r"\b" + re.escape(b) + r"\b", k) for b in _BRANDS):
                av_old += e["av"]
        tot = sum(v[1] for v in inv_all[cid].values())
        print("   [%-16s] marka=%4d | elerheto lefedve: mai %5d -> uj %5d (osszes elerheto %5d)"
              % (cid, len(keys), av_old, av_new, tot))


main()

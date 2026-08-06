"""m82h/2 MÉRÉS 4 — a higiénia-kapuk JAVÍTOTT változata.

A 3. mérés két hibát mutatott:
  - H2 (URL-kivágás) TÚL SOKAT vitt: a beillesztett termék-URL ÚTVONALÁBAN
    ott a márka ("copygo.hu/xiaomi-mesh-system…"), és azt ma felismerjük.
    JAVÍTÁS: csak a HOST-ot és az e-mail címet vágjuk ki, az útvonal-tokeneket
    szóközzel elválasztva MEGTARTJUK.
  - H3 (KB-próza kapu) a fishingoutlet 443 márkájából 257-et kiejtett, mert
    annak a KB-je TERMÉKLISTÁKAT tartalmaz, nem prózát -> valódi márkák estek ki.
    JAVÍTÁS: KERESZT-TENANT kapu — a kulcs csak akkor köznyelvi szó, ha
    LEGALÁBB K MÁSIK tenant KB-jében is előfordul (egy márka ott jelenik meg,
    ahol árulják; egy magyar köznyelvi szó mindenhol). Mérve K=2 és K=3-mal.

Futtatás: docker exec -i chatbot-api-prod python - < tools/m82h2_hyg2.py
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

STOP = {"egyeb", "other", "n/a", "na", "nincs", "ismeretlen", "no name", "noname",
        "general", "generic", "univerzalis"}

_RE_MAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\b")
_RE_URL = re.compile(r"(?:https?://|www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:hu|com|net|org|eu|io))(/\S*)?")


def clean(fm):
    """e-mail: ki; URL: a HOST ki, az utvonal tokenekre bontva marad."""
    fm = _RE_MAIL.sub(" ", fm)

    def _u(m):
        path = m.group(2) or ""
        return " " + re.sub(r"[^a-z0-9]+", " ", path) + " "
    return _RE_URL.sub(_u, fm)


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

    clients = sorted(set(qs) | set(json.load(open("/app/data/m82h2_clients.json"))))

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

    # --- kereszt-tenant kozneves-kapu: hany MASIK tenant KB-jeben fordul elo ---
    allkeys = set()
    for inv in inv_all.values():
        for b in inv:
            for k in keyform(b):
                if k and len(k) >= 2 and k not in STOP:
                    allkeys.add(k)
    df = {}
    for k in allkeys:
        rx = re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])")
        df[k] = {cid for cid, t in kb_all.items() if t and rx.search(t)}

    print("=" * 100)
    print("KERESZT-TENANT KOZNEVES-KAPU: kulcs -> hany tenant KB-jeben szerepel")
    print("=" * 100)
    for k in sorted(allkeys, key=lambda k: (-len(df[k]), k)):
        if len(df[k]) >= 2:
            print("  %-26s %d tenant KB: %s" % (k, len(df[k]), ",".join(sorted(df[k]))))

    for K in (2, 3):
        print()
        print("=" * 100)
        print("DIFF (H1 STOP + H2' host/mail-kivagas + H3' kereszt-tenant kapu K=%d)" % K)
        print("=" * 100)
        tot_same = tot_diff = 0
        dropped_tot = 0
        for cid, inv in inv_all.items():
            keys = {}
            drops = []
            for b, (n, av) in inv.items():
                for k in keyform(b):
                    if not k or len(k) < 2 or k in STOP:
                        continue
                    own = 1 if cid in df.get(k, ()) else 0
                    if len(df.get(k, ())) - own >= K:
                        drops.append(b)
                        continue
                    keys.setdefault(k, 0)
                    keys[k] += av
            dropped_tot += len(drops)
            corpus = qs.get(cid) or set()
            if not corpus:
                continue
            rx = {k: re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])") for k in keys}
            same, diffs = 0, {}
            for q in corpus:
                fm = clean(fold(q))
                best = ""
                for k, r in rx.items():
                    if r.search(fm) and len(k) > len(best):
                        best = k
                old = detect_old(fold(q))
                if best == old or (best and old and (best.startswith(old) or old.startswith(best))):
                    same += 1
                else:
                    diffs.setdefault((old or "-", best or "-"), []).append(q)
            tot_same += same
            tot_diff += sum(len(v) for v in diffs.values())
            print("  [%-16s] kulcs=%3d (kiejtve %d) | azonos %d | elteres %d%s"
                  % (cid, len(keys), len(drops), same, sum(len(v) for v in diffs.values()),
                     ("  KIEJTVE: " + ",".join(sorted(set(drops))[:10])) if drops else ""))
            for (old, new), qq in sorted(diffs.items(), key=lambda kv: -len(kv[1]))[:8]:
                print("       %-12s -> %-20s %3d db | %s" % (old, new, len(qq), qq[0][:56].replace("\n", " ")))
        print("  OSSZESEN: azonos %d | elteres %d | kiejtett marka-ertek %d"
              % (tot_same, tot_diff, dropped_tot))


main()

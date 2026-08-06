"""m82h/2 MÉRÉS 3 — a márkaszótár HIGIÉNIÁJA (attribútum-osztály szintű kapuk).

A 2. mérés kimutatta: a jelölt szótár a saját korpuszon 207 ÚJ márkafelismerést
hoz (a mai kézi lista 8 tenanton 0%-ot ér el), de köztük valódi FP-k is vannak,
és ezek OSZTÁLYBA sorolhatók (m82g tanulság: ne érték-feketelista, hanem
osztály-szabály):

  H1  STOP-értékek           "Egyéb", "No name" — töltelék brand-érték
  H2  e-mail / URL kivágás   "vitox98@t-online.hu" -> a `hu` márka illeszkedett
  H3  KÖZNYELVI-SZÓ KAPU     ha a kulcs a bolt SAJÁT KB-prózájában (nem termék
                             típusú chunkok) is előfordul, akkor köznyelvi szó,
                             nem megkülönböztető márka-token ("élő" -> Elo,
                             "alkatrész" -> Alkatresz). ADAT-VEZÉRELT, nem lista.

Ez a script MÉRI a három kaput: mit ejt ki, és mi marad a diffben.
Futtatás: docker exec -i chatbot-api-prod python - < tools/m82h2_hygiene.py
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
        "general", "generic", "univerzalis", "alkatresz", "egyeb termekek"}

_RE_MAIL = re.compile(r"\S+@\S+|https?://\S+|www\.\S+|\b[a-z0-9-]+\.(?:hu|com|net|org|eu)\b")


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
    print("=" * 100)
    print("A KAPUK HATASA TENANTONKENT")
    print("=" * 100)

    keep_all = {}
    for cid in clients:
        prods = scroll(cid, ["brand", "available", "stock", "name"], True)
        if not prods:
            continue
        inv = {}
        for p in prods:
            b = str(p.get("brand") or "").strip()
            if not b:
                continue
            av = p.get("available")
            if av is None:
                av = p.get("stock")
            d = inv.setdefault(b, [0, 0])
            d[0] += 1
            d[1] += 1 if av else 0

        kb = scroll(cid, ["text"], False)
        kbtext = fold(" ".join(str(p.get("text") or "") for p in kb))

        keys = {}
        drop_stop, drop_kb = [], []
        for b, (n, av) in inv.items():
            for k in keyform(b):
                if not k or len(k) < 2:
                    continue
                if k in STOP:
                    drop_stop.append("%s(%d)" % (b, av))
                    continue
                if kbtext and re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", kbtext):
                    drop_kb.append("%s(%d)" % (b, av))
                    continue
                e = keys.setdefault(k, {"vals": set(), "av": 0})
                e["vals"].add(b)
                e["av"] += av
        keep_all[cid] = keys
        print("  [%-16s] brand=%3d  megtartott kulcs=%3d  | STOP: %s | KB-KOZNYELVI (%d db): %s"
              % (cid, len(inv), len(keys), ",".join(drop_stop) or "-",
                 len(drop_kb), ",".join(sorted(drop_kb)[:14]) or "-"))

    print()
    print("=" * 100)
    print("DIFF A SAJAT KORPUSZON A HAROM KAPUVAL (v3)")
    print("=" * 100)
    tot_same = tot_diff = 0
    for cid, keys in keep_all.items():
        corpus = qs.get(cid) or set()
        if not corpus:
            continue
        rx = {}
        for k in keys:
            rx[k] = re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])")
        same, diffs = 0, {}
        for q in corpus:
            fm = _RE_MAIL.sub(" ", fold(q))          # H2
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
        if diffs:
            print("  [%s] azonos %d | uj/elteres %d" % (cid, same, sum(len(v) for v in diffs.values())))
            for (old, new), qq in sorted(diffs.items(), key=lambda kv: -len(kv[1])):
                print("     %-12s -> %-22s %3d db | %s" % (old, new, len(qq), qq[0][:64].replace("\n", " ")))
    print()
    print("  OSSZESEN: azonos %d | elteres %d" % (tot_same, tot_diff))


main()

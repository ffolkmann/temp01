"""m85/1 ELOMERES: NYELVI RES — magyar kerdes vs. terméknev szokincse.

A m82h/3 hagyta nyitva: "Xiaomi okosora" nem javul, mert a termeknev angol
(`Watch`); "szaraz tap" vs `szarazeledel`. Kerdes: HANY valodi kerdest erint?

Ket merteket nezunk kerdesenkent (rerank utani top-8 termekei):
  A) LEXIKAI VAKSAG: a kerdes egyetlen tartalmas tokenje sem fordul elo a
     kontextus TERMEKNEVEIBEN -> a rerank lexikai jele nem tudott dolgozni.
  B) ISMERETLEN SZO: a kerdes tokenje a tenant TELJES terméknev-szokincseben
     sem szerepel -> ha van ra termek, csak mas neven van (ez a szotar-jelolt).
Kulon nezzuk a `text` (leiras) szokincset is: ha a szo ott megvan, a res kisebb.

Csak olvas. Futtatas:
  docker exec -i chatbot-api-prod python - < tools/m85_langgap.py
"""
import asyncio
import json
import sys
import unicodedata
import urllib.request

sys.path.insert(0, "/app")

from app.services.policy_filter import _is_product, is_policy_query  # noqa: E402
from app.services.retrieval import retrieve  # noqa: E402

QFILE = "/app/data/m82i_q.txt"
Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"
PER_TENANT = 55
VOCAB_PAGES = 40

STOP = set("""
hogy mint ilyen olyan amit amit ezek azok vagy meg csak most mar nagyon lehet kell
kellene tudsz tudna tudok szeretnek keresek keresem erdekel erdekelne ajanlj ajanlasz
milyen mennyi mikor hogyan hova honnan miert melyik mennyibe kerul koszonom koszi szia
udvozlom kerem legyen szives lenne nektek nalatok van vannak volt lesz elerheto raktaron
keszleten termek termeket termekek bolt boltban webshop webaruhaz oldal oldalon rendeles
rendelni vasarolni venni kaphato szallitas szallitasi ara arak arat forint jo jobb legjobb
kicsit tobb kevesebb esetleg persze igen nem talan pedig azert ezert ugyan sajnos
""".split())


def fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c))


def toks(s, minlen=4):
    out, cur = [], []
    for ch in fold(s):
        if ch.isalnum():
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return [t for t in out if len(t) >= minlen and not t.isdigit() and t not in STOP]


def post(path, body, timeout=180):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def vocab(cid):
    """A tenant terméknev- es leiras-szokincse (fold-olt tokenek)."""
    names, texts = set(), set()
    offset = None
    for _ in range(VOCAB_PAGES):
        body = {"filter": {"must": [{"key": "client_id", "match": {"value": cid}},
                                    {"key": "type", "match": {"value": "product"}}]},
                "limit": 1000, "with_payload": ["name", "text"], "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % COLL, body)["result"]
        for pt in res.get("points", []):
            p = pt.get("payload") or {}
            names.update(toks(p.get("name")))
            texts.update(toks(p.get("text")))
        offset = res.get("next_page_offset")
        if not offset:
            break
    return names, texts


async def main():
    rows = []
    with open(QFILE, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if "|" in ln:
                cid, q = ln.split("|", 1)
                if len(q.strip()) >= 8:
                    rows.append((cid.strip(), q.strip()))

    per_cid = {}
    for cid, q in rows:
        d = per_cid.setdefault(cid, [])
        if len(d) < PER_TENANT and q not in d:
            d.append(q)

    total_prod = total_blind = 0
    unknown_all = {}

    for cid, qs in sorted(per_cid.items()):
        nvocab, tvocab = vocab(cid)
        n = blind = 0
        blind_ex = []
        unknown = {}
        for q in qs:
            if is_policy_query(q):
                continue
            qt = toks(q)
            if not qt:
                continue
            try:
                hits, _s, _m = await retrieve(q, q, cid)
            except Exception as e:  # noqa: BLE001
                print("  HIBA [%s] %s -> %s" % (cid, q[:40], str(e)[:60]))
                continue
            prods = [h for h in hits if _is_product(h)]
            if not prods:
                continue
            n += 1
            ctx = set()
            for h in prods:
                ctx.update(toks((h.get("payload") or {}).get("name")))
            if not (set(qt) & ctx):
                blind += 1
                if len(blind_ex) < 10:
                    miss = [t for t in qt if t not in nvocab]
                    blind_ex.append((q, sorted(set(qt))[:6], miss[:4]))
            for t in set(qt):
                if t not in nvocab:
                    unknown[t] = unknown.get(t, 0) + 1
                    unknown_all[t] = unknown_all.get(t, 0) + 1

        total_prod += n
        total_blind += blind
        print("=" * 100)
        print("[%s] termek-kerdes: %d | LEXIKAILAG VAK (0 atfedes a top-8 neveivel): %d (%.0f%%)"
              % (cid, n, blind, 100.0 * blind / max(n, 1)))
        print("  terméknev-szokincs: %d token | leiras-szokincs: %d token"
              % (len(nvocab), len(tvocab)))
        for q, qtk, miss in blind_ex:
            print("    VAK: %-52s tokenek=%s" % (q[:52], qtk))
            if miss:
                print("         a NEV-szokincsben sincs: %s%s"
                      % (miss, "  (de a leirasban VAN: %s)"
                         % [m for m in miss if m in tvocab] if any(m in tvocab for m in miss) else ""))
        top = sorted(unknown.items(), key=lambda kv: -kv[1])[:14]
        print("  a terméknevekben ISMERETLEN kerdes-szavak (szotar-jeloltek): %s"
              % ", ".join("%s(%d)" % (k, v) for k, v in top))

    print()
    print("=" * 100)
    print("OSSZESEN: %d termek-kerdes, ebbol lexikailag vak %d (%.0f%%)"
          % (total_prod, total_blind, 100.0 * total_blind / max(total_prod, 1)))
    print("Leggyakoribb ismeretlen kerdes-szavak minden tenanton:")
    for k, v in sorted(unknown_all.items(), key=lambda kv: -kv[1])[:30]:
        print("   %-22s %d" % (k, v))

    print()
    print("=" * 100)
    print("KONTROLL-ESETEK (a m82h/3 nyitott peldai)")
    for cid, q in [("copygo", "Xiaomi okosóra érdekelne"),
                   ("nagyonallatshop", "Whiskas száraz tápot kerestek?"),
                   ("notebookstore", "Van olcsó laptopotok?")]:
        hits, _s, _m = await retrieve(q, q, cid)
        print("-" * 100)
        print("[%s] %s" % (cid, q))
        for h in hits:
            if _is_product(h):
                p = h.get("payload") or {}
                print("    %s" % str(p.get("name"))[:78])


asyncio.run(main())

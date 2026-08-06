"""m82h/3 DIAGNOZIS: marka-szurt pool + altipus.

Kerdes: a marka-szures jol fut (m82h/2), de a valasz megis "nincs ilyen" —
hol vesz el az altipus? A poolban nincs benne (limit-problema), vagy a
rerank nem hozza fel (rangsor-problema)?

Merjuk esetenkent: dense pool 30 / 100 / 300 / 1000 a brand must-tal, es
minden pool-meretre a rerank utani top-8. Az "altipus-talalat" a termeknevben
levo kulcsszo (fold-olt).

Futtatas: docker exec -i chatbot-api-prod python - < tools/m82h3_diag.py
"""
import asyncio
import sys
import unicodedata

sys.path.insert(0, "/app")

from app.core.embeddings import embed_query  # noqa: E402
from app.core.qdrant import get_qdrant  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.services.paramextract import build_filter_conditions, detect_constraints  # noqa: E402
from app.services.policy_filter import policy_embed_input  # noqa: E402
from app.services.query_cleanup import product_query_cleanup  # noqa: E402
from app.services.rerank import rerank  # noqa: E402

S = get_settings()

CASES = [
    ("fishingoutlet", "Milyen Delphin sátratok van?", ["sator"]),
    ("nagyonallatshop", "Whiskas száraz tápot kerestek?", ["szaraz"]),
    ("kellegyszerszam", "Ryobi akkus fúrót keresek", ["furo"]),
    ("copygo", "Xiaomi okosóra érdekelne", ["watch", "okosora", "smart band", "band"]),
    ("notebookstore", "Milyen HP tintapatronotok van?", ["tintapatron"]),
    ("fishingoutlet", "Carp Expert bototok van?", ["bot"]),
]

LIMITS = [30, 100, 300, 1000]


def fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c))


def is_hit(p, words):
    n = fold(p.get("payload", {}).get("name"))
    return any(w in n for w in words)


def avail(p):
    pl = p.get("payload", {}) or {}
    a = pl.get("available")
    return bool(pl.get("stock")) if a is None else bool(a)


async def main():
    q = get_qdrant()
    for cid, msg, words in CASES:
        cons = detect_constraints(msg, cid)
        must = build_filter_conditions(cons)
        vector = await embed_query(policy_embed_input(msg, product_query_cleanup(msg)))
        print("=" * 100)
        print("[%s] %s" % (cid, msg))
        print("   brand=%s vals=%s | altipus-szavak=%s"
              % (cons.get("brand") or "-", cons.get("brand_vals") or "-", words))
        if not must:
            print("   NINCS marka-szuro -- kihagyva")
            continue
        for lim in LIMITS:
            hits = await q.search(vector=vector, client_id=cid, limit=lim,
                                  product_only=False, extra_must=must)
            h = [i for i, p in enumerate(hits, 1) if is_hit(p, words)]
            ha = [i for i, p in enumerate(hits, 1) if is_hit(p, words) and avail(p)]
            rr = rerank(msg, hits, top_n=S.context_top_n)
            rh = [p for p in rr if is_hit(p, words)]
            print("   limit=%4d | pool=%4d | altipus a poolban=%3d (elerheto %3d) legjobb rank=%s"
                  " | RERANK top-%d: altipus=%d"
                  % (lim, len(hits), len(h), len(ha), (h[0] if h else "-"),
                     len(rr), len(rh)))
            if lim == LIMITS[-1]:
                print("      rerank top-%d nevei:" % len(rr))
                for p in rr:
                    pl = p.get("payload", {}) or {}
                    print("        %s %s | %s Ft" % ("*" if is_hit(p, words) else " ",
                                                     str(pl.get("name"))[:66], pl.get("price")))


asyncio.run(main())

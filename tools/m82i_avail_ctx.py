"""m82i/3 ELOMERES az `available` alapertelmezeshez (handoff 3.4/4).

Kerdes: a mai ELES retrieval-lanc vegen (rerank top-8 kontextus) hany %-ban van
NEM elerheto termek? Ha a modell csak ebbol valaszthat, kifutot ajanlhat.
A m64 `needs_available_boost` csak akkor foltoz, ha EGY elerheto sincs.

Elerhetoseg: `available` ha van, kulonben `stock` > 0 (a m82h3_diag mintaja).

Bemenet: /app/data/m82i_q.txt sorai "<client_id>|<kerdes>".
Futtatas:  docker exec -i chatbot-api-prod python - < tools/m82i_avail_ctx.py
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from app.core.embeddings import embed_query  # noqa: E402
from app.core.qdrant import get_qdrant  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.services.policy_filter import _is_product, is_policy_query, policy_embed_input  # noqa: E402
from app.services.query_cleanup import product_query_cleanup  # noqa: E402
from app.services.retrieval import retrieve  # noqa: E402

S = get_settings()
QFILE = "/app/data/m82i_q.txt"
PER_TENANT = 40


def avail(h):
    pl = h.get("payload") or {}
    a = pl.get("available")
    if a is None:
        try:
            return float(pl.get("stock") or 0) > 0
        except Exception:  # noqa: BLE001
            return False
    return bool(a)


async def main():
    rows = []
    with open(QFILE, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if "|" not in ln:
                continue
            cid, q = ln.split("|", 1)
            cid, q = cid.strip(), q.strip()
            if len(q) < 8:
                continue
            rows.append((cid, q))

    per_cid = {}
    for cid, q in rows:
        d = per_cid.setdefault(cid, [])
        if len(d) < PER_TENANT and q not in d:
            d.append(q)

    qdrant = get_qdrant()
    print("korpusz: %d sor, tenantok: %s"
          % (len(rows), {k: len(v) for k, v in per_cid.items()}))
    print()

    for cid, qs in sorted(per_cid.items()):
        stat = {"n": 0, "policy": 0, "noprod": 0, "prod": 0, "prod_av": 0,
                "ctx_all_oos": 0, "ctx_has_oos": 0, "ctx_clean": 0, "alt_empty": 0}
        worst = []
        for q in qs:
            if is_policy_query(q):
                stat["policy"] += 1
                continue
            stat["n"] += 1
            try:
                hits, _score, _mode = await retrieve(q, q, cid)
            except Exception as e:  # noqa: BLE001
                print("  HIBA [%s] %s -> %s" % (cid, q[:50], str(e)[:70]))
                continue
            prods = [h for h in hits if _is_product(h)]
            if not prods:
                stat["noprod"] += 1
                continue
            av = [h for h in prods if avail(h)]
            stat["prod"] += len(prods)
            stat["prod_av"] += len(av)
            if not av:
                stat["ctx_all_oos"] += 1
            elif len(av) < len(prods):
                stat["ctx_has_oos"] += 1
            else:
                stat["ctx_clean"] += 1
            if len(av) < len(prods):
                # van-e mivel helyettesiteni? available-szurt termek-pool ugyanarra a temara
                try:
                    vec = await embed_query(policy_embed_input(q, product_query_cleanup(q)))
                    alt = await qdrant.search(vector=vec, client_id=cid,
                                              limit=S.retrieval_top_k,
                                              product_only=True, available_only=True)
                except Exception:  # noqa: BLE001
                    alt = []
                if not alt:
                    stat["alt_empty"] += 1
                if len(worst) < 6:
                    worst.append((q, len(prods), len(av), len(alt)))

        n = max(stat["n"] - stat["noprod"], 1)
        print("=" * 100)
        print("[%s] termek-kerdes: %d (policy kihagyva: %d, termek nelkuli kontextus: %d)"
              % (cid, stat["n"], stat["policy"], stat["noprod"]))
        print("  kontextus-termekek: %d, ebbol ELERHETO: %d (%.0f%%)"
              % (stat["prod"], stat["prod_av"],
                 100.0 * stat["prod_av"] / max(stat["prod"], 1)))
        print("  kerdesek: tiszta (mind elerheto) %d (%.0f%%) | vegyes %d (%.0f%%) |"
              " MIND KIFUTO %d (%.0f%%)"
              % (stat["ctx_clean"], 100.0 * stat["ctx_clean"] / n,
                 stat["ctx_has_oos"], 100.0 * stat["ctx_has_oos"] / n,
                 stat["ctx_all_oos"], 100.0 * stat["ctx_all_oos"] / n))
        print("  available-szurt alternativ pool URES: %d esetben"
              " (ilyenkor a szures csak rontana)" % stat["alt_empty"])
        for q, np_, na, nalt in worst:
            print("    pelda: %-58s termek=%d elerheto=%d alt-pool=%d"
                  % (q[:58], np_, na, nalt))


asyncio.run(main())

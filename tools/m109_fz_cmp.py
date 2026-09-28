"""m109 elotte/utana: a valodi keresesek (ss_search + session utolso ss_q, 120 nap) searchq.search
eredmenye. Kozvetlen hivas (nincs ss_q esemeny). python fz_cmp.py <tenant> <out.json>
A lekerdezes-lista mindket futasnal azonos (DB-bol, rendezve)."""
import asyncio
import json
import os
import sys

T, OUT = sys.argv[1], sys.argv[2]


async def main():
    import asyncpg
    import httpx
    from app.core.settings import get_settings
    from app.services import searchq as sq
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    con = await asyncpg.connect(url)
    rows = await con.fetch(
        "select distinct q from ("
        " select meta->>'q' q from events where client_id=$1 and kind='ss_search' and created_at > now()-interval '120 days'"
        " union all select q from (select distinct on (session_id) meta->>'q' q from events where client_id=$1"
        "  and kind='ss_q' and created_at > now()-interval '120 days' order by session_id, created_at desc) x"
        ") y where q is not null and length(q) > 1 order by q", T)
    cfg = json.loads(await con.fetchval("select search_config::text from tenants where client_id=$1", T))
    await con.close()
    cl = httpx.AsyncClient(base_url=str(get_settings().qdrant_url).rstrip("/"), timeout=30)
    res = {}
    for r in rows:
        q = r["q"]
        try:
            d = await sq.search(cl, cfg, T, q, limit=3)
            res[q] = {"total": d.get("total"), "mode": d.get("mode"), "fz": d.get("fuzzy"),
                      "top": [h.get("n", "")[:70] for h in d.get("hits") or []]}
        except Exception as e:  # noqa: BLE001
            res[q] = {"err": repr(e)[:100]}
    await cl.aclose()
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("queries", len(res))


asyncio.run(main())

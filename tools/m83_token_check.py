"""m83 eles ellenorzes: tenyleg cache-el-e a token, es single-flight-e.

Futtatas: docker exec -i chatbot-api-prod python - < tools/m83_token_check.py
Nem modosit semmit. Valodi Shoprenter token-vegpontot hiv, tenantonkent EGYSZER.
"""
import asyncio
import sys
import time

sys.path.insert(0, "/app")

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.db_models import Tenant  # noqa: E402
from app.services import platform_api as pa  # noqa: E402


def _name(t):
    for attr in ("client_id", "slug", "name", "id"):
        v = getattr(t, attr, None)
        if v:
            return str(v)
    return "?"


async def main():
    async with SessionLocal() as db:
        rows = (await db.execute(select(Tenant))).scalars().all()
    srs = [t for t in rows if str(getattr(t, "platform", "") or "").lower() == "shoprenter"]
    print("Shoprenter tenantok:", ", ".join(_name(t) for t in srs) or "(nincs)")
    print()
    print("%-16s %-6s %-9s %-10s %-12s %-10s" % (
        "tenant", "token", "1. hivas", "2. hivas", "5 parhuzamos", "jwt_ttl"))
    print("-" * 72)

    async with httpx.AsyncClient(timeout=20.0) as c:
        for t in srs:
            nm = _name(t)
            try:
                shop = pa.shoprenter_shop(str(getattr(t, "api_base", "") or ""))
                cid = str(getattr(t, "api_client_id", "") or "")
                sec = str(getattr(t, "api_client_secret", "") or "")
                if not (shop and cid and sec):
                    print("%-16s HIANYZO CREDENTIAL/api_base" % nm)
                    continue

                t0 = time.monotonic()
                tok1 = await pa.shoprenter_token(c, shop, cid, sec)
                d1 = time.monotonic() - t0

                t0 = time.monotonic()
                tok2 = await pa.shoprenter_token(c, shop, cid, sec)
                d2 = time.monotonic() - t0

                t0 = time.monotonic()
                res = await asyncio.gather(*[
                    pa.shoprenter_token(c, shop, cid, sec) for _ in range(5)
                ])
                d3 = time.monotonic() - t0

                same = (tok1 == tok2) and len(set(res)) == 1 and res[0] == tok1
                ttl = pa._sr_jwt_ttl(tok1)
                print("%-16s %-6s %-9.3f %-10.5f %-12.5f %-10.0f %s" % (
                    nm, "OK" if tok1 else "URES", d1, d2, d3, ttl,
                    "cache OK" if same and d2 < max(d1 / 5, 0.001) else "!! NEM CACHE-EL"))
            except Exception as e:  # noqa: BLE001
                print("%-16s HIBA: %s: %s" % (nm, type(e).__name__, str(e)[:70]))

    print()
    print("cache-bejegyzesek:", len(pa._SR_TOKEN_CACHE))
    for (shop, cid), (_tok, exp) in pa._SR_TOKEN_CACHE.items():
        print("  %-24s lejar %.0f mp mulva" % (shop, exp - time.monotonic()))


asyncio.run(main())

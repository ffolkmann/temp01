"""CX SmartSearch sync CLI — python -m app.search --tenant <client_id> | --all [--out DIR]

Tenantonkent statikus kereso-indexet epit a webrootba (index/params/manifest.json).
A tenant-lista es a credentialek a kozos tenants tablabol jonnek (mint az
app.sync-nel); hogy MELYIK tenantra fut, azt a data/smartsearch.json kapcsolja:

    {"tenants": {"teslashop": {"enabled": true, "min_ratio": 0.5, "only_available": true}}}

Futtatas a cx-sync mintajara, kulon out-mounttal (az app a kepben NINCS friss,
ezert a repo app-jat is mountoljuk):

  docker compose -f docker-compose.prod.yml run --rm \
    -v /docker/chatbot-prod/app:/app/app -v /root/weboldal_fajlok/cx-search:/out \
    api python -m app.search --all --out /out

Hiba-izolacio: tenantonkent try/except — egy tenant hibaja nem allitja meg a
tobbit; hibanal a regi index marad, a manifest error-t kap (indexcore).
Portolt platformok: sellvio (S1), shoprenter (K1), webdoc (S4); a tobbi "nincs portolva" skippel.
"""
import argparse
import asyncio
import json
import os

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.db_models import Tenant
from app.search import indexcore, sellvio, shoprenter, unas, webdoc

CONFIG_PATH = os.environ.get("SS_CONFIG", "data/smartsearch.json")

_FETCHERS = {
    "sellvio": sellvio.fetch,
    "shoprenter": shoprenter.fetch,
    "webdoc": webdoc.fetch,
    "unas": unas.fetch,
}


def load_config(path=None):
    path = path or CONFIG_PATH
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return {}
    tenants = cfg.get("tenants")
    return tenants if isinstance(tenants, dict) else {}


async def run_tenant(tenant, tcfg, out_root):
    client_id = tenant.client_id
    platform = str(tenant.platform or "").strip().lower()
    out_dir = os.path.join(out_root, client_id)
    fetch = _FETCHERS.get(platform)
    if fetch is None:
        return {"client_id": client_id, "platform": platform,
                "skipped": f"platform '{platform}' nincs portolva (sellvio, shoprenter, webdoc, unas)"}
    try:
        products, url_prefix, img_prefix = await fetch(tenant, tcfg)
    except Exception as e:  # noqa: BLE001 — fetch-hiba: regi index marad, manifest error
        indexcore.write_error_manifest(out_dir, client_id, f"fetch: {e}")
        return {"client_id": client_id, "platform": platform, "error": f"fetch: {e}"}
    if not products:
        indexcore.write_error_manifest(out_dir, client_id, "0 forras termek — index nem frissult")
        return {"client_id": client_id, "platform": platform, "error": "0 forras termek"}
    res = indexcore.build_index(
        client_id, products, out_dir, url_prefix, img_prefix,
        only_available=bool(tcfg.get("only_available", True)),
        min_ratio=float(tcfg.get("min_ratio", 0.5)),
    )
    res["platform"] = platform
    return res


def effective_config(tenant, filecfg):
    """s3: az igazsag-forras a tenants.search_config; ures/hianyzo -> data/smartsearch.json."""
    sc = getattr(tenant, "search_config", None)
    if isinstance(sc, dict) and sc:
        return sc
    row = filecfg.get(tenant.client_id)
    return row if isinstance(row, dict) else {}


async def _run(client_id, do_all, out_root):
    filecfg = load_config()
    async with SessionLocal() as session:
        stmt = select(Tenant).where(Tenant.active.is_(True))
        if not do_all:
            stmt = stmt.where(Tenant.client_id == client_id)
        tenants = (await session.execute(stmt)).scalars().all()
    pairs = [(t, effective_config(t, filecfg)) for t in tenants]
    pairs = [(t, c) for t, c in pairs if c.get("enabled")]
    if not pairs:
        print(json.dumps({"error": "nincs egyezo aktiv+enabled tenant"}, ensure_ascii=False))
        return
    for t, cfg in pairs:
        try:
            res = await run_tenant(t, cfg, out_root)
        except Exception as e:  # noqa: BLE001 — vedoernyo: a tenant-loop nem allhat meg
            res = {"client_id": t.client_id, "error": f"unexpected: {e}"}
        print(json.dumps(res, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="CX SmartSearch statikus index-sync")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tenant", help="egy tenant client_id-ja")
    g.add_argument("--all", action="store_true", help="minden enabled tenant")
    ap.add_argument("--out", default="/out", help="kimeneti gyoker (tenantonkent almappa)")
    args = ap.parse_args()
    asyncio.run(_run(args.tenant, args.all, args.out))


if __name__ == "__main__":
    main()

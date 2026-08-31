"""CX SmartSearch sync CLI — python -m app.search --tenant <client_id> | --all [--out DIR]

Tenantonkent statikus kereso-indexet epit a webrootba (index/params/manifest.json).
A tenant-lista es a credentialek a kozos tenants tablabol jonnek (mint az
app.sync-nel); hogy MELYIK tenantra fut, azt a data/smartsearch.json kapcsolja:

    {"tenants": {"teslashop": {"enabled": true, "min_ratio": 0.5, "only_available": true}}}

kfsc/1: opcionalis MASODIK kimenet (konfigurator-index) ugyanabbol a lekert adatbol:

    {"enabled": true, "only_available": true,
     "konf": {"enabled": true, "suffix": "-konf", "only_available": true,
              "scope": [{"param": "technologia", "op": "exists"}]}}

-> <out>/<tenant>/ (teljes, keresonek) es <out>/<tenant>-konf/ (szuk, konfiguratornak).
A `konf` blokk nelkul semmi nem valtozik.

ssq/1: opcionalis HARMADIK kimenet - Qdrant-kollekcio a szerver-oldali keresonek
(GET /search/q, app/search/qdrantout.py), ugyanabbol a lekert adatbol:

    {"enabled": true, "server": {"enabled": true, "only_available": false,
                                "min_ratio": 0.5, "scope": []}}

-> Qdrant alias cx_search_<tenant> + <out>/<tenant>-q/ (manifest.json, vocab.json).
A `server` blokk nelkul semmi nem valtozik.

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
from app.core.settings import get_settings
from app.search import indexcore, qdrantout, sellvio, shoprenter, unas, webdoc

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

    # kfsc/1: OPCIONALIS masodik kimenet szukebb termekkorrel (konfigurator-index).
    # Ugyanabbol a mar lekert `products` listabol epul - NINCS ujabb API-hivas.
    kcfg = tcfg.get("konf")
    if isinstance(kcfg, dict) and kcfg.get("enabled"):
        suffix = str(kcfg.get("suffix") or "-konf").strip() or "-konf"
        kdir = os.path.join(out_root, client_id + suffix)
        try:
            res["konf"] = indexcore.build_index(
                client_id, products, kdir, url_prefix, img_prefix,
                only_available=bool(kcfg.get("only_available", True)),
                min_ratio=float(kcfg.get("min_ratio", 0.5)),
                scope=kcfg.get("scope") or None,
            )
        except Exception as e:  # noqa: BLE001 - a konf-index hibaja NEM viheti el a fo indexet
            indexcore.write_error_manifest(kdir, client_id, f"konf-index: {e}")
            res["konf"] = {"error": f"konf-index: {e}"}

    # ssq/1: OPCIONALIS harmadik kimenet - Qdrant-kollekcio a szerver-oldali keresonek
    # (GET /search/q). Ugyanabbol a `products` listabol, plusz API-hivas nelkul; alapbol
    # only_available=False: a 0 keszletu termek is kereshetove valik, az `a` valodi 0/1.
    scfg = tcfg.get("server")
    if isinstance(scfg, dict) and scfg.get("enabled"):
        qdir = os.path.join(out_root, client_id + qdrantout.SUFFIX)
        try:
            res["server"] = qdrantout.build(
                client_id, products, out_root, url_prefix, img_prefix,
                only_available=bool(scfg.get("only_available", False)),
                min_ratio=float(scfg.get("min_ratio", 0.5)),
                scope=scfg.get("scope") or None,
                qdrant_url=get_settings().qdrant_url,
            )
        except Exception as e:  # noqa: BLE001 - a kereso-profil hibaja NEM viheti el a fo indexet
            indexcore.write_error_manifest(qdir, client_id, f"qdrant-index: {e}")
            res["server"] = {"error": f"qdrant-index: {e}"}
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

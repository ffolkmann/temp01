"""Streamelő platform-adapterek: forrás -> SourceProduct stream (memória-korlátos).

Minden platform egy `stream_<plat>(tenant)` async generátort ad, ami SourceProduct-okat YIELD-el,
anélkül hogy az egész katalógust memóriában tartaná:
 - Sellvio/Woo/Shoprenter (lapozott, nehéz elemek): 2-menetes — pass1 reláció-INDEX (könnyű:
   id->name/url), pass2 újralapozás + build + yield. A nehéz oldalak eldobásra kerülnek.
 - Unas/Webdoc (egy letöltés, könnyű nyers): a blob egyszer letöltve, chunkonként build + yield.

A build_* byte-egyező marad (a builder osztályok index()+build()-je); hibánál (fetch) a stream DOB
-> az engine skippeli a tenantot (NINCS purge).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from app.core.settings import get_settings
from app.services import platform_api as pa
from app.sync.builders import (
    ShoprenterBuilder,
    SellvioBuilder,
    UnasBuilder,
    WebdocBuilder,
    WooBuilder,
    unas_rowdicts,
    webdoc_sorted,
)

if TYPE_CHECKING:
    from app.models.db_models import Tenant

_CHUNK = 200   # egy-blobos források (webdoc/unas) build-chunk mérete


def _creds(tenant):
    return (
        str(tenant.api_base or "").strip(),
        str(tenant.api_client_id or "").strip(),
        str(tenant.api_client_secret or "").strip(),
        str(tenant.public_url or "").strip(),
    )


async def _stream_paginated(index_pages, build_pages, builder):
    """2-menetes: pass1 index (index_pages — lehet KÖNNYŰ fetch), pass2 build (build_pages).

    index_pages()/build_pages() friss async gen-t adnak. Sellvio/Woo esetén a kettő azonos; Shoprenternél
    az index_pages full=0 (könnyű), a build_pages full=1 (nehéz) -> nincs második nehéz fetch.
    """
    async for page in index_pages():          # pass 1 — csak a reláció-index
        builder.index(page)
    async for page in build_pages():          # pass 2 — build + yield
        for sp in builder.build(page):
            yield sp


async def _stream_blob(items, builder):
    """Egy-blobos forrás: index az egészen (könnyű), majd chunkonként build + yield."""
    builder.index(items)
    for i in range(0, len(items), _CHUNK):
        for sp in builder.build(items[i:i + _CHUNK]):
            yield sp


# --- lapozott, nehéz források (2× fetch, de korlátos memória) ---------------
async def stream_sellvio(tenant: "Tenant"):
    base, cid, sec, pub = _creds(tenant)
    def pages():
        return pa.sellvio_list_products(base, cid, sec)
    async for sp in _stream_paginated(pages, pages, SellvioBuilder(tenant.client_id, pub)):
        yield sp


async def stream_woo(tenant: "Tenant"):
    base, ck, cs, _ = _creds(tenant)
    def pages():
        return pa.woo_list_products(base, ck, cs)
    async for sp in _stream_paginated(pages, pages, WooBuilder(tenant.client_id)):
        yield sp


async def stream_shoprenter(tenant: "Tenant"):
    base, cid, sec, pub = _creds(tenant)
    conc = get_settings().sync_shoprenter_concurrency
    # pass-1: full=0 KÖNNYŰ (csak id->name/url a relációkhoz) — nincs második nehéz fetch.
    # pass-2: full=1 NEHÉZ (a teljes text), egyszer, ablakonként párhuzamosan lekérve.
    async for sp in _stream_paginated(
        lambda: pa.shoprenter_list_products(base, cid, sec, full=0, concurrency=conc),
        lambda: pa.shoprenter_list_products(base, cid, sec, full=1, concurrency=conc),
        ShoprenterBuilder(tenant.client_id, pub, include_inactive=get_settings().sync_include_inactive),
    ):
        yield sp


# --- egy-blobos források (1× letöltés, chunkolt build) ----------------------
async def stream_unas(tenant: "Tenant"):
    _, cid, sec, pub = _creds(tenant)
    csv_text = await pa.unas_export_csv(sec or cid)
    async for sp in _stream_blob(unas_rowdicts(csv_text), UnasBuilder(tenant.client_id)):
        yield sp


async def stream_webdoc(tenant: "Tenant"):
    feed_url = str(tenant.api_base or "").strip()
    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        r = await client.get(feed_url, headers={"Accept": "application/json"})
        r.raise_for_status()
        root = r.json()
    products = []
    if isinstance(root, dict):
        if isinstance(root.get("products"), list):
            products = root["products"]
        elif isinstance(root.get("data"), dict) and isinstance(root["data"].get("products"), list):
            products = root["data"]["products"]
        elif isinstance(root.get("data"), list):
            products = root["data"]
    elif isinstance(root, list):
        products = root
    async for sp in _stream_blob(webdoc_sorted(products), WebdocBuilder(tenant.client_id)):
        yield sp


_STREAMERS = {
    "sellvio": stream_sellvio,
    "woocommerce": stream_woo,
    "shoprenter": stream_shoprenter,
    "unas": stream_unas,
    "webdoc": stream_webdoc,
}

SUPPORTED_PLATFORMS = frozenset(_STREAMERS)


async def stream_products(tenant: "Tenant"):
    """A tenant platformja szerinti SourceProduct-stream (memória-korlátos)."""
    fn = _STREAMERS.get(str(tenant.platform or "").strip().lower())
    if fn is None:
        return
    async for sp in fn(tenant):
        yield sp

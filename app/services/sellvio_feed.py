"""m91: Sellvio B2B termék-feed — a SZÁMSZERŰ készlet egyetlen működő forrása.

Miért külön modul: a Sellvio OAuth `api/v2 /products` 59 mezője NEM tartalmaz
darabszámot (se quantity, se stock, se raktár — élesben ellenőrizve mind a 3
tenanton), csak `is_available_for_order` boolt (azt a m90 már beköti). A valódi
készlet kizárólag a per-user B2B feedből jön:

    https://{domain}/api/{locale}/products?output_type=json&api_key={token}

A tokent a bolt adminja adja (Webshop → Automatikus termékmegosztás (API) →
B2B API), tenantonként egy, a `tenants.b2b_api_key` oszlopban (m90/1).

HÁROM SZABÁLY, ami a mérésekből jött:
  1. A feed a TELJES katalógust adja egy válaszban, lapozás nélkül (teslashop
     ~5300 termék ~36 MB XML) -> per-kérés lekérni tilos: TTL-cache tenantonként.
  2. A `quantity` csak ott valódi, ahol a bolt tényleg vezet készletet, ÉS a
     tokent raktár-szűrés nélkül hozták létre. Dropship boltnál (teslashop) MIND
     a 5289 termék 0, miközben rendelhető -> `usable` kapu: ha egyetlen nem-nulla
     darabszám sincs, a feedet NEM használjuk készletre (különben a bot mindent
     kifutónak mondana).
  3. A feed ÁRA felhasználó-specifikus (a token gazdájának kedvezményeivel) ->
     ÁRAT innen SOSEM veszünk át, csak darabszámot.

Bot-védelem: a bolt domainje mögött CDN-kapu állhat, a csupasz kérés
„One moment, please…" HTML-t ad JSON helyett -> böngésző User-Agent + egy retry.
"""

import logging
import time as _time

import httpx

logger = logging.getLogger("cx.sellvio_feed")

_TTL = 600.0          # 10 perc — a live ág percenként is kérdezhet, a feed nehéz
_TIMEOUT = 180.0      # a teljes katalógus egy válaszban jön
_RETRY_SLEEP = 5.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_CACHE: dict[str, tuple[float, "StockMap"]] = {}


class StockMap:
    """Cikkszám/id -> darabszám, a feed egészére vonatkozó minőség-jelzőkkel."""

    __slots__ = ("by_id", "by_sku", "count", "nonzero", "error")

    def __init__(self, by_id=None, by_sku=None, count=0, nonzero=0, error=""):
        self.by_id = by_id or {}
        self.by_sku = by_sku or {}
        self.count = count
        self.nonzero = nonzero
        self.error = error

    @property
    def usable(self) -> bool:
        """Készletre CSAK akkor használható, ha betöltött ÉS van benne nem-nulla darab.

        A csupa-nulla feed vagy dropship bolt, vagy raktár-szűrt token — mindkét
        esetben a 0 nem azt jelenti, hogy elfogyott.
        """
        return self.count > 0 and self.nonzero > 0

    def qty(self, product_id=None, sku=None):
        """Darabszám id vagy cikkszám alapján; None, ha nincs a feedben."""
        if product_id not in (None, ""):
            v = self.by_id.get(str(product_id))
            if v is not None:
                return v
        if sku not in (None, ""):
            return self.by_sku.get(str(sku).strip())
        return None

    def __repr__(self) -> str:  # pragma: no cover — diagnosztika
        return "StockMap(count=%d, nonzero=%d, usable=%s, error=%r)" % (
            self.count, self.nonzero, self.usable, self.error)


def _int_or_none(v):
    try:
        return int(float(str(v).replace(" ", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _items(body):
    """A JSON-boríték toleráns kicsomagolása (lista vagy products/data/items kulcs)."""
    if isinstance(body, list):
        return [i for i in body if isinstance(i, dict)]
    if isinstance(body, dict):
        for k in ("products", "data", "items"):
            v = body.get(k)
            if isinstance(v, list):
                return [i for i in v if isinstance(i, dict)]
            if isinstance(v, dict):  # {"data": {"items": [...]}}
                for k2 in ("products", "items"):
                    v2 = v.get(k2)
                    if isinstance(v2, list):
                        return [i for i in v2 if isinstance(i, dict)]
    return []


def parse_feed(body) -> StockMap:
    """Tiszta (I/O nélküli) elemzés — ez a tesztelt mag."""
    by_id, by_sku, nonzero = {}, {}, 0
    rows = _items(body)
    for it in rows:
        q = _int_or_none(it.get("quantity"))
        if q is None:
            continue
        if q < 0:
            q = 0
        pid = it.get("id")
        if pid not in (None, ""):
            by_id[str(pid)] = q
        sku = str(it.get("article_number") or "").strip()
        if sku:
            by_sku[sku] = q
        if q > 0:
            nonzero += 1
    return StockMap(by_id=by_id, by_sku=by_sku, count=len(rows), nonzero=nonzero)


def feed_url(base: str, locale: str = "hu") -> str:
    return str(base or "").strip().rstrip("/") + "/api/" + (locale or "hu") + "/products"


async def fetch_stock_map(client, base: str, api_key: str, locale: str = "hu") -> StockMap:
    """Egy feed-lehúzás a MEGADOTT klienssel (a hívó adja be -> fake-kel tesztelhető).

    Sosem dob: hiba esetén üres StockMap `error`-ral (a sync/live ág fail-open).
    """
    url = feed_url(base, locale)
    params = {"output_type": "json", "api_key": api_key}
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    for attempt in (1, 2):
        try:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            try:
                body = r.json()
            except Exception:  # noqa: BLE001 — bot-kapu HTML-t adott JSON helyett
                if attempt == 1:
                    import asyncio
                    await asyncio.sleep(_RETRY_SLEEP)
                    continue
                return StockMap(error="nem JSON valasz (bot-kapu?)")
            sm = parse_feed(body)
            if sm.count == 0 and attempt == 1:
                import asyncio
                await asyncio.sleep(_RETRY_SLEEP)
                continue
            return sm
        except Exception as e:  # noqa: BLE001
            if attempt == 1:
                import asyncio
                await asyncio.sleep(_RETRY_SLEEP)
                continue
            return StockMap(error=str(e)[:200])
    return StockMap(error="ismeretlen")


async def get_stock_map(tenant, *, force: bool = False) -> StockMap:
    """Tenant-szintű, TTL-cache-elt készlet-térkép. Kulcs nélkül ÜRES térkép (nincs hívás)."""
    cid = str(getattr(tenant, "client_id", "") or "")
    key = str(getattr(tenant, "b2b_api_key", "") or "").strip()
    if not key:
        return StockMap()
    base = str(getattr(tenant, "api_base", "") or "").strip() or \
        str(getattr(tenant, "public_url", "") or "").strip()
    if not base:
        return StockMap(error="nincs api_base/public_url")

    now = _time.monotonic()
    hit = _CACHE.get(cid)
    if hit and not force and hit[0] > now:
        return hit[1]

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        sm = await fetch_stock_map(client, base, key)
    if sm.error:
        logger.warning("m91 sellvio feed [%s]: %s", cid, sm.error)
    elif not sm.usable:
        logger.warning(
            "m91 sellvio feed [%s]: %d termek, MIND 0 darab -> a keszletet NEM hasznaljuk "
            "(dropship bolt vagy raktar-szurt token)", cid, sm.count)
    else:
        logger.info("m91 sellvio feed [%s]: %d termek, %d nem-nulla keszlet",
                    cid, sm.count, sm.nonzero)
    _CACHE[cid] = (now + _TTL, sm)
    return sm


def cache_clear() -> None:
    _CACHE.clear()

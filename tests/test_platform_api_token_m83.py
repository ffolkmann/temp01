"""m83: Shoprenter token-cache + single-flight + 401 re-auth.

Eddig MINDEN hivas uj tokent kert (termekmegtekintesenkent 2 API-hivas), es a
`raise_for_status()` azonnal dobott 401-re. A Shoprenter 3 req/s/app/shop
limitje mellett ez parhuzamos hivasoknal versenyhelyzet volt a token-vegponton
(fishingoutlet, ~128e termek: tranziens 401 -> "synced marad").
"""

import asyncio
import base64
import json
import time

import pytest

from app.services import platform_api as pa


def _jwt(exp_delta):
    """JWT-alaku token a megadott exp-pel (masodperc a mostanihoz kepest)."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time() + exp_delta)}).encode()
    ).decode().rstrip("=")
    return "hdr.%s.sig" % payload


class _Resp:
    def __init__(self, token):
        self._token = token

    def raise_for_status(self):
        return None

    def json(self):
        return {"access_token": self._token}


class _Client:
    """Szamolja, hanyszor kertek tokent; opcionalisan lassit (single-flight teszt)."""

    def __init__(self, token=None, delay=0.0):
        self.calls = 0
        self.token = _jwt(3600) if token is None else token
        self.delay = delay

    async def post(self, url, json=None):  # noqa: A002
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return _Resp(self.token)


@pytest.fixture(autouse=True)
def _clear_cache():
    pa._SR_TOKEN_CACHE.clear()
    pa._SR_TOKEN_LOCKS.clear()
    yield
    pa._SR_TOKEN_CACHE.clear()
    pa._SR_TOKEN_LOCKS.clear()


async def test_masodik_hivas_a_cachebol_jon_m83():
    c = _Client()
    t1 = await pa.shoprenter_token(c, "bolt", "cid", "sec")
    t2 = await pa.shoprenter_token(c, "bolt", "cid", "sec")
    assert t1 == t2 and t1
    assert c.calls == 1, "a masodik hivasnak a cachebol kell jonnie"


async def test_force_mindig_friss_tokent_ker_m83():
    c = _Client()
    await pa.shoprenter_token(c, "bolt", "cid", "sec")
    await pa.shoprenter_token(c, "bolt", "cid", "sec", force=True)
    assert c.calls == 2


async def test_lejart_token_ujra_lekerodik_m83():
    c = _Client(token=_jwt(10))  # 10 mp -> a 60 mp-es skew miatt azonnal lejart
    await pa.shoprenter_token(c, "bolt", "cid", "sec")
    await pa.shoprenter_token(c, "bolt", "cid", "sec")
    assert c.calls == 2, "a skew-n beluli tokent nem szabad cachelni"


async def test_single_flight_parhuzamos_hivasoknal_m83():
    c = _Client(delay=0.05)
    res = await asyncio.gather(*[
        pa.shoprenter_token(c, "bolt", "cid", "sec") for _ in range(5)
    ])
    assert len(set(res)) == 1
    assert c.calls == 1, "parhuzamos hivoknal is CSAK egy token-keres mehet ki"


async def test_shoponkent_kulon_cache_m83():
    c1 = _Client(token=_jwt(3600))
    c2 = _Client(token=_jwt(3600))
    await pa.shoprenter_token(c1, "bolt-a", "cid", "sec")
    await pa.shoprenter_token(c2, "bolt-b", "cid", "sec")
    assert c1.calls == 1 and c2.calls == 1
    assert len(pa._SR_TOKEN_CACHE) == 2


async def test_ugyanaz_a_shop_mas_credentiallel_kulon_cache_m83():
    c = _Client()
    await pa.shoprenter_token(c, "bolt", "cid-1", "sec")
    await pa.shoprenter_token(c, "bolt", "cid-2", "sec")
    assert c.calls == 2


async def test_ures_token_nem_kerul_cachebe_m83():
    c = _Client(token="")
    await pa.shoprenter_token(c, "bolt", "cid", "sec")
    await pa.shoprenter_token(c, "bolt", "cid", "sec")
    assert c.calls == 2
    assert ("bolt", "cid") not in pa._SR_TOKEN_CACHE


def test_jwt_ttl_fallback_ertelmetlen_tokenre_m83():
    # nem JWT / hianyzo exp -> konzervativ fallback, nem 0 es nem vegtelen
    assert pa._sr_jwt_ttl("nem-jwt") == pa._SR_FALLBACK_TTL
    assert pa._sr_jwt_ttl("") == pa._SR_FALLBACK_TTL
    assert pa._sr_jwt_ttl(_jwt(-100)) == 0.0


def test_jwt_ttl_valodi_expet_olvas_m83():
    ttl = pa._sr_jwt_ttl(_jwt(1800))
    assert 1700 < ttl <= 1800

"""operator_presence (m30) — TENANTONKÉNTI jelenlét-kulcsok.

A modult FÁJLBÓL töltjük (importlib) + `app.core.redis` stub, mert a többi teszt
`app.services` stubot rak a sys.modules-ba `__path__=[]`-szal.

Kulcs-invariáns: egy tenant operátorának online-állapota NE tegye online-ná a
többi tenantot. A master pult (`__all__`) viszont mindenkire számít.
"""

import asyncio
import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

for _name in ("app", "app.core", "app.services"):
    _m = sys.modules.setdefault(_name, types.ModuleType(_name))
    if not hasattr(_m, "__path__"):
        _m.__path__ = []

_redis_stub = types.ModuleType("app.core.redis")
_redis_stub.get_redis = lambda: None
sys.modules.setdefault("app.core.redis", _redis_stub)

_P = ROOT / "app" / "services" / "operator_presence.py"
_spec = importlib.util.spec_from_file_location("operator_presence_under_test", _P)
_op = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_op)


class FakeRedis:
    """Csak a használt metódusok. `boom=True` -> minden hívás dob (fail-safe teszt)."""

    def __init__(self, keys=(), boom=False):
        self.keys = set(keys)
        self.boom = boom
        self.sets: list[tuple[str, str, int]] = []

    async def exists(self, k):
        if self.boom:
            raise RuntimeError("redis down")
        return 1 if k in self.keys else 0

    async def set(self, k, v, ex=None):
        if self.boom:
            raise RuntimeError("redis down")
        self.keys.add(k)
        self.sets.append((k, v, ex))

    async def delete(self, k):
        if self.boom:
            raise RuntimeError("redis down")
        self.keys.discard(k)

    async def ttl(self, k):
        if self.boom:
            raise RuntimeError("redis down")
        return 120 if k in self.keys else -2


def _with_redis(r):
    _op.get_redis = lambda: r
    return r


# --- kulcs-epites (pure) -----------------------------------------------------
@pytest.mark.parametrize(
    "cid,want",
    [
        ("notebookstore", "cx:operator:online:notebookstore"),
        ("  TeslaShop ", "cx:operator:online:teslashop"),
        (None, "cx:operator:online:__all__"),
        ("", "cx:operator:online:__all__"),
    ],
)
def test_presence_key(cid, want):
    assert _op.presence_key(cid) == want


# --- a LENYEG: nem szivarog at tenantok kozott --------------------------------
def test_masik_tenant_operatora_nem_tesz_online_na():
    _with_redis(FakeRedis(keys={"cx:operator:online:fishingoutlet"}))
    assert asyncio.run(_op.is_operator_online("fishingoutlet")) is True
    assert asyncio.run(_op.is_operator_online("notebookstore")) is False


def test_master_pult_minden_tenantra_szamit():
    _with_redis(FakeRedis(keys={"cx:operator:online:__all__"}))
    assert asyncio.run(_op.is_operator_online("notebookstore")) is True
    assert asyncio.run(_op.is_operator_online("barmi")) is True


def test_senki_sincs_online():
    _with_redis(FakeRedis())
    assert asyncio.run(_op.is_operator_online("notebookstore")) is False


def test_redis_hiba_eseten_offline():
    """Fail-safe: inkább e-mailes handoff, mint elnyelt vevő."""
    _with_redis(FakeRedis(boom=True))
    assert asyncio.run(_op.is_operator_online("notebookstore")) is False


# --- set/offline a helyes kulcsra --------------------------------------------
def test_set_online_a_sajat_kulcsra_ir():
    r = _with_redis(FakeRedis())
    asyncio.run(_op.set_online("Anna", "notebookstore"))
    assert r.sets == [("cx:operator:online:notebookstore", "Anna", 150)]
    assert asyncio.run(_op.is_operator_online("teslashop")) is False


def test_set_online_master_a_wildcardra_ir():
    r = _with_redis(FakeRedis())
    asyncio.run(_op.set_online("Feco", None))
    assert r.sets[0][0] == "cx:operator:online:__all__"


def test_set_offline_csak_a_sajatot_torli():
    r = _with_redis(FakeRedis(keys={"cx:operator:online:a", "cx:operator:online:b"}))
    asyncio.run(_op.set_offline("a"))
    assert r.keys == {"cx:operator:online:b"}


def test_status_a_sajat_kulcsot_nezi():
    _with_redis(FakeRedis(keys={"cx:operator:online:a"}))
    assert asyncio.run(_op.status("a")) == {"online": True, "ttl": 120}
    assert asyncio.run(_op.status("b")) == {"online": False, "ttl": 0}

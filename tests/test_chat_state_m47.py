"""m47 - widget state-poll (session_live_state) + takeover Redis-flag
(mark_takeover / clear_takeover). Fajlbol toltve (suite-konvencio, mint
test_operator_live_m46.py)."""

import asyncio
import importlib.util
import pathlib
import sys
import types

_sa_snapshot = {k: v for k, v in sys.modules.items() if k == "sqlalchemy" or k.startswith("sqlalchemy.")}
for _k in list(_sa_snapshot):
    del sys.modules[_k]
import sqlalchemy  # noqa: E402,F401
import sqlalchemy.dialects.postgresql  # noqa: E402,F401
import sqlalchemy.ext.asyncio  # noqa: E402,F401
import sqlalchemy.orm  # noqa: E402,F401

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _name in ("app", "app.core", "app.services", "app.models"):
    _m = sys.modules.setdefault(_name, types.ModuleType(_name))
    _m.__path__ = []

_dm_path = ROOT / "app" / "models" / "db_models.py"
_dm_spec = importlib.util.spec_from_file_location("app.models.db_models", _dm_path)
_dm = importlib.util.module_from_spec(_dm_spec)
sys.modules["app.models.db_models"] = _dm
_dm_spec.loader.exec_module(_dm)

_la_path = ROOT / "app" / "services" / "live_agent.py"
_la_spec = importlib.util.spec_from_file_location("live_agent_m47_under_test", _la_path)
_la = importlib.util.module_from_spec(_la_spec)
_la_spec.loader.exec_module(_la)

for _k in [x for x in list(sys.modules) if x == "sqlalchemy" or x.startswith("sqlalchemy.")]:
    del sys.modules[_k]
sys.modules.update(_sa_snapshot)


class _Result:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.exec_count = 0

    async def execute(self, stmt):
        self.exec_count += 1
        return self._results.pop(0) if self._results else _Result()


class _RaisingSession:
    exec_count = 0

    async def execute(self, stmt):
        raise RuntimeError("db down")


class _FakeRedis:
    def __init__(self, store=None, fail=False):
        self.store = dict(store or {})
        self.fail = fail
        self.set_calls = []
        self.del_calls = []

    async def get(self, k):
        if self.fail:
            raise RuntimeError("redis down")
        return self.store.get(k)

    async def set(self, k, v, ex=None):
        if self.fail:
            raise RuntimeError("redis down")
        self.store[k] = v
        self.set_calls.append((k, v, ex))

    async def delete(self, *ks):
        if self.fail:
            raise RuntimeError("redis down")
        for k in ks:
            self.store.pop(k, None)
        self.del_calls.extend(ks)


# --------------------------------------------------------------------------- #
# mark_takeover / clear_takeover
# --------------------------------------------------------------------------- #
def test_mark_takeover_sets_flag_and_drops_cache():
    r = _FakeRedis({_la._state_cache_key("s1"): "bot"})
    asyncio.run(_la.mark_takeover(r, "s1", "Anna"))
    assert r.store[_la._takeover_key("s1")] == "Anna"
    assert _la._state_cache_key("s1") not in r.store  # a negativ cache torolve
    assert r.set_calls[0][2] == _la.TAKEOVER_TTL


def test_mark_takeover_empty_sid_noop():
    r = _FakeRedis()
    asyncio.run(_la.mark_takeover(r, "", "Anna"))
    assert r.store == {} and r.set_calls == []


def test_mark_takeover_redis_failure_is_silent():
    asyncio.run(_la.mark_takeover(_FakeRedis(fail=True), "s1", "Anna"))


def test_clear_takeover_deletes_both_keys():
    r = _FakeRedis({_la._takeover_key("s1"): "Anna", _la._state_cache_key("s1"): "operator"})
    asyncio.run(_la.clear_takeover(r, "s1"))
    assert r.store == {}


def test_clear_takeover_redis_failure_is_silent():
    asyncio.run(_la.clear_takeover(_FakeRedis(fail=True), "s1"))


# --------------------------------------------------------------------------- #
# session_live_state
# --------------------------------------------------------------------------- #
def test_state_redis_flag_hit_no_db():
    db = _FakeSession()
    r = _FakeRedis({_la._takeover_key("s1"): "Anna"})
    assert asyncio.run(_la.session_live_state(db, r, "s1")) == "operator"
    assert db.exec_count == 0  # a DB-hez hozza sem nyult


def test_state_cache_hit_no_db():
    db = _FakeSession()
    r = _FakeRedis({_la._state_cache_key("s1"): "bot"})
    assert asyncio.run(_la.session_live_state(db, r, "s1")) == "bot"
    assert db.exec_count == 0


def test_state_db_operator_self_heals_flag():
    db = _FakeSession([_Result(scalar="operator")])
    r = _FakeRedis()
    assert asyncio.run(_la.session_live_state(db, r, "s1")) == "operator"
    assert r.store.get(_la._takeover_key("s1")) == "operator"  # self-heal
    assert r.set_calls[0][2] == _la.TAKEOVER_TTL


def test_state_db_bot_sets_short_cache():
    db = _FakeSession([_Result(scalar=None)])  # nincs chat_sessions sor -> bot
    r = _FakeRedis()
    assert asyncio.run(_la.session_live_state(db, r, "s1")) == "bot"
    assert r.store.get(_la._state_cache_key("s1")) == "bot"
    assert r.set_calls[0][2] == _la._STATE_CACHE_TTL


def test_state_db_closed_maps_to_bot():
    db = _FakeSession([_Result(scalar="closed")])
    assert asyncio.run(_la.session_live_state(db, _FakeRedis(), "s1")) == "bot"


def test_state_db_requested_maps_to_bot():
    # requested-nel a widget mar operator_wait-bol elt at live-modba; a state-poll bot-ot ad
    db = _FakeSession([_Result(scalar="requested")])
    assert asyncio.run(_la.session_live_state(db, _FakeRedis(), "s1")) == "bot"


def test_state_empty_sid_bot():
    db = _FakeSession()
    assert asyncio.run(_la.session_live_state(db, _FakeRedis(), "")) == "bot"
    assert db.exec_count == 0


def test_state_redis_down_db_fallback():
    db = _FakeSession([_Result(scalar="operator")])
    assert asyncio.run(_la.session_live_state(db, _FakeRedis(fail=True), "s1")) == "operator"


def test_state_db_down_bot():
    assert asyncio.run(_la.session_live_state(_RaisingSession(), _FakeRedis(), "s1")) == "bot"

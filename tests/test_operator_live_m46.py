"""m46 - elo monitor + proaktiv atvetel (live_agent: list_live / takeover_session /
resolve_client_id / transcript_rows / get_conversation log-fallback).

Fajlbol toltve (suite-konvencio, mint test_live_agent.py): valodi sqlalchemy +
valodi db_models a statement-epiteshez, fake AsyncSession sorban adott eredmenyekkel.
"""

import asyncio
import importlib.util
import pathlib
import sys
import types

# valodi sqlalchemy import-idore (mint test_live_agent.py), utana visszaallitas
_sa_snapshot = {k: v for k, v in sys.modules.items() if k == "sqlalchemy" or k.startswith("sqlalchemy.")}
for _k in list(_sa_snapshot):
    del sys.modules[_k]
import sqlalchemy  # noqa: E402,F401  (valodi)
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
_la_spec = importlib.util.spec_from_file_location("live_agent_m46_under_test", _la_path)
_la = importlib.util.module_from_spec(_la_spec)
_la_spec.loader.exec_module(_la)

for _k in [x for x in list(sys.modules) if x == "sqlalchemy" or x.startswith("sqlalchemy.")]:
    del sys.modules[_k]
sys.modules.update(_sa_snapshot)


# --------------------------------------------------------------------------- #
# Fake AsyncSession
# --------------------------------------------------------------------------- #
class _Result:
    def __init__(self, *, scalar=None, scalars_all=None, first=None, rowcount=0, all_rows=None):
        self._scalar = scalar
        self._scalars_all = list(scalars_all or [])
        self._first = first
        self._all = list(all_rows or [])
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return types.SimpleNamespace(all=lambda: list(self._scalars_all))

    def first(self):
        return self._first

    def all(self):
        return list(self._all)


class _FakeSession:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.added = []
        self.flushed = 0
        self.committed = 0
        self.exec_count = 0

    async def execute(self, stmt):
        self.exec_count += 1
        return self._results.pop(0) if self._results else _Result()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        pass


def _ts(iso="2026-07-15T09:00:00+00:00"):
    return types.SimpleNamespace(isoformat=lambda _t=iso: _t)


def _msg(id_, sender, text):
    return types.SimpleNamespace(id=id_, sender=sender, text=text, created_at=_ts())


# --------------------------------------------------------------------------- #
# takeover_session - allapot-atmenetek + konfliktus (WHERE-guard rowcountbol)
# --------------------------------------------------------------------------- #
def test_takeover_no_row_creates_and_claims():
    # 1) _ensure_row select -> None (nincs sor, insert) 2) update rowcount=1
    db = _FakeSession([_Result(scalar=None), _Result(rowcount=1)])
    out = asyncio.run(_la.takeover_session(db, "copygo", "s1", "Anna"))
    assert out == "ok"
    assert db.committed == 1
    assert any(getattr(o, "state", None) == "bot" for o in db.added)  # get-or-create


def test_takeover_existing_bot_row_claims():
    db = _FakeSession([_Result(scalar="s1"), _Result(rowcount=1)])
    out = asyncio.run(_la.takeover_session(db, "copygo", "s1", "Anna"))
    assert out == "ok"
    assert db.added == []  # nem hozott letre uj sort


def test_takeover_requested_row_claims():
    # requested-sorra az atvetel = a meglevo claim (state != 'operator' -> guard atenged)
    db = _FakeSession([_Result(scalar="s1"), _Result(rowcount=1)])
    assert asyncio.run(_la.takeover_session(db, "copygo", "s1", "Bela")) == "ok"


def test_takeover_conflict_when_other_operator_holds():
    # MASIK operator aktiv claimje -> a WHERE-guard 0 sort frissit -> conflict
    db = _FakeSession([_Result(scalar="s1"), _Result(rowcount=0)])
    out = asyncio.run(_la.takeover_session(db, "copygo", "s1", "Bela"))
    assert out == "conflict"
    assert db.committed == 1


# --------------------------------------------------------------------------- #
# resolve_client_id - chat_sessions eloszor, messages-fallback utana
# --------------------------------------------------------------------------- #
def test_resolve_from_chat_sessions():
    db = _FakeSession([_Result(scalar="copygo")])
    assert asyncio.run(_la.resolve_client_id(db, "s1")) == "copygo"
    assert db.exec_count == 1


def test_resolve_fallback_to_messages():
    db = _FakeSession([_Result(scalar=None), _Result(scalar="copygo")])
    assert asyncio.run(_la.resolve_client_id(db, "s1")) == "copygo"
    assert db.exec_count == 2


def test_resolve_unknown_none():
    db = _FakeSession([_Result(scalar=None), _Result(scalar=None)])
    assert asyncio.run(_la.resolve_client_id(db, "sX")) is None


def test_resolve_empty_session_id_none():
    db = _FakeSession()
    assert asyncio.run(_la.resolve_client_id(db, "")) is None
    assert db.exec_count == 0


# --------------------------------------------------------------------------- #
# transcript_rows - messages turn-naplo -> chat_messages-kompatibilis sorok
# --------------------------------------------------------------------------- #
def test_transcript_rows_maps_turns():
    rows = [("kerdes", "valasz", _ts()), ("masodik kerdes", None, _ts())]
    db = _FakeSession([_Result(all_rows=rows)])
    out = asyncio.run(_la.transcript_rows(db, "copygo", "s1"))
    assert [(r["sender"], r["text"]) for r in out] == [
        ("user", "kerdes"), ("bot", "valasz"), ("user", "masodik kerdes"),
    ]
    assert all(r["id"] == 0 for r in out)  # a poll-kurzort nem mozgatjak
    assert out[0]["ts"] == "2026-07-15T09:00:00+00:00"


# --------------------------------------------------------------------------- #
# get_conversation - log-fallback csak bot-only sessionre, after<=0 mellett
# --------------------------------------------------------------------------- #
def test_conversation_log_fallback_bot_only():
    db = _FakeSession([
        _Result(scalar=None),                                   # nincs chat_sessions sor
        _Result(scalars_all=[]),                                # nincs chat_messages
        _Result(all_rows=[("kerdes", "valasz", _ts())]),        # messages transcript
    ])
    out = asyncio.run(_la.get_conversation(db, "s1", 0, client_id="copygo"))
    assert out["state"] == "bot"
    assert out["client_id"] == "copygo"
    assert out["log_fallback"] is True
    assert [(m["sender"], m["text"]) for m in out["messages"]] == [
        ("user", "kerdes"), ("bot", "valasz"),
    ]


def test_conversation_no_fallback_when_chat_messages_exist():
    sess = types.SimpleNamespace(state="operator", claimed_by="Anna", client_id="copygo")
    db = _FakeSession([
        _Result(scalar=sess),
        _Result(scalars_all=[_msg(7, "system", "elozmeny"), _msg(8, "user", "szia")]),
    ])
    out = asyncio.run(_la.get_conversation(db, "s1", 0))
    assert out["log_fallback"] is False
    assert out["state"] == "operator"
    assert [m["id"] for m in out["messages"]] == [7, 8]
    assert db.exec_count == 2  # nem nyult a messages naplohoz


def test_conversation_no_fallback_when_after_positive():
    db = _FakeSession([_Result(scalar=None), _Result(scalars_all=[])])
    out = asyncio.run(_la.get_conversation(db, "s1", 9, client_id="copygo"))
    assert out["messages"] == [] and out["log_fallback"] is False
    assert db.exec_count == 2  # a fallback-query NEM futott le


def test_conversation_no_fallback_when_not_bot_state():
    sess = types.SimpleNamespace(state="closed", claimed_by="Anna", client_id="copygo")
    db = _FakeSession([_Result(scalar=sess), _Result(scalars_all=[])])
    out = asyncio.run(_la.get_conversation(db, "s1", 0))
    assert out["log_fallback"] is False and out["messages"] == []
    assert db.exec_count == 2


# --------------------------------------------------------------------------- #
# list_live - messages-aggregacio + chat_sessions "LEFT JOIN" + tenant-szures
# --------------------------------------------------------------------------- #
def test_list_live_shapes_and_joins_state():
    agg = [
        ("s1", "copygo", 3, _ts("2026-07-15T09:05:00+00:00"), 42),
        ("s2", "copygo", 1, _ts("2026-07-15T09:01:00+00:00"), 43),
    ]
    db = _FakeSession([
        _Result(all_rows=agg),
        _Result(first=("utolso kerdes " + "x" * 200, "utolso valasz")),   # s1 utolso turn
        _Result(first=("masodik kerdes", None)),                          # s2 utolso turn
        _Result(scalars_all=[types.SimpleNamespace(
            session_id="s1", state="operator", claimed_by="Anna")]),
    ])
    out = asyncio.run(_la.list_live(db, "copygo"))
    assert len(out) == 2
    assert out[0]["session_id"] == "s1"
    assert out[0]["state"] == "operator" and out[0]["claimed_by"] == "Anna"
    assert out[0]["turns"] == 3
    assert len(out[0]["last_question"]) == 120  # vagas
    assert out[0]["last_ts"] == "2026-07-15T09:05:00+00:00"
    assert out[1]["state"] == "bot" and out[1]["claimed_by"] is None
    assert out[1]["last_question"] == "masodik kerdes"
    assert out[1]["last_answer"] == ""


def test_list_live_empty():
    db = _FakeSession([_Result(all_rows=[])])
    assert asyncio.run(_la.list_live(db, None)) == []
    assert db.exec_count == 1  # ures aggregacio utan nincs tovabbi query

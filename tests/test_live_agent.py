"""Élő operátor-átvétel service (app/services/live_agent.py) — izolátor tesztek.

A modult FÁJLBÓL töltjük (importlib), a VALÓDI db_models-szel (a mapped oszlopok
kellenek a select/update statementekhez); az AsyncSession-t fake-eljük, ami sorban
adja vissza az előre bedrótozott eredményeket (a statement tartalmát figyelmen kívül
hagyja). A kulcs-invariáns: a claim ATOMI (rowcount alapján requested -> operator).
"""

import asyncio
import importlib.util
import pathlib
import sys
import types

# Egy korábban kollektált teszt (test_cors) fake `sqlalchemy`-t tesz a sys.modules-ba;
# a valódi db_models betöltéséhez ideiglenesen visszaállítjuk a VALÓDI sqlalchemy-t,
# majd a betöltés után visszatesszük az eredeti állapotot (a később kollektált tesztek –
# pl. test_stats – ne sérüljenek). A betöltött modulok a valódi select/update/oszlop-
# referenciákat elkapják import-időben, így futásidőben függetlenek a sys.modules-tól.
_sa_snapshot = {k: v for k, v in sys.modules.items() if k == "sqlalchemy" or k.startswith("sqlalchemy.")}
for _k in list(_sa_snapshot):
    del sys.modules[_k]
import sqlalchemy  # noqa: E402,F401  (valódi)
import sqlalchemy.dialects.postgresql  # noqa: E402,F401
import sqlalchemy.ext.asyncio  # noqa: E402,F401
import sqlalchemy.orm  # noqa: E402,F401

ROOT = pathlib.Path(__file__).resolve().parents[1]

for _name in ("app", "app.core", "app.services", "app.models"):
    _m = sys.modules.setdefault(_name, types.ModuleType(_name))
    _m.__path__ = []

# VALÓDI db_models (mapped ChatSession/ChatMessage a statement-építéshez)
_dm_path = ROOT / "app" / "models" / "db_models.py"
_dm_spec = importlib.util.spec_from_file_location("app.models.db_models", _dm_path)
_dm = importlib.util.module_from_spec(_dm_spec)
sys.modules["app.models.db_models"] = _dm
_dm_spec.loader.exec_module(_dm)

# live_agent under test
_la_path = ROOT / "app" / "services" / "live_agent.py"
_la_spec = importlib.util.spec_from_file_location("live_agent_under_test", _la_path)
_la = importlib.util.module_from_spec(_la_spec)
_la_spec.loader.exec_module(_la)

# az eredeti sqlalchemy-állapot visszaállítása (ne szivárogjon a valódi modul a
# később kollektált tesztekbe, pl. test_stats a fake sqlalchemy-re számít)
for _k in [x for x in list(sys.modules) if x == "sqlalchemy" or x.startswith("sqlalchemy.")]:
    del sys.modules[_k]
sys.modules.update(_sa_snapshot)


# --------------------------------------------------------------------------- #
# Fake AsyncSession — sorban visszaadott előre-gyártott eredmények
# --------------------------------------------------------------------------- #
class _Result:
    def __init__(self, *, scalar=None, scalars_all=None, first=None, rowcount=0):
        self._scalar = scalar
        self._scalars_all = list(scalars_all or [])
        self._first = first
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return types.SimpleNamespace(all=lambda: list(self._scalars_all))

    def first(self):
        return self._first


class _FakeSession:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.added = []
        self.flushed = 0
        self.committed = 0
        self.rolled_back = 0

    async def execute(self, stmt):  # a stmt-et szándékosan ignoráljuk
        return self._results.pop(0) if self._results else _Result()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1
        # a DB-autoincrement szimulációja: a friss ChatMessage kap egy id-t
        for o in self.added:
            if hasattr(o, "sender") and getattr(o, "id", None) is None:
                o.id = 101

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


def _msg(id_, sender, text, ts="2026-07-08T10:00:00+00:00"):
    return types.SimpleNamespace(
        id=id_,
        sender=sender,
        text=text,
        created_at=types.SimpleNamespace(isoformat=lambda _t=ts: _t),
    )


# --------------------------------------------------------------------------- #
# get_session_state
# --------------------------------------------------------------------------- #
def test_state_no_session_id():
    db = _FakeSession()
    assert asyncio.run(_la.get_session_state(db, "c", None)) == "bot"


def test_state_no_row_defaults_bot():
    db = _FakeSession([_Result(scalar=None)])
    assert asyncio.run(_la.get_session_state(db, "c", "s1")) == "bot"


def test_state_returns_value():
    db = _FakeSession([_Result(scalar="operator")])
    assert asyncio.run(_la.get_session_state(db, "c", "s1")) == "operator"


# --------------------------------------------------------------------------- #
# claim_session — ATOMI invariáns
# --------------------------------------------------------------------------- #
def test_claim_success_when_row_updated():
    db = _FakeSession([_Result(rowcount=1)])
    ok = asyncio.run(_la.claim_session(db, "s1", "Anna"))
    assert ok is True
    assert db.committed == 1


def test_claim_fails_when_already_taken():
    db = _FakeSession([_Result(rowcount=0)])
    ok = asyncio.run(_la.claim_session(db, "s1", "Bela"))
    assert ok is False
    assert db.committed == 1


# --------------------------------------------------------------------------- #
# operator_send — csak 'operator' állapotban
# --------------------------------------------------------------------------- #
def test_send_rejected_when_not_operator_state():
    db = _FakeSession([_Result(first=("requested", "c"))])
    assert asyncio.run(_la.operator_send(db, "s1", "Anna", "hello")) is None
    assert db.committed == 0  # nem írtunk


def test_send_rejected_when_no_session():
    db = _FakeSession([_Result(first=None)])
    assert asyncio.run(_la.operator_send(db, "s1", "Anna", "hello")) is None


def test_send_ok_returns_message_id():
    # 1) select state -> ('operator','c'); 2..) add_message belső execute-jai -> default
    db = _FakeSession([_Result(first=("operator", "c"))])
    mid = asyncio.run(_la.operator_send(db, "s1", "Anna", "szia"))
    assert mid == 101
    assert db.committed == 1
    assert any(getattr(o, "sender", None) == "operator" for o in db.added)


# --------------------------------------------------------------------------- #
# add_message
# --------------------------------------------------------------------------- #
def test_add_message_persists_and_commits():
    db = _FakeSession()
    mid = asyncio.run(_la.add_message(db, "c", "s1", "user", "kérdés"))
    assert mid == 101
    assert db.committed == 1
    m = db.added[-1]
    assert m.sender == "user" and m.text == "kérdés" and m.client_id == "c"


# --------------------------------------------------------------------------- #
# poll_messages / row-formázás
# --------------------------------------------------------------------------- #
def test_poll_no_session_id_empty():
    db = _FakeSession()
    assert asyncio.run(_la.poll_messages(db, None, 0)) == []


def test_poll_maps_rows():
    db = _FakeSession(
        [_Result(scalars_all=[_msg(5, "operator", "hi"), _msg(6, "operator", "ott vagy?")])]
    )
    out = asyncio.run(_la.poll_messages(db, "s1", 4, senders=("operator",)))
    assert out == [
        {"id": 5, "sender": "operator", "text": "hi", "ts": "2026-07-08T10:00:00+00:00"},
        {"id": 6, "sender": "operator", "text": "ott vagy?", "ts": "2026-07-08T10:00:00+00:00"},
    ]


def test_msg_row_handles_missing_ts():
    row = _la._msg_row(types.SimpleNamespace(id=1, sender="user", text=None, created_at=None))
    assert row == {"id": 1, "sender": "user", "text": "", "ts": None}


# --------------------------------------------------------------------------- #
# list_queue / get_conversation
# --------------------------------------------------------------------------- #
def test_list_queue_with_preview():
    sess = types.SimpleNamespace(
        session_id="s1",
        client_id="c",
        state="requested",
        claimed_by=None,
        requested_at=None,
        last_user_at=None,
        last_op_at=None,
    )
    db = _FakeSession([_Result(scalars_all=[sess]), _Result(scalar="utolsó user üzenet")])
    out = asyncio.run(_la.list_queue(db, "c"))
    assert len(out) == 1
    assert out[0]["session_id"] == "s1"
    assert out[0]["state"] == "requested"
    assert out[0]["preview"] == "utolsó user üzenet"


def test_get_conversation_no_session_defaults_bot():
    db = _FakeSession([_Result(scalar=None), _Result(scalars_all=[])])
    out = asyncio.run(_la.get_conversation(db, "sX", 0))
    assert out["state"] == "bot"
    assert out["messages"] == []

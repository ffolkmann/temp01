"""m70: /stats idoszak-szures (days= / from&to) - "period" blokk tesztje.

Konvencio: stats.py fajlbol toltve fake fastapi/sqlalchemy stubokkal (mint
test_stats.py); az erintett sys.modules kulcsokat a futas vegen visszaallitjuk,
hogy a suite tobbi tesztjet ne zavarja.
Futtatas: python tests/test_stats_period_m70.py
"""
import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])

_KEYS = ("fastapi", "sqlalchemy", "sqlalchemy.ext", "sqlalchemy.ext.asyncio",
         "app", "app.core", "app.core.db", "app.api", "app.models",
         "app.services", "app.services.unanswered_export",
         "app.services.conversations_export", "app.api.stats")
_SNAP = {n: sys.modules.get(n) for n in _KEYS}

for n in ("app", "app.core", "app.api", "app.models", "app.services",
          "sqlalchemy", "sqlalchemy.ext"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []

ff = types.ModuleType("fastapi")


class _Router:
    def get(self, *a, **k):
        def deco(fn):
            return fn
        return deco

    def post(self, *a, **k):
        def deco(fn):
            return fn
        return deco


ff.APIRouter = _Router
ff.Depends = lambda x=None: x
ff.Query = lambda *a, **k: (a[0] if a else None)


class HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        self.status_code = status_code
        self.detail = detail


ff.HTTPException = HTTPException


class _Response:
    def __init__(self, content=None, media_type=None, headers=None):
        self.content = content
        self.media_type = media_type
        self.headers = headers or {}


ff.Response = _Response
sys.modules["fastapi"] = ff


class _Text:
    def __init__(self, s):
        self.s = s


sa = sys.modules["sqlalchemy"]
sa.text = lambda s: _Text(s)
sa_async = types.ModuleType("sqlalchemy.ext.asyncio")
sa_async.AsyncSession = object
sys.modules["sqlalchemy.ext.asyncio"] = sa_async

db = types.ModuleType("app.core.db")
db.get_session = lambda: None
sys.modules["app.core.db"] = db
ue = types.ModuleType("app.services.unanswered_export")
ue.build_unanswered_xlsx = lambda rows, transcripts=None: b"PK"
sys.modules["app.services.unanswered_export"] = ue
ce = types.ModuleType("app.services.conversations_export")
ce.build_conversations_xlsx = lambda rows: b"x"
sys.modules["app.services.conversations_export"] = ce


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


stats = _load("app.api.stats", f"{ROOT}/app/api/stats.py")


class _Res:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self):
        self.period_sqls = []

    async def execute(self, t, params=None):
        s = t.s
        # --- m70 period-agak (a bazis-agak ELOTT ellenorizve) ---
        if "created_at >= :f" in s and "FROM events" in s:
            self.period_sqls.append(s)
            return _Res([
                {"kind": "product_rec", "n": 2, "s": 6, "v": 0},
                {"kind": "link_click", "n": 3, "s": 0, "v": 0},
                {"kind": "handoff", "n": 1, "s": 0, "v": 0},
                {"kind": "purchase", "n": 2, "s": 0, "v": 5000},
            ])
        if "created_at >= :f" in s and "FROM leads" in s:
            return _Res(scalar=4)
        if "created_at >= :f" in s and "FROM messages" in s:
            return _Res([{"m": 20, "cv": 5}])
        if "period IN (" in s:
            self.period_sqls.append(s)
            return _Res([{"cv": 33, "m": 77}])
        # --- bazis-agak (minimalis valaszok a /stats tobbi lekerdezesere) ---
        if "FROM tenants t LEFT JOIN plans" in s:
            return _Res([{"client_id": "t1", "plan": "pro", "platform": "x",
                          "bot_name": "B", "header_color": "#fff",
                          "white_label": False, "live_api": False,
                          "monthly_limit": 0}])
        if "AS impressions" in s:
            return _Res([{"impressions": 0, "chatted": 0, "clicked": 0}])
        if "MIN(created_at) FROM events" in s:
            return _Res(scalar=None)
        if "COUNT(*) n FROM leads" in s:
            return _Res(scalar=0)
        return _Res()


async def main():
    ok = []

    # === days=7: pontos (messages-naplo), esemeny-szamlalok, purchase value ===
    fs = FakeSession()
    d = await stats.stats(k="sk", days=7, session=fs)
    p = d["period"]
    assert p["days"] == 7 and p["label"] == "Utols\u00f3 7 nap"
    assert p["from"].endswith("Z") and p["to"].endswith("Z")
    assert p["conv_msg_approx"] is False
    assert p["conversations"] == 5 and p["messages"] == 20 and p["leads"] == 4
    pe = p["events"]
    assert pe["product_recs"] == 6          # SUM(meta->>'count')
    assert pe["link_clicks"] == 3 and pe["handoffs"] == 1
    assert pe["order_lookups"] == 0 and pe["configurator"] == 0
    assert pe["purchases"] == {"count": 2, "value": 5000}
    assert not any("period IN (" in q for q in fs.period_sqls)
    ok.append("days=7: pontos conv/msg + esemeny-szamlalok + purchase value")

    # === days=60: kozelites a havi usage-bol ===
    fs = FakeSession()
    d = await stats.stats(k="sk", days=60, session=fs)
    p = d["period"]
    assert p["conv_msg_approx"] is True
    assert p["conversations"] == 33 and p["messages"] == 77
    assert any("period IN (" in q for q in fs.period_sqls)
    ok.append("days=60: conv_msg_approx=True, havi usage-osszeg")

    # === egyeni from/to (friss, 30 napon beluli) ===
    now = datetime.now(timezone.utc)
    f_s = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    t_s = now.strftime("%Y-%m-%d")
    d = await stats.stats(k="sk", date_from=f_s, date_to=t_s, session=FakeSession())
    p = d["period"]
    assert p["label"] == "%s \u2013 %s" % (f_s, t_s)
    assert p["conv_msg_approx"] is False
    ok.append("from&to (friss): label + pontos ag")

    # === egyeni from/to (regi -> kozelites) ===
    f_s = (now - timedelta(days=100)).strftime("%Y-%m-%d")
    t_s = (now - timedelta(days=95)).strftime("%Y-%m-%d")
    d = await stats.stats(k="sk", date_from=f_s, date_to=t_s, session=FakeSession())
    p = d["period"]
    assert p["days"] == 6 and p["conv_msg_approx"] is True
    ok.append("from&to (regi): days szamitas + kozelites")

    # === parameter nelkul: NINCS period kulcs (visszafele kompatibilis) ===
    d = await stats.stats(k="sk", session=FakeSession())
    assert "period" not in d
    ok.append("parameter nelkul: valtozatlan valasz, nincs period kulcs")

    # === hibas parameterek -> 400 ===
    for kw in ({"days": 15}, {"date_from": "2026-01-01"},
               {"date_from": "rossz", "date_to": "2026-01-02"},
               {"date_from": "2026-02-01", "date_to": "2026-01-01"}):
        try:
            await stats.stats(k="sk", session=FakeSession(), **kw)
            assert False, "kellett volna 400: %r" % kw
        except ff.HTTPException as e:
            assert e.status_code == 400, kw
    ok.append("hibas days / fel-datum / rossz formatum / forditott sorrend -> 400")

    for line in ok:
        print("OK ", line)
    print("\nALL GOOD (m70 period)")


try:
    asyncio.run(main())
finally:
    for _n, _prev in _SNAP.items():
        if _prev is None:
            sys.modules.pop(_n, None)
        else:
            sys.modules[_n] = _prev

"""/stats + usage + unanswered teszt — injektált fake fastapi/sqlalchemy/redis (dev-gépen is fut).
Futtatás: python tests/test_stats.py

Lefedi: a /stats JSON KULCSRA-PONTOS shape-je (fake session a lekérdezésekre), unanswered
score/reasons aggregáció, eval_reasons (low_score/collect_lead/order_form), usage session-dedup.
"""
import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])
for n in ("app", "app.core", "app.api", "app.models", "app.services", "sqlalchemy", "sqlalchemy.dialects"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


# --- fake fastapi ---
ff = types.ModuleType("fastapi")
class _Router:
    def get(self, *a, **k):
        def deco(fn): return fn
        return deco
    def post(self, *a, **k):
        def deco(fn): return fn
        return deco
ff.APIRouter = _Router
ff.Depends = lambda x=None: x
ff.Query = lambda *a, **k: (a[0] if a else None)
class HTTPException(Exception):
    def __init__(self, status_code=500, detail=""): self.status_code = status_code; self.detail = detail
ff.HTTPException = HTTPException
class _Response:  # m44: stats.py mar importalja a fastapi.Response-t
    def __init__(self, content=None, media_type=None, headers=None):
        self.content = content; self.media_type = media_type; self.headers = headers or {}
ff.Response = _Response
sys.modules["fastapi"] = ff

# --- fake sqlalchemy.text + ext.asyncio + dialects.postgresql.insert ---
class _Text:
    def __init__(self, s): self.s = s
sa = sys.modules["sqlalchemy"]; sa.text = lambda s: _Text(s)
sa_async = types.ModuleType("sqlalchemy.ext.asyncio"); sa_async.AsyncSession = object
sys.modules["sqlalchemy.ext.asyncio"] = sa_async
sys.modules.setdefault("sqlalchemy.ext", types.ModuleType("sqlalchemy.ext")).__path__ = []

class _Col:
    def __init__(self, n): self.n = n
    def __add__(self, o): return f"{self.n}+{o}"
LAST_INSERT = {}
class _Insert:
    def values(self, **kw): self.vals = kw; return self
    def on_conflict_do_update(self, index_elements=None, set_=None): self.idx = index_elements; self.set_ = set_; return self
def _pg_insert(model):
    ins = _Insert(); LAST_INSERT["i"] = ins; return ins
pg = types.ModuleType("sqlalchemy.dialects.postgresql"); pg.insert = _pg_insert
sys.modules["sqlalchemy.dialects.postgresql"] = pg

# --- fake app.core.db + models ---
db = types.ModuleType("app.core.db"); db.get_session = lambda: None
sys.modules["app.core.db"] = db
fm = types.ModuleType("app.models.db_models")
class _UT: c = types.SimpleNamespace(messages=_Col("messages"), conversations=_Col("conversations"))
class Usage: __table__ = _UT
class Unanswered:
    def __init__(self, **kw): self.kw = kw
fm.Usage = Usage; fm.Unanswered = Unanswered
sys.modules["app.models.db_models"] = fm

# m44: a stats.py uj importja - fake stub, hogy dev-gepen openpyxl nelkul is fusson
ue = types.ModuleType("app.services.unanswered_export")
ue.build_unanswered_xlsx = lambda rows, transcripts=None: b"PK-fake"
sys.modules["app.services.unanswered_export"] = ue
ce = types.ModuleType("app.services.conversations_export")
ce.build_conversations_xlsx = lambda rows: b"xlsx"
sys.modules["app.services.conversations_export"] = ce

usage = _load("app.services.usage", f"{ROOT}/app/services/usage.py")
unans = _load("app.services.unanswered", f"{ROOT}/app/services/unanswered.py")
stats = _load("app.api.stats", f"{ROOT}/app/api/stats.py")

CP = datetime.now(timezone.utc).astimezone(stats.BUDAPEST).strftime("%Y-%m")
DT1 = datetime(2026, 6, 20, 10, tzinfo=timezone.utc)
DT2 = datetime(2026, 6, 19, 10, tzinfo=timezone.utc)
DT3 = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


class _Res:
    def __init__(self, rows=None, scalar=None): self._rows = rows or []; self._scalar = scalar
    def mappings(self): return self
    def first(self): return self._rows[0] if self._rows else None
    def all(self): return list(self._rows)
    def scalar(self): return self._scalar


class FakeSession:
    def __init__(self, tenant=True): self.tenant = tenant
    async def execute(self, t, params=None):
        s = t.s
        if "FROM tenants t LEFT JOIN plans" in s:
            return _Res([] if not self.tenant else [{
                "client_id": "t1", "plan": "pro", "platform": "sellvio", "bot_name": "Bot",
                "header_color": "#fff", "white_label": True, "live_api": True, "monthly_limit": 500}])
        if "FROM usage WHERE client_id=:c AND period" in s:
            return _Res([{"conversations": 10, "messages": 25}])
        if "SUM(conversations)" in s:
            return _Res([{"c": 40, "m": 100}])
        if "period, conversations, messages FROM usage" in s:
            return _Res([{"period": CP, "conversations": 10, "messages": 25},
                         {"period": "2020-01", "conversations": 30, "messages": 75}])
        if "FROM leads WHERE client_id=:c GROUP BY 1" in s:   # by-period (specifikusabb, COUNT-ot is tartalmaz)
            return _Res([{"period": CP, "n": 3}, {"period": "2020-01", "n": 4}])
        if "COUNT(*) n FROM leads" in s:
            return _Res(scalar=7)
        if "name,email,phone,message,created_at FROM leads" in s:
            return _Res([{"name": "A", "email": "a@b", "phone": "1", "message": "hi", "created_at": DT1}])
        if "rating, COUNT(*) n FROM feedback" in s:
            return _Res([{"rating": "up", "n": 5}, {"rating": "down", "n": 2}])
        if "rating='down'" in s:
            return _Res([{"question": "rossz", "answer": "a", "page_context": {"url": "u"}, "created_at": DT1}])
        if "FROM events WHERE client_id=:c GROUP BY 1,2" in s:
            return _Res([{"kind": "link_click", "period": CP, "n": 4, "s": 0},
                         {"kind": "product_rec", "period": CP, "n": 2, "s": 5},
                         {"kind": "order_lookup", "period": "2020-01", "n": 3, "s": 0}])
        if "AS impressions" in s:   # m38 (parhuzamos) engagement-SQL — a link_click ag ELOTT,
            # mert az engagement-query is tartalmazza a kind='link_click' szoveget
            return _Res([{"impressions": 30, "chatted": 12, "clicked": 6}])
        if "MIN(created_at) FROM events" in s:
            return _Res(scalar=None)
        if "kind='link_click'" in s:
            return _Res([{"url": "https://x/p1", "title": "P1", "n": 4}])
        if "COUNT(DISTINCT session_id)" in s:
            return _Res(scalar=4.5)
        if "EXTRACT(HOUR" in s:
            return _Res([{"h": 9, "n": 7}, {"h": 14, "n": 3}])
        if "FROM unanswered" in s:
            return _Res([{"question": "miért?", "score": 0.10, "reasons": ["low_score"], "session_id": "s1", "created_at": DT1},
                         {"question": "miért?", "score": 0.20, "reasons": ["collect_lead"], "session_id": "s2", "created_at": DT2},
                         {"question": "hol?", "score": 0.30, "reasons": [], "session_id": None, "created_at": DT3}])
        return _Res()
    async def execute_commit(self): pass


async def main():
    ok = []

    # === eval_reasons ===
    assert unans.eval_reasons(0.10, None) == ["low_score"]
    assert unans.eval_reasons(0.90, "collect_lead") == ["collect_lead"]
    assert unans.eval_reasons(0.20, "order_status_form") == ["low_score", "order_form"]
    assert unans.eval_reasons(0.90, None) == []
    ok.append("eval_reasons: low_score/collect_lead/order_form kombinációk")

    # === /stats shape ===
    d = await stats.stats(k="sk", session=FakeSession())
    for key in ("client_id", "plan", "platform", "bot_name", "header_color", "white_label", "live_api",
                "monthly_limit", "generated_at", "current_period", "current", "limit_pct", "totals",
                "conversion_rate", "monthly", "leads", "feedback", "unanswered"):
        assert key in d, key
    assert d["white_label"] is True and d["live_api"] is True and d["monthly_limit"] == 500
    assert d["generated_at"].endswith("Z") and d["current_period"] == CP
    assert d["current"] == {"period": CP, "conversations": 10, "messages": 25,
                            "order_lookups": 0, "product_recs": 5, "leads": 3}
    assert d["limit_pct"] == 2                                # round(10/500*100)
    assert d["totals"] == {"conversations": 40, "messages": 100, "leads": 7,
                           "order_lookups": 3, "product_recs": 5}
    assert d["conversion_rate"] == 17.5                       # round(7/40*100,1)
    assert [m["period"] for m in d["monthly"]] == sorted([CP, "2020-01"])   # ASC
    assert d["leads"][0]["name"] == "A" and d["leads"][0]["created"].endswith("Z")
    assert d["feedback"] == {"total": 7, "up": 5, "down": 2,
                             "down_items": [{"question": "rossz", "answer": "a",
                                             "created": stats._iso(DT1), "page_context": {"url": "u"}}]}
    ok.append("/stats: kulcsra-pontos shape + current/totals/limit_pct/conversion_rate/monthly/leads/feedback")

    # === events + conversation_stats (m22) ===
    ev = d["events"]
    assert ev["link_clicks"] == {"total": 4, "current": 4,
                                 "top": [{"url": "https://x/p1", "title": "P1", "count": 4}]}
    assert ev["handoffs"] == {"total": 0, "current": 0}
    assert ev["configurator"] == {"total": 0, "current": 0}
    cs = d["conversation_stats"]
    assert cs["avg_messages"] == 4.5 and cs["window_days"] == 30
    assert cs["hourly"][9] == 7 and cs["hourly"][14] == 3 and sum(cs["hourly"]) == 10 and len(cs["hourly"]) == 24
    ok.append("events (link_clicks/handoffs/configurator + product_rec SUM) + conversation_stats (avg/hourly)")

    # === unanswered aggregáció ===
    ua = d["unanswered"]
    assert ua["total"] == 3
    qs = ua["questions"]
    assert qs[0]["question"] == "miért?" and qs[0]["count"] == 2          # count DESC
    assert qs[0]["score"] == 0.1                                          # latest (DESC első) score
    assert qs[0]["reasons"] == ["collect_lead", "low_score"]             # union, sorted
    assert qs[0]["last_ts"] == stats._iso(DT1)
    assert qs[0]["sessions"] == ["s1", "s2"]                              # m22: session-lista a visszanézőhöz
    assert qs[1]["sessions"] == []                                        # None session_id -> üres
    assert qs[1]["question"] == "hol?" and qs[1]["count"] == 1
    assert ua["current_week_label"] == stats._iso_week(datetime.now(timezone.utc))
    assert all(set(w) == {"week", "count"} for w in ua["weekly"])
    ok.append("/stats unanswered: questions count DESC + score(latest) + reasons(union) + weekly ISO")

    # === 404 ismeretlen stat_key ===
    try:
        await stats.stats(k="x", session=FakeSession(tenant=False))
        assert False, "kellett volna 404"
    except ff.HTTPException as e:
        assert e.status_code == 404
    ok.append("/stats: ismeretlen stat_key -> 404")

    # === usage: current_period + record_usage (Redis dedup) ===
    assert len(usage.current_period()) == 7 and usage.current_period()[4] == "-"

    class FakeRedis:
        def __init__(self, added): self._added = added; self.expired = False
        async def sadd(self, k, v): return self._added
        async def expire(self, k, ttl): self.expired = True
    class CapSession:
        def __init__(self): self.executed = False; self.committed = False
        async def execute(self, stmt): self.executed = True
        async def commit(self): self.committed = True
        async def rollback(self): pass

    # új session -> conversations a values-ban + a set_-ben, expire beállítva
    s1 = CapSession()
    await usage.record_usage(s1, FakeRedis(added=1), "c1", "sess1")
    ins = LAST_INSERT["i"]
    assert ins.vals["messages"] == 1 and ins.vals["conversations"] == 1
    assert ins.set_["messages"] == "messages+1" and ins.set_.get("conversations") == "conversations+1"
    assert s1.executed and s1.committed
    # visszatérő session -> conversations 0 a values-ban, NINCS a set_-ben
    await usage.record_usage(CapSession(), FakeRedis(added=0), "c1", "sess1")
    ins2 = LAST_INSERT["i"]
    assert ins2.vals["conversations"] == 0 and "conversations" not in ins2.set_
    ok.append("usage: új session -> conversations+1; visszatérő -> csak messages+1")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

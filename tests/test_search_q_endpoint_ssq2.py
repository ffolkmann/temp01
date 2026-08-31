"""ssq/2: GET /search/q vegpont (app/api/search.py) - a suite s2-konvencioja szerint
fajlbol toltve (fake app.core.db + app.services.events, sys.modules VISSZAALLITVA),
a kereso-mag (app/services/searchq.py) fajlbol, a Qdrant memoria-fake-kel.
"""

import asyncio
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import types

_PREFIXES = ("sqlalchemy", "fastapi", "starlette")
_sa_snapshot = {k: v for k, v in sys.modules.items() if k.split(".")[0] in _PREFIXES}
for _k in list(_sa_snapshot):
    del sys.modules[_k]
import sqlalchemy  # noqa: E402,F401
import sqlalchemy.ext.asyncio  # noqa: E402,F401
import fastapi  # noqa: E402,F401
import starlette  # noqa: E402,F401

ROOT = pathlib.Path(__file__).resolve().parents[1]

_KEYS = ("app", "app.core", "app.services", "app.core.db", "app.services.events")
_prev_mods = {k: sys.modules.get(k) for k in _KEYS}

for _name in ("app", "app.core", "app.services"):
    _m = types.ModuleType(_name)
    _m.__path__ = []
    sys.modules[_name] = _m

LOGGED: list[tuple] = []


async def _fake_get_session():  # pragma: no cover
    yield None


async def _fake_log_event(session, client_id, session_id, kind, meta=None):
    LOGGED.append((client_id, session_id, kind, meta))


_db = types.ModuleType("app.core.db")
_db.get_session = _fake_get_session
sys.modules["app.core.db"] = _db

_ev = types.ModuleType("app.services.events")
_ev.log_event = _fake_log_event
sys.modules["app.services.events"] = _ev

_spec = importlib.util.spec_from_file_location("search_ssq2_under_test", ROOT / "app" / "api" / "search.py")
SS = importlib.util.module_from_spec(_spec)
sys.modules["search_ssq2_under_test"] = SS
_spec.loader.exec_module(SS)

for _k, _v in _prev_mods.items():
    if _v is None:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _v

for _k in [x for x in list(sys.modules) if x.split(".")[0] in _PREFIXES]:
    del sys.modules[_k]
sys.modules.update(_sa_snapshot)


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sq = _load("app/services/searchq.py", "ssq2ep_searchq")
qo = _load("app/search/qdrantout.py", "ssq2ep_qdrantout")


# --------------------------------------------------------------------------- #
# segedek
# --------------------------------------------------------------------------- #
class _Scalar:
    def __init__(self, v):
        self._v = v

    def scalar(self):
        return self._v


class FakeSession:
    def __init__(self, cfg):
        self.cfg = cfg

    async def execute(self, stmt, params=None):
        return _Scalar(self.cfg)


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b, self.text = status, body, json.dumps(body)

    def json(self):
        return self._b


class FakeQdrant:
    """Minimal: count = minden pont, query = pontok score-ral, facet ures."""

    def __init__(self, points, fail=False):
        self.points, self.fail = points, fail

    async def post(self, path, json=None):
        if self.fail:
            raise RuntimeError("qdrant down")
        if path.endswith("/points/count"):
            return _Resp({"result": {"count": len(self.points)}})
        if path.endswith("/points/query"):
            return _Resp({"result": {"points": [{"id": p["id"], "score": 1.0, "payload": p["payload"]}
                                                for p in self.points][:json.get("limit", 10)]}})
        if path.endswith("/points/scroll"):
            return _Resp({"result": {"points": [{"id": p["id"], "payload": p["payload"]} for p in self.points]}})
        if path.endswith("/facet"):
            return _Resp({"result": {"hits": []}})
        return _Resp({}, 404)


def _profile(tmp, cid="t"):
    row = {"i": "1", "k": "WF-M5899", "n": "Epson WF-M5899", "b": "Epson", "c": "Nyomtató",
           "p": 180000, "a": 1, "u": "/p1", "m": "i1.jpg", "d": 20000}
    pt, terms = qo.make_point(cid, row, ["technologia=Tintasugaras"])
    d = os.path.join(tmp, cid + "-q")
    os.makedirs(d)
    json.dump({"tenant": cid, "v": "v1", "count": 1, "url_prefix": "https://x.hu",
               "img_prefix": "https://x.hu/i/", "collection": "cx_search_t_1", "alias": "cx_search_t"},
              open(os.path.join(d, "manifest.json"), "w", encoding="utf-8"))
    json.dump({"v": "v1", "count": 1, "terms": sorted([[t, 1] for t in terms])},
              open(os.path.join(d, "vocab.json"), "w", encoding="utf-8"))
    sq._cache.clear()
    return [pt]


class _Services:
    """A handler lazy `from app.services import searchq` importja ezt kapja."""

    def __enter__(self):
        self.prev = {k: sys.modules.get(k) for k in ("app", "app.services", "app.services.searchq")}
        app = types.ModuleType("app")
        app.__path__ = []
        svc = types.ModuleType("app.services")
        svc.__path__ = []
        svc.searchq = sq
        sys.modules["app"] = app
        sys.modules["app.services"] = svc
        sys.modules["app.services.searchq"] = sq
        return self

    def __exit__(self, *a):
        for k, v in self.prev.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _call(cfg, **kw):
    args = dict(client_id="t", q="epson", limit=8, offset=0, sort="rel", facets=0, fb=[], fc=[],
                fpr="", fpx=[], avail=0, session_id="", session=FakeSession(cfg))
    args.update(kw)
    with _Services():
        return asyncio.run(SS.search_q(**args))


def _body(resp):
    return json.loads(resp.body.decode("utf-8"))


# --------------------------------------------------------------------------- #
# tesztek
# --------------------------------------------------------------------------- #
def test_q_404_when_tenant_or_server_disabled():
    LOGGED.clear()
    with tempfile.TemporaryDirectory() as tmp:
        SS._qclient = FakeQdrant(_profile(tmp))
        old = sq.ROOT
        sq.ROOT = tmp
        try:
            assert _call({}).status_code == 404
            assert _call({"enabled": True}).status_code == 404                       # nincs server-blokk
            assert _call({"enabled": True, "server": {"enabled": False}}).status_code == 404
            assert _call({"enabled": True, "server": {"enabled": True}}, client_id="").status_code == 404
        finally:
            sq.ROOT = old
    assert not LOGGED


def test_q_200_hits_and_ss_q_event():
    LOGGED.clear()
    cfg = {"enabled": True, "server": {"enabled": True}}
    with tempfile.TemporaryDirectory() as tmp:
        SS._qclient = FakeQdrant(_profile(tmp))
        old = sq.ROOT
        sq.ROOT = tmp
        try:
            r = _call(cfg, session_id="s1")
            assert r.status_code == 200
            b = _body(r)
            assert b["total"] == 1 and b["hits"][0]["k"] == "WF-M5899" and b["hits"][0]["a"] == 1
            assert b["url_prefix"] == "https://x.hu" and b["mode"] == "and"
            assert r.headers.get("cache-control", "").startswith("public, max-age=")
            # ures q: nincs esemeny
            r2 = _call(cfg, q="")
            assert r2.status_code == 200 and _body(r2)["mode"] == "none"
        finally:
            sq.ROOT = old
    assert len(LOGGED) == 1
    cid, sid, kind, meta = LOGGED[0]
    assert (cid, sid, kind) == ("t", "s1", "ss_q")
    assert meta["q"] == "epson" and meta["total"] == 1 and meta["mode"] == "and" and meta["f"] == 0


def test_q_404_no_profile_and_503_backend():
    LOGGED.clear()
    cfg = {"enabled": True, "server": {"enabled": True}}
    with tempfile.TemporaryDirectory() as tmp:
        old = sq.ROOT
        sq.ROOT = tmp
        try:
            SS._qclient = FakeQdrant([])
            sq._cache.clear()
            assert _call(cfg).status_code == 404            # nincs <tenant>-q profil a webrooton
            SS._qclient = FakeQdrant(_profile(tmp), fail=True)
            assert _call(cfg).status_code == 503
        finally:
            sq.ROOT = old
    assert not LOGGED


def test_settings_server_flag():
    """ssq/3a: a /search/settings `server` mezoje a search_config.server.enabled-bol."""

    def _settings(cfg):
        with _Services():
            resp = asyncio.run(SS.search_settings(client_id="t", session=FakeSession(cfg)))
        return json.loads(resp.body.decode("utf-8"))

    assert _settings({})["server"] is False
    assert _settings({"server": {"enabled": False}})["server"] is False
    assert _settings({"server": True})["server"] is False
    assert _settings({"server": {"enabled": True}})["server"] is True

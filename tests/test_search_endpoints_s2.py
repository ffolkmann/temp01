"""S2 — SmartSearch widget-végpontok (app/api/search.py).

Fájlból töltve (suite-konvenció): a modul csak az ``app.core.db`` és
``app.services.events`` neveket importálja az app-csomagból — ezeket fake
modulokkal adjuk, majd VISSZAÁLLÍTJUK a sys.modules eredeti állapotát, hogy a
többi teszt (fájl-betöltős és app-importos egyaránt) ne szennyeződjön.
"""

import asyncio
import importlib.util
import json
import os
import pathlib
import sys
import types

# a suite mas tesztjei fake `starlette`/`fastapi`/`sqlalchemy` modulokat tehetnek a
# sys.modules-be (fajl-betoltos minta) - ezert ezeket kivesszuk, frissen importaljuk,
# majd a modul betoltese utan PONTOSAN visszaallitjuk az eredeti allapotot
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


async def _fake_get_session():  # pragma: no cover — csak Depends-alapértelmezés
    yield None


async def _fake_log_event(session, client_id, session_id, kind, meta=None):
    LOGGED.append((client_id, session_id, kind, meta))


_db = types.ModuleType("app.core.db")
_db.get_session = _fake_get_session
sys.modules["app.core.db"] = _db

_ev = types.ModuleType("app.services.events")
_ev.log_event = _fake_log_event
sys.modules["app.services.events"] = _ev

_path = ROOT / "app" / "api" / "search.py"
_spec = importlib.util.spec_from_file_location("search_s2_under_test", _path)
SS = importlib.util.module_from_spec(_spec)
sys.modules["search_s2_under_test"] = SS
_spec.loader.exec_module(SS)

for _k, _v in _prev_mods.items():
    if _v is None:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _v

for _k in [x for x in list(sys.modules) if x.split(".")[0] in _PREFIXES]:
    del sys.modules[_k]
sys.modules.update(_sa_snapshot)


# --------------------------------------------------------------------------- #
# segédek
# --------------------------------------------------------------------------- #
class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalar(self):
        return None


class _Session:
    """Fake AsyncSession: az SQL szövege alapján adja vissza a sorokat."""

    def __init__(self, terms=None, ids=None, boom=False):
        self.terms = terms or []
        self.ids = ids or []
        self.boom = boom
        self.calls = 0

    async def execute(self, stmt, params=None):
        self.calls += 1
        if self.boom:
            raise RuntimeError("db down")
        return _Rows(self.terms if "ss_search" in str(stmt) else self.ids)


class _Req:
    def __init__(self, raw: bytes):
        self._raw = raw

    async def body(self) -> bytes:
        return self._raw


def _write_cfg(tmp_path, tenants):
    p = tmp_path / "smartsearch.json"
    p.write_text(json.dumps({"tenants": tenants}), encoding="utf-8")
    return str(p)


def _with_cfg(path):
    os.environ["SS_CONFIG"] = path


def _clear_cfg():
    os.environ.pop("SS_CONFIG", None)


def _body(resp):
    return json.loads(resp.body.decode("utf-8"))


# --------------------------------------------------------------------------- #
# normalizálók
# --------------------------------------------------------------------------- #
def test_norm_groups_min_ket_tag():
    assert SS.norm_groups([["felni", "kerek"], ["magaban"], "nem lista", []]) == [["felni", "kerek"]]


def test_norm_groups_max_nyolc_tag_es_trim():
    out = SS.norm_groups([[" a ", "b", "c", "d", "e", "f", "g", "h", "i"]])
    assert out == [["a", "b", "c", "d", "e", "f", "g", "h"]]


def test_norm_oneway():
    out = SS.norm_oneway([
        {"f": "noti", "t": ["notebook", "laptop"]},
        {"f": "", "t": ["x"]},
        {"f": "a", "t": []},
        "nem dict",
    ])
    assert out == [{"f": "noti", "t": ["notebook", "laptop"]}]


def test_active_merch_idoablak():
    import datetime

    rules = [
        {"kw": ["felni"], "skus": ["A1"], "w": "front", "from": "2026-08-01", "to": "2026-08-31"},
        {"kw": [], "skus": ["B2"], "w": "back", "to": "2026-07-31"},          # lejart
        {"kw": [], "skus": ["C3"], "w": "up", "from": "2026-09-01"},          # jovobeni
        {"kw": [], "skus": ["D4"], "w": "nemletezo"},                          # rossz suly
        {"kw": [], "skus": [], "w": "front"},                                  # nincs sku
    ]
    out = SS.active_merch(rules, today=datetime.date(2026, 8, 4))
    assert [r["skus"] for r in out] == [["A1"]]
    assert out[0]["w"] == "front" and out[0]["kw"] == ["felni"]


def test_active_merch_hatarnap_inkluziv():
    import datetime

    rule = [{"skus": ["A"], "w": "front", "from": "2026-08-04", "to": "2026-08-04"}]
    assert len(SS.active_merch(rule, today=datetime.date(2026, 8, 4))) == 1
    assert SS.active_merch(rule, today=datetime.date(2026, 8, 5)) == []


def test_pick_terms_prefix_dedup_es_min_hossz():
    out = SS.pick_terms(["la", "lap", "lapto", "laptop", "  szonyeg  ", "szonyeg"])
    assert out == ["laptop", "szonyeg"]


def test_pick_terms_cap():
    assert len(SS.pick_terms(["aaa", "bbb", "ccc", "ddd", "eee", "fff", "ggg", "hhh", "iii"])) == 8


def test_int_clamp():
    assert SS._int("12") == 12
    assert SS._int(None) == 0
    assert SS._int("abc") == 0
    assert SS._int(-5) == 0
    assert SS._int(10**12) == 10**9


# --------------------------------------------------------------------------- #
# konfiguráció
# --------------------------------------------------------------------------- #
def test_load_config_ismeretlen_tenant_ures(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True}}))
    try:
        assert SS.load_config("teslashop") == {"enabled": True}
        assert SS.load_config("nincsilyen") == {}
        assert SS.load_config("") == {}
    finally:
        _clear_cfg()


def test_load_config_hianyzo_fajl_ures():
    _with_cfg("/nincs/ilyen/utvonal/smartsearch.json")
    try:
        assert SS.load_config("teslashop") == {}
    finally:
        _clear_cfg()


# --------------------------------------------------------------------------- #
# GET /search/settings
# --------------------------------------------------------------------------- #
def test_settings_kezi_listak_nem_kerdezik_a_dbt(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {
        "enabled": True,
        "synonyms": [["felni", "kerek"]],
        "oneway": [{"f": "noti", "t": ["notebook"]}],
        "popular_terms": ["felni"],
        "popular_skus": ["SKU1"],
    }}))
    try:
        sess = _Session(terms=[("nemkell", 9, 9)])
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=sess)))
    finally:
        _clear_cfg()
    assert sess.calls == 1          # s3: csak a search_config lekerdezes
    assert body["groups"] == [["felni", "kerek"]]
    assert body["oneway"] == [{"f": "noti", "t": ["notebook"]}]
    assert body["popular_terms"] == ["felni"]
    assert body["popular_skus"] == ["SKU1"]
    assert body["popular_ids"] == []


def test_settings_auto_listak_az_esemenyekbol(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True}}))
    try:
        sess = _Session(
            terms=[("szonyeg", 40, 40), ("nulla talalatos", 12, 0), ("szo", 5, 5)],
            ids=[("101", 9), ("202", 4), ("", 2)],
        )
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=sess)))
    finally:
        _clear_cfg()
    assert body["popular_terms"] == ["szonyeg"]        # a 0 talalatos kiesik
    assert body["popular_ids"] == ["101", "202"]        # az ures pid kiesik
    assert sess.calls == 3          # s3: +1 a search_config lekerdezes


def test_settings_kikapcsolt_tenant_nem_kerdez(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": False}}))
    try:
        sess = _Session(terms=[("x", 1, 1)])
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=sess)))
    finally:
        _clear_cfg()
    assert sess.calls == 1          # s3: csak a search_config lekerdezes
    assert body["popular_terms"] == [] and body["groups"] == []


def test_settings_db_hiba_eseten_is_valid_valasz(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True}}))
    try:
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=_Session(boom=True))))
    finally:
        _clear_cfg()
    assert body["popular_terms"] == [] and body["popular_ids"] == []


def test_settings_ai_flag_alapbol_hamis(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True, "popular_terms": ["a"], "popular_skus": ["s"]}}))
    try:
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=_Session())))
    finally:
        _clear_cfg()
    assert body["ai"] is False


def test_settings_ai_flag_a_db_configbol(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {}))
    try:
        sess = _CfgSession(cfg={"enabled": True, "ai_answer": True, "popular_terms": ["a"], "popular_skus": ["s"]})
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=sess)))
    finally:
        _clear_cfg()
    assert body["ai"] is True


def test_settings_cache_header(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True, "popular_terms": ["a"], "popular_skus": ["s"]}}))
    try:
        resp = asyncio.run(SS.search_settings(client_id="teslashop", session=_Session()))
    finally:
        _clear_cfg()
    assert "max-age=300" in resp.headers.get("cache-control", "")


# --------------------------------------------------------------------------- #
# POST /search/event
# --------------------------------------------------------------------------- #
def _post(payload, tmp_path, tenants=None):
    LOGGED.clear()
    _with_cfg(_write_cfg(tmp_path, tenants if tenants is not None else {"teslashop": {"enabled": True}}))
    try:
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        resp = asyncio.run(SS.search_event(request=_Req(raw), session=None))
    finally:
        _clear_cfg()
    return resp


def test_event_naplozza_es_vagja_a_metat(tmp_path):
    resp = _post({
        "client_id": "teslashop", "session_id": "ss-1", "event": "ss_search",
        "meta": {"q": "x" * 300, "pid": "42", "total": "17", "extra": 1},
    }, tmp_path)
    assert resp.status_code == 204
    assert len(LOGGED) == 1
    cid, sid, kind, meta = LOGGED[0]
    assert (cid, sid, kind) == ("teslashop", "ss-1", "ss_search")
    assert len(meta["q"]) == 120
    assert meta["total"] == 17 and meta["pid"] == "42" and meta["extra"] == 1


def test_event_mindharom_fajta_atmegy(tmp_path):
    for kind in ("ss_search", "ss_click", "ss_purchase"):
        _post({"client_id": "teslashop", "event": kind, "meta": {}}, tmp_path)
        assert len(LOGGED) == 1, kind
        assert LOGGED[0][2] == kind


def test_event_ismeretlen_fajta_eldobva(tmp_path):
    assert _post({"client_id": "teslashop", "event": "link_click"}, tmp_path).status_code == 204
    assert LOGGED == []


def test_event_ismeretlen_vagy_kikapcsolt_tenant_eldobva(tmp_path):
    _post({"client_id": "nincsilyen", "event": "ss_search"}, tmp_path)
    assert LOGGED == []
    _post({"client_id": "teslashop", "event": "ss_search"}, tmp_path, tenants={"teslashop": {"enabled": False}})
    assert LOGGED == []


def test_event_rossz_body_nem_dob(tmp_path):
    assert _post(b"nem json", tmp_path).status_code == 204
    assert LOGGED == []
    assert _post(b"[1,2,3]", tmp_path).status_code == 204
    assert LOGGED == []
    assert _post(b"", tmp_path).status_code == 204
    assert LOGGED == []


def test_event_hianyzo_meta_es_session(tmp_path):
    _post({"client_id": "teslashop", "event": "ss_click"}, tmp_path)
    cid, sid, kind, meta = LOGGED[0]
    assert sid is None
    assert meta == {"q": "", "pid": "", "total": 0, "extra": 0}


# --------------------------------------------------------------------------- #
# S3: tenants.search_config (jsonb) az igazsag-forras, a fajl a fallback
# --------------------------------------------------------------------------- #
class _One:
    def __init__(self, value):
        self._v = value

    def scalar(self):
        return self._v


class _CfgSession:
    """Fake session: a search_config lekerdezes kulon agon, a tobbi mint a _Session."""

    def __init__(self, cfg=None, boom=False, terms=None, ids=None):
        self.cfg = cfg
        self.boom = boom
        self.terms = terms or []
        self.ids = ids or []
        self.calls = 0

    async def execute(self, stmt, params=None):
        self.calls += 1
        s = str(stmt)
        if "search_config" in s:
            if self.boom:
                raise RuntimeError("db down")
            return _One(self.cfg)
        return _Rows(self.terms if "ss_search" in s else self.ids)


def test_s3_db_config_elsobbseget_elvez_a_fajl_felett(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True, "popular_terms": ["fajlbol"]}}))
    try:
        sess = _CfgSession(cfg={"enabled": True, "popular_terms": ["dbbol"]})
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=sess)))
    finally:
        _clear_cfg()
    assert body["popular_terms"] == ["dbbol"]


def test_s3_ures_vagy_rossz_db_config_eseten_a_fajl_jon(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True, "popular_terms": ["fajlbol"]}}))
    try:
        for empty in (None, {}, "nem json", 42, []):
            sess = _CfgSession(cfg=empty)
            body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=sess)))
            assert body["popular_terms"] == ["fajlbol"], empty
    finally:
        _clear_cfg()


def test_s3_db_hiba_eseten_a_fajl_jon(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True, "popular_terms": ["fajlbol"]}}))
    try:
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=_CfgSession(boom=True))))
    finally:
        _clear_cfg()
    assert body["popular_terms"] == ["fajlbol"]


def test_s3_db_config_string_jsonkent_is_jo(tmp_path):
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True}}))
    try:
        sess = _CfgSession(cfg=json.dumps({"enabled": True, "popular_terms": ["stringbol"]}))
        body = _body(asyncio.run(SS.search_settings(client_id="teslashop", session=sess)))
    finally:
        _clear_cfg()
    assert body["popular_terms"] == ["stringbol"]


def test_s3_event_db_configbol_engedelyezve(tmp_path):
    LOGGED.clear()
    _with_cfg(_write_cfg(tmp_path, {}))            # a fajlban NINCS ilyen tenant
    try:
        sess = _CfgSession(cfg={"enabled": True})
        raw = json.dumps({"client_id": "ujshop", "event": "ss_search", "meta": {}}).encode("utf-8")
        resp = asyncio.run(SS.search_event(request=_Req(raw), session=sess))
    finally:
        _clear_cfg()
    assert resp.status_code == 204
    assert len(LOGGED) == 1 and LOGGED[0][0] == "ujshop"


def test_s3_event_db_configban_kikapcsolva(tmp_path):
    LOGGED.clear()
    _with_cfg(_write_cfg(tmp_path, {"teslashop": {"enabled": True}}))   # a fajl szerint MENNE
    try:
        sess = _CfgSession(cfg={"enabled": False})
        raw = json.dumps({"client_id": "teslashop", "event": "ss_search", "meta": {}}).encode("utf-8")
        resp = asyncio.run(SS.search_event(request=_Req(raw), session=sess))
    finally:
        _clear_cfg()
    assert resp.status_code == 204
    assert LOGGED == []

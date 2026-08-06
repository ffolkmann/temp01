"""S6/2 tesztek: POST /search/answer (app/api/search.py).

Fajlbol toltve, mint a test_search_endpoints_s2.py. KULONBSEG: a vegpont ket LAZY
importot hasznal (``app.services.searchanswer`` es ``app.core.llm``), amelyek a HIVAS
pillanataban futnak - addigra a suite tobbi fajl-betoltos tesztje mar felulirhatta a
sys.modules-t. Ezert minden hivas kore beinjektaljuk a VALODI searchanswer modult es
egy fake llm-et, majd PONTOSAN visszaallitjuk az elozo allapotot (a fake llm nem
szivaroghat at a tobbi tesztre).
"""

import asyncio
import contextlib
import importlib.util
import json
import os
import pathlib
import sys
import types

# a suite mas tesztjei fake `starlette`/`fastapi`/`sqlalchemy` modulokat tehetnek a
# sys.modules-be -> kivesszuk, frissen importaljuk, majd PONTOSAN visszaallitjuk
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


async def _fake_get_session():  # pragma: no cover - csak Depends-alapertelmezes
    yield None


async def _fake_log_event(session, client_id, session_id, kind, meta=None):
    return None


_db = types.ModuleType("app.core.db")
_db.get_session = _fake_get_session
sys.modules["app.core.db"] = _db

_ev = types.ModuleType("app.services.events")
_ev.log_event = _fake_log_event
sys.modules["app.services.events"] = _ev

_spec = importlib.util.spec_from_file_location(
    "search_s62_under_test", ROOT / "app" / "api" / "search.py")
SS = importlib.util.module_from_spec(_spec)
sys.modules["search_s62_under_test"] = SS
_spec.loader.exec_module(SS)

for _k, _v in _prev_mods.items():
    if _v is None:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _v

for _k in [x for x in list(sys.modules) if x.split(".")[0] in _PREFIXES]:
    del sys.modules[_k]
sys.modules.update(_sa_snapshot)

# a VALODI searchanswer (stdlib-only) - a vegpont ezt hivja, nem stub
_sa_spec = importlib.util.spec_from_file_location(
    "searchanswer_s62_real", ROOT / "app" / "services" / "searchanswer.py")
SA = importlib.util.module_from_spec(_sa_spec)
_sa_spec.loader.exec_module(SA)


# --------------------------------------------------------------------------- #
# fake LLM (a hivasokat naplozza; kivetelt is tud dobni)
# --------------------------------------------------------------------------- #
CALLS: list = []
REPLY: list = [""]


async def _fake_generate_reply(system, history, message, model=None):
    CALLS.append({"system": system, "history": history, "message": message, "model": model})
    out = REPLY[0]
    if isinstance(out, BaseException):
        raise out
    return out


_llm = types.ModuleType("app.core.llm")
_llm.generate_reply = _fake_generate_reply

_MISS = object()
_INJECT_MODULES = (("app.services.searchanswer", SA), ("app.core.llm", _llm))
_INJECT_ATTRS = (("app.services", "searchanswer", SA), ("app.core", "llm", _llm))


@contextlib.contextmanager
def _patched():
    """A lazy importok a HIVAS pillanataban futnak - ide injektalunk, majd takaritunk."""
    prev_mods = {k: sys.modules.get(k, _MISS) for k, _ in _INJECT_MODULES}
    made = []
    for name in ("app", "app.core", "app.services"):
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.__path__ = []
            sys.modules[name] = m
            made.append(name)
    prev_attrs = {}
    for pkg, attr, val in _INJECT_ATTRS:
        prev_attrs[(pkg, attr)] = getattr(sys.modules[pkg], attr, _MISS)
        setattr(sys.modules[pkg], attr, val)
    for name, mod in _INJECT_MODULES:
        sys.modules[name] = mod
    try:
        yield
    finally:
        for (pkg, attr), old in prev_attrs.items():
            if old is _MISS:
                try:
                    delattr(sys.modules[pkg], attr)
                except Exception:  # noqa: BLE001
                    pass
            else:
                setattr(sys.modules[pkg], attr, old)
        for name, old in prev_mods.items():
            if old is _MISS:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
        for name in made:
            sys.modules.pop(name, None)


# --------------------------------------------------------------------------- #
# segedek
# --------------------------------------------------------------------------- #
class _One:
    def __init__(self, value):
        self._v = value

    def scalar(self):
        return self._v


class _Sess:
    """Fake session: search_config es chat_model kulon agon."""

    def __init__(self, cfg=None, model=None, boom=False):
        self.cfg = cfg
        self.model = model
        self.boom = boom
        self.calls = 0

    async def execute(self, stmt, params=None):
        self.calls += 1
        if self.boom:
            raise RuntimeError("db down")
        return _One(self.model if "chat_model" in str(stmt) else self.cfg)


class _Req:
    def __init__(self, raw):
        self._raw = raw

    async def body(self):
        return self._raw


OK_REPLY = json.dumps({"a": "Ez a huzat illik a Model Y-hoz.", "pids": ["1"]},
                      ensure_ascii=False)


def _reset():
    SS._ai_cache.clear()
    SS._ai_calls.clear()
    CALLS.clear()
    REPLY[0] = OK_REPLY


def _cands(n=2):
    return [{"i": str(i + 1), "n": "TESERY termek %d" % (i + 1), "a": 1} for i in range(n)]


def _payload(q="melyik uleshuzat illik a Model Y-hoz", total=42, force=True, cands=None):
    return {"client_id": "teslashop", "q": q, "total": total, "force": force,
            "candidates": _cands() if cands is None else cands}


def _post(payload, sess=None):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    # nincs fajl-fallback: a teszt csak a DB-configot hasznalja
    os.environ["SS_CONFIG"] = "/nincs/ilyen/utvonal/smartsearch.json"
    try:
        with _patched():
            resp = asyncio.run(SS.search_answer(request=_Req(raw), session=sess or _Sess()))
    finally:
        os.environ.pop("SS_CONFIG", None)
    return json.loads(resp.body.decode("utf-8"))


# --------------------------------------------------------------------------- #
# boldog ut
# --------------------------------------------------------------------------- #
def test_boldog_ut_valasz_pidek_es_prompt():
    _reset()
    out = _post(_payload(), _Sess(cfg={"enabled": True}, model="claude-haiku-4-5"))
    assert out["pids"] == ["1"] and out["cached"] == 0
    assert "Model Y" in out["answer"]
    assert len(CALLS) == 1
    assert CALLS[0]["model"] == "claude-haiku-4-5"      # tenant-felulbiralat atmegy
    assert CALLS[0]["history"] == []                    # nincs beszelgetes-elozmeny
    assert "[1]" in CALLS[0]["message"] and "[2]" in CALLS[0]["message"]
    assert "Ft" not in CALLS[0]["message"]              # arat nem adunk az LLM-nek


def test_chat_model_nelkul_globalis_alapmodell():
    _reset()
    out = _post(_payload(), _Sess(cfg={"enabled": True}, model=None))
    assert out["pids"] == ["1"]
    assert CALLS[0]["model"] is None


def test_tenant_kapcsolo_force_nelkul_is_enged():
    _reset()
    out = _post(_payload(force=False), _Sess(cfg={"enabled": True, "ai_answer": True}))
    assert out["pids"] == ["1"] and len(CALLS) == 1


# --------------------------------------------------------------------------- #
# kapuk (LLM-hivas NELKUL kell elvernie)
# --------------------------------------------------------------------------- #
def test_kapu_ki_nincs_llm_hivas():
    _reset()
    assert _post(_payload(force=False), _Sess(cfg={"enabled": True})) == {}
    assert CALLS == []


def test_kikapcsolt_vagy_ismeretlen_tenant_force_ellenere_sem_hiv():
    _reset()
    assert _post(_payload(), _Sess(cfg={"enabled": False})) == {}
    assert _post(_payload(), _Sess(cfg=None)) == {}
    assert _post(_payload(), _Sess(boom=True)) == {}
    assert CALLS == []


def test_trigger_nem_teljesul_sima_kereses():
    _reset()
    sess = _Sess(cfg={"enabled": True, "ai_answer": True})
    assert _post(_payload(q="uleshuzat", total=120, force=False), sess) == {}
    assert CALLS == []
    # ugyanez nulla talalattal MAR fut (nincs jo talalat -> segitunk)
    assert _post(_payload(q="uleshuzat", total=0, force=False), sess)["pids"] == ["1"]
    assert len(CALLS) == 1


def test_nincs_ervenyes_jelolt():
    _reset()
    sess = _Sess(cfg={"enabled": True})
    assert _post(_payload(cands=[]), sess) == {}
    assert _post(_payload(cands=[{"i": "1", "n": "Elfogyott", "a": 0}]), sess) == {}
    assert _post(_payload(cands="szemet"), sess) == {}
    assert CALLS == []


def test_rossz_body_es_hianyzo_mezok():
    _reset()
    sess = _Sess(cfg={"enabled": True})
    assert _post(b"nem json", sess) == {}
    assert _post(b"[1,2,3]", sess) == {}
    assert _post(b"", sess) == {}
    assert _post({"client_id": "teslashop", "force": True}, sess) == {}
    assert _post({"q": "melyik jo ide?", "force": True}, sess) == {}
    assert CALLS == []


# --------------------------------------------------------------------------- #
# cache es napi plafon
# --------------------------------------------------------------------------- #
def test_cache_a_masodik_hivas_nem_hiv_llmet():
    _reset()
    sess = _Sess(cfg={"enabled": True})
    first = _post(_payload(), sess)
    second = _post(_payload(q="MELYIK ULESHUZAT illik a Model Y-hoz"), sess)   # norm_q azonos
    assert first["answer"] == second["answer"] and first["pids"] == second["pids"]
    assert (first["cached"], second["cached"]) == (0, 1)
    assert len(CALLS) == 1


def test_cache_tenantonkent_kulon():
    _reset()
    sess = _Sess(cfg={"enabled": True})
    _post(_payload(), sess)
    masik = dict(_payload(), client_id="notebookstore")
    assert _post(masik, sess)["cached"] == 0
    assert len(CALLS) == 2


def test_napi_plafon_felett_nincs_hivas():
    _reset()
    sess = _Sess(cfg={"enabled": True, "ai_daily_cap": 1})
    assert _post(_payload(q="melyik szonyeg jo ide"), sess)["pids"] == ["1"]
    assert _post(_payload(q="melyik felni illik ra"), sess) == {}
    assert len(CALLS) == 1


def test_plafon_nulla_teljesen_kikapcsol():
    _reset()
    assert _post(_payload(), _Sess(cfg={"enabled": True, "ai_daily_cap": 0})) == {}
    assert CALLS == []


def test_ai_cap_ertekek():
    assert SS.ai_cap({}) == SS.AI_DAILY_CAP
    assert SS.ai_cap({"ai_daily_cap": ""}) == SS.AI_DAILY_CAP
    assert SS.ai_cap({"ai_daily_cap": None}) == SS.AI_DAILY_CAP
    assert SS.ai_cap({"ai_daily_cap": 5}) == 5
    assert SS.ai_cap({"ai_daily_cap": "7"}) == 7
    assert SS.ai_cap({"ai_daily_cap": 0}) == 0


def test_cache_lejar_es_nem_no_a_vegtelensegig():
    SS._ai_cache.clear()
    SS.ai_cache_put(("t", "a"), {"answer": "x", "pids": ["1"]})
    assert SS.ai_cache_get(("t", "a"))["answer"] == "x"
    SS._ai_cache[("t", "a")] = (0.0, {"answer": "x", "pids": ["1"]})      # osregi bejegyzes
    assert SS.ai_cache_get(("t", "a")) is None
    for i in range(SS.AI_CACHE_MAX + 10):
        SS.ai_cache_put(("t", str(i)), {"answer": "x", "pids": ["1"]})
    assert len(SS._ai_cache) <= SS.AI_CACHE_MAX
    SS._ai_cache.clear()


# --------------------------------------------------------------------------- #
# hibas / gyenge LLM-valasz -> nincs sav, de nincs 500 sem
# --------------------------------------------------------------------------- #
def test_llm_hiba_nincs_500():
    _reset()
    REPLY[0] = RuntimeError("LLM 529 overloaded")
    assert _post(_payload(), _Sess(cfg={"enabled": True})) == {}
    assert len(CALLS) == 1


def test_ertelmezhetetlen_valasz_nincs_sav_es_nincs_cache():
    _reset()
    REPLY[0] = "Szia! Ezt ajanlom neked."
    sess = _Sess(cfg={"enabled": True})
    assert _post(_payload(), sess) == {}
    assert _post(_payload(), sess) == {}
    assert len(CALLS) == 2          # a sikertelen valasz NEM kerul cache-be


def test_hallucinalt_pid_nem_kerul_ki():
    _reset()
    REPLY[0] = json.dumps({"a": "Ez a termek tokeletesen illik hozza.", "pids": ["999"]})
    assert _post(_payload(), _Sess(cfg={"enabled": True})) == {}


def test_ar_nem_kerul_a_valaszba():
    _reset()
    REPLY[0] = json.dumps(
        {"a": "Ez a huzat illik a Model Y-hoz. Ara 45 900 Ft.", "pids": ["1"]},
        ensure_ascii=False)
    out = _post(_payload(), _Sess(cfg={"enabled": True}))
    assert out["pids"] == ["1"]
    assert "Ft" not in out["answer"] and "45" not in out["answer"]

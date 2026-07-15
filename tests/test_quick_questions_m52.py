"""m52 - gyorskerdes-gombok (tenants.quick_questions + chat-config).
Fajlbol toltve (suite-konvencio, mint test_handoff_keywords_m50.py)."""

import importlib.util
import pathlib
import sys
import types

_PFX = ("sqlalchemy", "fastapi", "starlette", "pydantic", "httpx", "anyio")
_sa_snapshot = {k: v for k, v in sys.modules.items() if any(k == _p or k.startswith(_p + ".") for _p in _PFX)}
for _k in list(_sa_snapshot):
    del sys.modules[_k]
import sqlalchemy  # noqa: E402,F401
import sqlalchemy.dialects.postgresql  # noqa: E402,F401
import sqlalchemy.ext.asyncio  # noqa: E402,F401
import sqlalchemy.orm  # noqa: E402,F401

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _name in ("app", "app.core", "app.services", "app.models", "app.api"):
    _m = sys.modules.setdefault(_name, types.ModuleType(_name))
    _m.__path__ = []


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


_stub("app.core.db", get_session=lambda: None)
_stub("app.core.settings", get_settings=lambda: types.SimpleNamespace())
_stub("app.services.current_product",
      get_current_product=lambda *a, **k: None,
      normalize_url=lambda u: u)
_stub("app.services.operator_notify", notify_operators_ex=lambda *a, **k: None)
_load("app.models.db_models", ROOT / "app" / "models" / "db_models.py")
_cfg = _load("config_m52_under_test", ROOT / "app" / "api" / "config.py")

for _k in [x for x in list(sys.modules) if any(x == _p or x.startswith(_p + ".") for _p in _PFX)]:
    del sys.modules[_k]
sys.modules.update(_sa_snapshot)


def _tenant(qq, enabled=True):
    return types.SimpleNamespace(
        plan=None, popup_config={}, use_fastapi=True, search_fallback=False,
        launcher_config={}, bot_name="Bot", header_color="#fff", bubble_color=None,
        welcome_message="hi", launcher_position=None, launcher_anim=None,
        auto_open=False, auto_open_delay=None, proactive_message=None,
        proactive_product_message=None, quick_questions=qq,
        quick_questions_enabled=enabled,
    )


def test_config_body_qq_enabled():
    assert _cfg._config_body(_tenant(["a", "b"]))["quick_questions"] == ["a", "b"]


def test_config_body_qq_disabled():
    assert _cfg._config_body(_tenant(["a"], enabled=False))["quick_questions"] == []


def test_config_body_qq_null():
    assert _cfg._config_body(_tenant(None))["quick_questions"] == []


def test_config_body_no_tenant():
    assert _cfg._config_body(None)["quick_questions"] == []


def test_parse_newlines():
    assert _cfg._parse_quick_questions("egy\n ketto \n\nharom") == ["egy", "ketto", "harom"]


def test_parse_json_array():
    assert _cfg._parse_quick_questions('["a","b"]') == ["a", "b"]


def test_parse_keeps_commas():
    assert _cfg._parse_quick_questions("a, b es c") == ["a, b es c"]


def test_parse_empty_is_none():
    assert _cfg._parse_quick_questions("") is None
    assert _cfg._parse_quick_questions("[]") is None


def test_parse_item_cap():
    assert len(_cfg._parse_quick_questions("\n".join("q%d" % i for i in range(30)))) == 10


def test_parse_len_cap():
    assert _cfg._parse_quick_questions(["x" * 500])[0] == "x" * 120

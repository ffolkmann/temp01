"""m50 - tenant-specifikus handoff-kifejezesek (tenants.handoff_keywords).
Fajlbol toltve (suite-konvencio, mint test_operator_live_m46.py)."""

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

def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m

_load("app.models.db_models", ROOT / "app" / "models" / "db_models.py")
_load("app.services.handoff_offer", ROOT / "app" / "services" / "handoff_offer.py")
_it = _load("intent_m50_under_test", ROOT / "app" / "services" / "intent.py")

for _k in [x for x in list(sys.modules) if x == "sqlalchemy" or x.startswith("sqlalchemy.")]:
    del sys.modules[_k]
sys.modules.update(_sa_snapshot)


def _tenant(kws=None):
    return types.SimpleNamespace(lead_email="", handoff_keywords=kws)


def test_builtin_patterns_still_work():
    assert _it.detect_handoff("emberrel szeretnek beszelni", _tenant()).is_handoff is True
    assert _it.detect_handoff("mennyibe kerul a szallitas?", _tenant()).is_handoff is False


def test_custom_keyword_matches_accented_message():
    t = _tenant(["reklamacio"])
    assert _it.detect_handoff("Reklam\u00e1ci\u00f3t szeretn\u00e9k beny\u00fajtani!", t).is_handoff is True


def test_accented_keyword_matches_plain_message():
    t = _tenant(["visszak\u00fcld\u00e9s"])
    assert _it.detect_handoff("a visszakuldes erdekel", t).is_handoff is True


def test_keyword_no_match_stays_bot():
    t = _tenant(["reklamacio"])
    assert _it.detect_handoff("van keszleten a gep?", t).is_handoff is False


def test_short_keyword_ignored():
    t = _tenant(["ok", "hm"])
    assert _it.detect_handoff("ok koszi", t).is_handoff is False


def test_none_and_garbage_config_safe():
    assert _it.detect_handoff("teszt uzenet", _tenant(None)).is_handoff is False
    assert _it.detect_handoff("teszt uzenet", _tenant([None, 42, ""])).is_handoff is False


def test_missing_attribute_safe():
    t = types.SimpleNamespace(lead_email="")
    assert _it.detect_handoff("teszt uzenet", t).is_handoff is False

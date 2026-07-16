"""m53 - 529 (overloaded) retry a llm.generate_reply-ben.
Fajlbol toltve, stubolt anthropic modullal (suite-konvencio)."""

import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _name in ("app", "app.core", "app.models"):
    _m = sys.modules.setdefault(_name, types.ModuleType(_name))
    _m.__path__ = []


class FakeStatusError(Exception):
    def __init__(self, status_code):
        super().__init__("status %s" % status_code)
        self.status_code = status_code


class _FakeMessages:
    def __init__(self):
        self.calls = 0
        self.script = []
        self.models = []

    async def create(self, **kw):
        self.calls += 1
        self.models.append(kw.get("model"))
        act = self.script.pop(0)
        if isinstance(act, Exception):
            raise act
        return act


class FakeAsyncAnthropic:
    def __init__(self, **kw):
        self.messages = _FakeMessages()


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


_anthropic_snapshot = sys.modules.get("anthropic")
_stub("anthropic", AsyncAnthropic=FakeAsyncAnthropic, APIStatusError=FakeStatusError)
_stub("app.core.settings", get_settings=lambda: types.SimpleNamespace(
    anthropic_api_key="x", chat_model="m", max_tokens=10))
_stub("app.models.schemas", HistoryItem=type("HistoryItem", (), {}))

spec = importlib.util.spec_from_file_location("llm_m53_under_test", ROOT / "app" / "core" / "llm.py")
_llm = importlib.util.module_from_spec(spec)
sys.modules["llm_m53_under_test"] = _llm
spec.loader.exec_module(_llm)
_llm._RETRY_SLEEPS = (0.0, 0.0)

if _anthropic_snapshot is not None:
    sys.modules["anthropic"] = _anthropic_snapshot
else:
    sys.modules.pop("anthropic", None)


def _ok_resp(text="ok"):
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])


def _fresh_client(script):
    c = FakeAsyncAnthropic()
    c.messages.script = list(script)
    _llm._client = c
    return c.messages


async def test_immediate_success():
    m = _fresh_client([_ok_resp("valasz")])
    assert await _llm.generate_reply("sys", [], "hi") == "valasz"
    assert m.calls == 1


async def test_529_then_success():
    m = _fresh_client([FakeStatusError(529), FakeStatusError(529), _ok_resp()])
    assert await _llm.generate_reply("sys", [], "hi") == "ok"
    assert m.calls == 3


async def test_529_exhausted_falls_back_to_sonnet():
    m = _fresh_client([FakeStatusError(529)] * 3 + [_ok_resp("sonnet-valasz")])
    assert await _llm.generate_reply("sys", [], "hi") == "sonnet-valasz"
    assert m.calls == 4
    assert m.models[-1] == _llm._FALLBACK_MODEL
    assert m.models[0] != _llm._FALLBACK_MODEL


async def test_529_everything_down_raises():
    m = _fresh_client([FakeStatusError(529)] * 4)
    with pytest.raises(FakeStatusError):
        await _llm.generate_reply("sys", [], "hi")
    assert m.calls == 4


async def test_non_529_raises_immediately():
    m = _fresh_client([FakeStatusError(400)])
    with pytest.raises(FakeStatusError):
        await _llm.generate_reply("sys", [], "hi")
    assert m.calls == 1


async def test_model_override_used():
    m = _fresh_client([_ok_resp()])
    await _llm.generate_reply("sys", [], "hi", model="custom-model")
    assert m.models == ["custom-model"]


async def test_default_model_when_no_override():
    m = _fresh_client([_ok_resp()])
    await _llm.generate_reply("sys", [], "hi")
    assert m.models == ["m"]

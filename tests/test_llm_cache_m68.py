"""m68 - prompt-cache: a generate_reply a (statikus, dinamikus) system-part
cache_control-os blokklistava alakitja; str tovabbra is str marad.
Fajlbol toltve, stubolt anthropic modullal (m53-konvencio)."""

import importlib.util
import pathlib
import sys
import types

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
        self.systems = []

    async def create(self, **kw):
        self.calls += 1
        self.models.append(kw.get("model"))
        self.systems.append(kw.get("system"))
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

spec = importlib.util.spec_from_file_location(
    "llm_m68_under_test", ROOT / "app" / "core" / "llm.py")
_llm = importlib.util.module_from_spec(spec)
sys.modules["llm_m68_under_test"] = _llm
spec.loader.exec_module(_llm)
_llm._RETRY_SLEEPS = (0.0, 0.0)

if _anthropic_snapshot is not None:
    sys.modules["anthropic"] = _anthropic_snapshot
else:
    sys.modules.pop("anthropic", None)


def _ok_resp(text="ok"):
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])


def _ok_resp_usage(text="ok"):
    u = types.SimpleNamespace(input_tokens=5, cache_creation_input_tokens=100,
                              cache_read_input_tokens=0, output_tokens=7)
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)], usage=u)


def _fresh_client(script):
    c = FakeAsyncAnthropic()
    c.messages.script = list(script)
    _llm._client = c
    return c.messages


async def test_tuple_becomes_cached_blocks():
    m = _fresh_client([_ok_resp("v")])
    assert await _llm.generate_reply(("STAT", "DYN"), [], "hi") == "v"
    sysp = m.systems[0]
    assert isinstance(sysp, list) and len(sysp) == 2
    assert sysp[0]["text"] == "STAT"
    assert sysp[0]["cache_control"] == {"type": "ephemeral"}
    assert sysp[1] == {"type": "text", "text": "DYN"}


async def test_empty_dynamic_single_block():
    m = _fresh_client([_ok_resp()])
    await _llm.generate_reply(("STAT", ""), [], "hi")
    sysp = m.systems[0]
    assert isinstance(sysp, list) and len(sysp) == 1
    assert sysp[0]["cache_control"] == {"type": "ephemeral"}


async def test_str_passthrough():
    m = _fresh_client([_ok_resp()])
    await _llm.generate_reply("sys", [], "hi")
    assert m.systems[0] == "sys"


async def test_fallback_model_gets_same_blocks():
    m = _fresh_client([FakeStatusError(529)] * 3 + [_ok_resp("f")])
    assert await _llm.generate_reply(("STAT", "DYN"), [], "hi") == "f"
    assert m.models[-1] == _llm._FALLBACK_MODEL
    assert m.systems[-1] == m.systems[0]
    assert m.systems[-1][0]["cache_control"] == {"type": "ephemeral"}


async def test_usage_logging_failsafe():
    m = _fresh_client([_ok_resp_usage("u")])
    assert await _llm.generate_reply(("STAT", "DYN"), [], "hi") == "u"

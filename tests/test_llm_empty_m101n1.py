"""m101/1: ures (text-blokk nelkuli) LLM-valasz -> egy ujraproba. Fajlbol toltve,
stubolt anthropic/settings/schemas modulokkal, context managerben (sys.modules visszaall)."""
import asyncio
import contextlib
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _FakeStatusError(Exception):
    def __init__(self, status_code):
        super().__init__("status %s" % status_code)
        self.status_code = status_code


class _FakeMessages:
    def __init__(self):
        self.calls = 0
        self.script = []

    async def create(self, **kw):
        self.calls += 1
        return self.script.pop(0)


class _FakeAnthropic:
    def __init__(self, **kw):
        self.messages = _FakeMessages()


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


@contextlib.contextmanager
def _fake_modules(mods):
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _load():
    fakes = {
        "anthropic": _mod("anthropic", AsyncAnthropic=_FakeAnthropic, APIStatusError=_FakeStatusError),
        "app.core.settings": _mod("app.core.settings", get_settings=lambda: types.SimpleNamespace(
            anthropic_api_key="x", chat_model="m", max_tokens=10)),
        "app.models.schemas": _mod("app.models.schemas", HistoryItem=type("HistoryItem", (), {})),
    }
    with _fake_modules(fakes):
        spec = importlib.util.spec_from_file_location("llm_m101n1_test", ROOT / "app" / "core" / "llm.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    m._RETRY_SLEEPS = (0.0, 0.0)
    return m


llm = _load()


def _text(t):
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=t)], stop_reason="end_turn")


def _empty():
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="thinking", thinking="...")],
                                 stop_reason="end_turn")


def _run(script):
    llm._client.messages.calls = 0
    llm._client.messages.script = list(script)
    out = asyncio.run(llm.generate_reply("SP", [], "kerdes"))
    return out, llm._client.messages.calls


def test_normal_valasz_egy_hivas():
    assert _run([_text('{"reply": "szia"}')]) == ('{"reply": "szia"}', 1)


def test_ures_valasz_ujraprobal_es_sikerul():
    assert _run([_empty(), _text('{"reply": "ok"}')]) == ('{"reply": "ok"}', 2)


def test_ketszer_ures_marad_ures_nincs_harmadik_hivas():
    assert _run([_empty(), _empty()]) == ("", 2)


def test_ures_content_lista_is_ujraproba():
    r = types.SimpleNamespace(content=[], stop_reason="end_turn")
    assert _run([r, _text("x")]) == ("x", 2)

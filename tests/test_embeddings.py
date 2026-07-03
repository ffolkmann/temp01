"""embed_texts throttle-reset teszt — _throttle._events.clear().
Futtatás: python tests/test_embeddings.py
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])
for n in ("app", "app.core"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []

# --- fake openai ---
SCRIPT = {"acts": [], "calls": 0, "inputs": []}


class RateLimitError(Exception):
    def __init__(self, msg="429", retry_after=None):
        super().__init__(msg)
        self.response = types.SimpleNamespace(
            headers={"retry-after": str(retry_after)} if retry_after else {})


class APIError(Exception):
    pass


class _Emb:
    async def create(self, model, input):
        i = SCRIPT["calls"]; SCRIPT["calls"] += 1; SCRIPT["inputs"].append(list(input))
        act = SCRIPT["acts"][i] if i < len(SCRIPT["acts"]) else "ok"
        if act == "429":
            raise RateLimitError()
        if act.startswith("429:"):
            raise RateLimitError(retry_after=float(act.split(":")[1]))
        if act == "apierr":
            raise APIError("boom")
        return types.SimpleNamespace(
            data=[types.SimpleNamespace(embedding=[0.1, 0.2]) for _ in input])


class AsyncOpenAI:
    def __init__(self, *a, **k): self.embeddings = _Emb()


fo = types.ModuleType("openai")
fo.AsyncOpenAI = AsyncOpenAI; fo.RateLimitError = RateLimitError; fo.APIError = APIError
sys.modules["openai"] = fo

# --- fake settings (magas TPM -> retry-tesztek nem throttle-olnak) ---
fs = types.ModuleType("app.core.settings")
fs.get_settings = lambda: types.SimpleNamespace(
    openai_api_key="x", embed_model="text-embedding-3-small",
    embed_tpm_limit=10_000_000, embed_max_retries=3)
sys.modules["app.core.settings"] = fs

spec = importlib.util.spec_from_file_location("emb_under_test", f"{ROOT}/app/core/embeddings.py")
emb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emb)

SLEPT = []
emb.asyncio = types.SimpleNamespace(sleep=lambda s: (SLEPT.append(s), asyncio.sleep(0))[1])


def reset(acts=None):
    SCRIPT.update(acts=acts or [], calls=0, inputs=[])
    SLEPT.clear()
    emb._throttle._events.clear()


async def main():
    ok = []

    # 1) reset clears throttle events
    reset()
    assert list(emb._throttle._events) == [], "throttle events not empty after reset"
    ok.append("reset() clears _throttle._events")

    # 2) normal embed call after reset
    reset(["ok"])
    out = await emb.embed_texts(["hello"])
    assert len(out) == 1 and SCRIPT["calls"] == 1
    ok.append("embed_texts: single text succeeds after reset")

    # 3) batch call after reset
    reset(["ok"])
    assert list(emb._throttle._events) == []
    out = await emb.embed_texts(["a", "b"])
    assert len(out) == 2
    reset()
    assert list(emb._throttle._events) == []
    ok.append("throttle events cleared on each reset")

    # 4) empty input -> no API call
    reset([])
    out = await emb.embed_texts([])
    assert out == [] and SCRIPT["calls"] == 0
    ok.append("empty input -> [] (no API call)")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")


asyncio.run(main())

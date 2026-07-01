"""embed_texts teszt — TPM throttle + robusztus 429/APIError retry (injektált fake openai).
Futtatás: python tests/test_embed.py
"""
import asyncio
import importlib.util
import sys
import types

ROOT = "/home/folkm/chatbot"
for n in ("app", "app.core"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []

# --- fake openai ---
SCRIPT = {"acts": [], "calls": 0, "inputs": []}
class RateLimitError(Exception):
    def __init__(self, msg="429", retry_after=None):
        super().__init__(msg)
        self.response = types.SimpleNamespace(headers={"retry-after": str(retry_after)} if retry_after else {})
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
        return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[0.1, 0.2, 0.3, 0.4]) for _ in input])
class AsyncOpenAI:
    def __init__(self, *a, **k): self.embeddings = _Emb()
fo = types.ModuleType("openai")
fo.AsyncOpenAI = AsyncOpenAI; fo.RateLimitError = RateLimitError; fo.APIError = APIError
sys.modules["openai"] = fo

# --- fake settings (magas TPM -> a retry-tesztek nem throttle-olnak) ---
fs = types.ModuleType("app.core.settings")
fs.get_settings = lambda: types.SimpleNamespace(
    openai_api_key="x", embed_model="text-embedding-3-small",
    embed_tpm_limit=10_000_000, embed_max_retries=8)
sys.modules["app.core.settings"] = fs

spec = importlib.util.spec_from_file_location("emb_under_test", f"{ROOT}/app/core/embeddings.py")
emb = importlib.util.module_from_spec(spec); spec.loader.exec_module(emb)

# a backoff-sleepet gyorsítsuk + rögzítsük (a throttle magas TPM miatt itt nem alszik)
SLEPT = []
emb.asyncio = types.SimpleNamespace(sleep=lambda s: (SLEPT.append(s), asyncio.sleep(0))[1])


def reset(acts):
    SCRIPT.update(acts=acts, calls=0, inputs=[]); SLEPT.clear()


async def main():
    ok = []

    # 1) 429 kétszer -> retry -> siker
    reset(["429", "429", "ok"])
    out = await emb.embed_texts(["a", "b"])
    assert len(out) == 2 and SCRIPT["calls"] == 3 and len(SLEPT) == 2
    ok.append("429 x2 -> retry -> siker (3 hívás, 2 backoff)")

    # 2) retry-after tiszteletben tartva
    reset(["429:7", "ok"])
    await emb.embed_texts(["a"])
    assert 7.0 in SLEPT, SLEPT
    ok.append("retry-after (7s) tiszteletben tartva")

    # 3) APIError -> retry -> siker
    reset(["apierr", "ok"])
    out = await emb.embed_texts(["a"])
    assert len(out) == 1 and SCRIPT["calls"] == 2
    ok.append("APIError -> retry -> siker")

    # 4) retry kimerül (max_retries=8) -> DOB (az engine flush elkapja completion-first)
    reset(["429"] * 20)
    try:
        await emb.embed_texts(["a"])
        assert False, "kellett volna dobnia"
    except RateLimitError:
        assert SCRIPT["calls"] == 9         # max_retries+1 próba
    ok.append("retry kimerül -> RateLimitError dob (9 próba)")

    # 5) üres input -> nincs hívás
    reset([])
    assert await emb.embed_texts([]) == [] and SCRIPT["calls"] == 0
    ok.append("üres input -> [] (nincs hívás)")

    # 6) TPM throttle: budget felett acquire ALSZIK (60s ablak), majd (kiesés után) továbbenged
    clock = [0.0]; slept2 = []
    th = emb._TpmThrottle(limit=100)
    orig_time, orig_aio = emb.time, emb.asyncio
    async def fsleep(s): slept2.append(s); clock[0] += s
    emb.time = types.SimpleNamespace(monotonic=lambda: clock[0])
    emb.asyncio = types.SimpleNamespace(sleep=fsleep)
    await th.acquire(60)                     # 60 <= 100 -> nincs sleep
    assert slept2 == []
    await th.acquire(60)                     # 60+60=120 > 100 -> alszik, míg a régi (t=0) ki nem esik
    assert len(slept2) >= 1 and clock[0] >= 60   # a 60s ablakon túl jutott -> továbbengedett
    emb.time, emb.asyncio = orig_time, orig_aio
    ok.append("TPM throttle: budget felett alszik, ablak-kiesés után továbbenged")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")

asyncio.run(main())

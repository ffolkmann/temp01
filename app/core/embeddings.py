"""OpenAI text-embedding-3-small (1536 dim) — query (chat) + batch (sync).

A sync batch-embed (embed_texts) TPM-korlátos (nagy cold-start ~23M token / 1M TPM ≈ ~23 perc,
ez fizikai korlát): token-budget throttle (60s csúszóablak) pace-el a TPM alá, plusz robusztus
429/APIError retry (exponenciális backoff + retry-after tisztelet). A tényleges "ne dobjon a
streamből" completion-first az engine flush try/except-jében van (a purge így mindig lefusson).
"""

import asyncio
import logging
import time
from collections import deque

from openai import AsyncOpenAI

try:  # a hibatípusok az SDK-verziótól függően
    from openai import APIError, RateLimitError
except ImportError:  # pragma: no cover
    RateLimitError = APIError = Exception  # type: ignore

from app.core.settings import get_settings

logger = logging.getLogger("cx.embed")
_settings = get_settings()
_client = AsyncOpenAI(api_key=_settings.openai_api_key)


async def embed_query(text: str) -> list[float]:
    text = (text or " ").strip() or " "
    resp = await _client.embeddings.create(model=_settings.embed_model, input=text)
    return resp.data[0].embedding


# --- TPM throttle (60s csúszóablak, becsült token/hívás) -------------------- #
def _est_tokens(texts: list[str]) -> int:
    # durva becslés ~4 karakter/token; a throttle 85%-os headroommal fut a becslési hibára
    return max(1, sum(len(t) for t in texts) // 4)


class _TpmThrottle:
    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self._events: deque[tuple[float, int]] = deque()

    async def acquire(self, tokens: int) -> None:
        while True:
            now = time.monotonic()
            while self._events and self._events[0][0] <= now - 60:
                self._events.popleft()
            used = sum(t for _, t in self._events)
            if not self._events or used + tokens <= self.limit:
                self._events.append((now, tokens))
                return
            wait = 60 - (now - self._events[0][0]) + 0.05     # amíg a legrégebbi esemény kiesik
            await asyncio.sleep(min(max(wait, 0.05), 5.0))


_throttle = _TpmThrottle(int(_settings.embed_tpm_limit * 0.85))


def _retry_after(err) -> float | None:
    try:
        ra = err.response.headers.get("retry-after")
        return float(ra) if ra else None
    except Exception:  # noqa: BLE001
        return None


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch embedding a synchez — TPM-throttle + robusztus 429/APIError retry.

    UGYANAZ a modell, mint a query-embedding (a vektoroknak egyezniük kell). A retry kimerülése
    után DOB — az engine flush elkapja (completion-first: a batch kimarad, a stream/purge fut tovább).
    """
    clean = [(t or " ").strip() or " " for t in texts]
    if not clean:
        return []
    await _throttle.acquire(_est_tokens(clean))
    last_err: Exception | None = None
    for attempt in range(_settings.embed_max_retries + 1):
        try:
            resp = await _client.embeddings.create(model=_settings.embed_model, input=clean)
            return [d.embedding for d in resp.data]
        except RateLimitError as e:                       # 429 (TPM/RPM) -> retry-after v. exp backoff
            last_err = e
            delay = _retry_after(e) or min(2.0 ** attempt, 60.0)
            logger.warning("embed 429 (%d/%d) -> %.1fs backoff", attempt + 1, _settings.embed_max_retries, delay)
            await asyncio.sleep(delay)
        except APIError as e:                             # átmeneti API-hiba -> exp backoff
            last_err = e
            logger.warning("embed APIError (%d/%d): %s", attempt + 1, _settings.embed_max_retries, e)
            await asyncio.sleep(min(2.0 ** attempt, 30.0))
    raise last_err or RuntimeError("embed: retry kimerült")

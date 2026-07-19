"""Anthropic Haiku hívás (chat-válasz generálás)."""

import asyncio
import logging
import random

from anthropic import APIStatusError, AsyncAnthropic

from app.core.settings import get_settings
from app.models.schemas import HistoryItem

logger = logging.getLogger("cx.llm")

_settings = get_settings()
_client = AsyncAnthropic(api_key=_settings.anthropic_api_key)

_RETRY_SLEEPS = (1.5, 3.0)  # m53: 529-re ennyi varakozas a 2. es 3. probalkozas elott
_FALLBACK_MODEL = "claude-sonnet-4-6"  # m54: ha a fo modell 529-re kimerul, egy proba evvel


def _system_param(system_prompt):
    """m68: prompt-cache. (statikus, dinamikus) par -> system blokklista, a statikus
    blokkon cache_control=ephemeral (5 perces Anthropic prompt-cache; a cache-bol
    olvasott input ara a base 10%-a). Sima str valtozatlanul megy tovabb."""
    if isinstance(system_prompt, (tuple, list)):
        static = str(system_prompt[0] or "") if len(system_prompt) > 0 else ""
        dynamic = str(system_prompt[1] or "") if len(system_prompt) > 1 else ""
        blocks = []
        if static:
            blocks.append({
                "type": "text",
                "text": static,
                "cache_control": {"type": "ephemeral"},
            })
        if dynamic:
            blocks.append({"type": "text", "text": dynamic})
        return blocks if blocks else ""
    return system_prompt


def _log_usage(resp, model):
    """m68: cache-hatekonysag a kontener-logban (in/cache_w/cache_r/out). Fail-safe."""
    try:
        u = getattr(resp, "usage", None)
        if u is None:
            return
        logger.info(
            "llm usage model=%s in=%s cache_w=%s cache_r=%s out=%s",
            model,
            getattr(u, "input_tokens", None),
            getattr(u, "cache_creation_input_tokens", None),
            getattr(u, "cache_read_input_tokens", None),
            getattr(u, "output_tokens", None),
        )
    except Exception:  # noqa: BLE001 - a log soha ne torje a valaszt
        pass


async def generate_reply(
    system_prompt: str | tuple[str, str],
    history: list[HistoryItem],
    message: str,
    model: str | None = None,
) -> str:
    """A history utolsó (max 10) üzenete + az aktuális message a user turn.

    A history role-jai user/assistant; az aktuális message-et külön user turnként
    fűzzük a végére (a widget a history-ban NEM küldi az aktuális üzenetet).
    """
    messages: list[dict[str, str]] = []
    for h in history[-10:]:
        role = "assistant" if h.role == "assistant" else "user"
        if h.content:
            messages.append({"role": role, "content": h.content})
    messages.append({"role": "user", "content": message})

    # Anthropic megköveteli, hogy az első üzenet user legyen
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    _model = (model or "").strip() or _settings.chat_model  # m55: tenant-szintu felulbiralat
    # m53: 529 (overloaded_error) — app-szintu ujraprobalas az SDK sajat retry-jai folott
    _system = _system_param(system_prompt)  # m68: prompt-cache blokkok
    resp = None
    _used = _model
    for _delay in (*_RETRY_SLEEPS, None):
        try:
            resp = await _client.messages.create(
                model=_model,
                max_tokens=_settings.max_tokens,
                system=_system,
                messages=messages,
            )
            break
        except APIStatusError as err:
            if getattr(err, "status_code", None) != 529:
                raise
            if _delay is None:
                # m54: a fo modell tuloterhelt — utolso probalkozas masik tierrel
                _used = _FALLBACK_MODEL
                resp = await _client.messages.create(
                    model=_FALLBACK_MODEL,
                    max_tokens=_settings.max_tokens,
                    system=_system,
                    messages=messages,
                )
                break
            await asyncio.sleep(_delay + random.uniform(0, 0.5))
    # válasz: content[0].text (manual 1.)
    _log_usage(resp, _used)
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()

"""Anthropic Haiku hívás (chat-válasz generálás)."""

import asyncio
import random

from anthropic import APIStatusError, AsyncAnthropic

from app.core.settings import get_settings
from app.models.schemas import HistoryItem

_settings = get_settings()
_client = AsyncAnthropic(api_key=_settings.anthropic_api_key)

_RETRY_SLEEPS = (1.5, 3.0)  # m53: 529-re ennyi varakozas a 2. es 3. probalkozas elott


async def generate_reply(
    system_prompt: str,
    history: list[HistoryItem],
    message: str,
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

    # m53: 529 (overloaded_error) — app-szintu ujraprobalas az SDK sajat retry-jai folott
    resp = None
    for _delay in (*_RETRY_SLEEPS, None):
        try:
            resp = await _client.messages.create(
                model=_settings.chat_model,
                max_tokens=_settings.max_tokens,
                system=system_prompt,
                messages=messages,
            )
            break
        except APIStatusError as err:
            if getattr(err, "status_code", None) != 529 or _delay is None:
                raise
            await asyncio.sleep(_delay + random.uniform(0, 0.5))
    # válasz: content[0].text (manual 1.)
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()

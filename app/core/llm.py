"""Anthropic Haiku hívás (chat-válasz generálás)."""

from anthropic import AsyncAnthropic

from app.core.settings import get_settings
from app.models.schemas import HistoryItem

_settings = get_settings()
_client = AsyncAnthropic(api_key=_settings.anthropic_api_key)


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

    resp = await _client.messages.create(
        model=_settings.chat_model,
        max_tokens=_settings.max_tokens,
        system=system_prompt,
        messages=messages,
    )
    # válasz: content[0].text (manual 1.)
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()

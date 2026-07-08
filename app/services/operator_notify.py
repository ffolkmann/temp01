"""Operátor-értesítés Telegramon (m28 fázis5).

A meglévő „CX notify (Telegram)" n8n-workflow webhookján át küld:
POST body {chat_id, text}. Tenantonként TÖBB címzett: az operator_telegram_chat_id
vessző / újsor / pontosvessző / szóköz-elválasztott chatId-lista; mindegyikre külön POST.

Fail-safe: minden hiba csak logol — a /chat SOHA nem törhet meg egy Telegram-hiba miatt.
Ha a tenantnak nincs beállított chatId, NEM pingelünk (a wf-default chatId-t szándékosan
nem erőltetjük rá minden tenantra — így minden bolt a saját címzettjeit kapja, vagy semmit).
"""

import logging
import re

import httpx

logger = logging.getLogger("cx.operator_notify")

# a CX notify (Telegram) workflow webhookja — a chatbot-api és a n8n közös docker-
# networkön van (n8n-cxxz_default), így a n8n a konténer-nevén, BELSŐ porton (5678)
# érhető el (nem a host 1234-mappingen, és nem a publikus URL-en — az a konténerből
# hairpin miatt nem megy).
_NOTIFY_URL = "http://n8n-cxxz-n8n-1:5678/webhook/cx-notify-b41e88c2f7a3"
_OPERATOR_URL = "https://codexpress.cloud/chatbot/operator.html"

# chatId-elválasztók: vessző, pontosvessző, újsor, szóköz (bármely kombináció)
_SPLIT = re.compile(r"[\s,;]+")


def _parse_chat_ids(raw: str | None) -> list[str]:
    """A textarea/mező nyers tartalmából egyedi chatId-lista (sorrendtartó)."""
    if not raw:
        return []
    out: list[str] = []
    for tok in _SPLIT.split(str(raw).strip()):
        tok = tok.strip()
        if tok and tok not in out:
            out.append(tok)
    return out


def _compose(tenant, preview: str) -> str:
    shop = str(getattr(tenant, "client_id", "") or "")
    bot_name = str(getattr(tenant, "bot_name", "") or "")
    snippet = (preview or "").strip().replace("\n", " ")
    if len(snippet) > 160:
        snippet = snippet[:157] + "…"
    shop_line = shop + (f" ({bot_name})" if bot_name else "")
    return (
        "🔔 Új élő ügyintéző-kérés\n"
        f"Bolt: {shop_line}\n"
        f'Üzenet: „{snippet}”\n'
        f"Válasz: {_OPERATOR_URL}"
    )


async def notify_operators(tenant, preview: str) -> int:
    """Telegram-ping minden beállított chatId-re. Vissza: sikeres küldések száma.

    Fail-safe: kivételt nem propagál (csak logol).
    """
    chat_ids = _parse_chat_ids(getattr(tenant, "operator_telegram_chat_id", None))
    if not chat_ids:
        return 0
    text = _compose(tenant, preview)
    sent = 0
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            for cid in chat_ids:
                try:
                    r = await client.post(_NOTIFY_URL, json={"chat_id": cid, "text": text})
                    if r.status_code < 400:
                        sent += 1
                    else:
                        logger.warning("operator-notify: %s -> HTTP %s", cid, r.status_code)
                except Exception:  # noqa: BLE001
                    logger.exception("operator-notify: Telegram POST hiba chat_id=%s", cid)
    except Exception:  # noqa: BLE001
        logger.exception("operator-notify: httpx kliens hiba")
    return sent

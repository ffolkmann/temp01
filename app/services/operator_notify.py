"""Operátor-értesítés Telegramon (m28 fázis5, m31: per-tenant bot).

KÉT ÚT:
  1. `tenants.operator_bot_token` be van állítva -> KÖZVETLEN Telegram Bot API-hívás
     (`https://api.telegram.org/bot<token>/sendMessage`), n8n nélkül. Minden bolt a
     SAJÁT botjától kap értesítést.
  2. Nincs token -> a régi, központi „CX notify (Telegram)" n8n-workflow webhookja.
     Ez ugyanaz a bot, mint az „Anna" személyi asszisztens — külső ügyfélnek ezért
     mindig saját botot adjunk.

Tenantonként TÖBB címzett: az `operator_telegram_chat_id` vessző / újsor /
pontosvessző / szóköz-elválasztott chatId-lista; mindegyikre külön küldés.

Fail-safe: minden hiba csak logol — a /chat SOHA nem törhet meg egy Telegram-hiba
miatt. A tokent SEM logba, SEM hibaüzenetbe nem írjuk ki.

Ha a tenantnak nincs beállított chatId, NEM pingelünk (a wf-default chatId-t
szándékosan nem erőltetjük rá minden tenantra — így minden bolt a saját címzettjeit
kapja, vagy semmit).
"""

import logging
import re

import httpx

logger = logging.getLogger("cx.operator_notify")


class _RedactTelegramToken(logging.Filter):
    """A bot token SOHA ne kerüljön logba.

    Az httpx INFO-szinten kilogolja a teljes kért URL-t
    (`HTTP Request: POST https://api.telegram.org/bot<TOKEN>/sendMessage ...`),
    amiben ott a titok. A szűrő a `/bot<token>` részt `/bot***`-ra cseréli.
    Szándékosan a KIBOCSÁTÓ loggerekre tesszük fel (a filter nem öröklődik a
    propagáláskor, ezért a rooton nem lenne hatása).
    """

    _URL_RE = re.compile(r"/bot\d{5,16}:[A-Za-z0-9_-]{30,}")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 — a logolás sose törjön el
            return True
        if "/bot" in msg and self._URL_RE.search(msg):
            record.msg = self._URL_RE.sub("/bot***", msg)
            record.args = ()
        return True


_redactor = _RedactTelegramToken()
for _lg in ("httpx", "httpcore", "cx.operator_notify"):
    logging.getLogger(_lg).addFilter(_redactor)

# a CX notify (Telegram) workflow webhookja — a chatbot-api és a n8n közös docker-
# networkön van (n8n-cxxz_default), így a n8n a konténer-nevén, BELSŐ porton (5678)
# érhető el (nem a host 1234-mappingen, és nem a publikus URL-en — az a konténerből
# hairpin miatt nem megy).
_NOTIFY_URL = "http://n8n-cxxz-n8n-1:5678/webhook/cx-notify-b41e88c2f7a3"
_OPERATOR_URL = "https://codexpress.cloud/chatbot/operator.html"
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# chatId-elválasztók: vessző, pontosvessző, újsor, szóköz (bármely kombináció)
_SPLIT = re.compile(r"[\s,;]+")

# BotFather-token alakja: <bot_id>:<35 karakter körüli titok>
_TOKEN_RE = re.compile(r"^\d{5,16}:[A-Za-z0-9_-]{30,}$")

VIA_OWN = "sajat-bot"
VIA_CENTRAL = "kozponti-bot"


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


def bot_token(tenant) -> str:
    """A tenant SAJÁT bot tokenje, ha van és alakilag érvényes. PURE.

    Hibás alakú token -> "" (a küldés a központi botra esik vissza, hogy az
    értesítés ne tűnjön el némán; az admin „Teszt-üzenet" gombja megmutatja).
    """
    raw = str(getattr(tenant, "operator_bot_token", "") or "").strip()
    return raw if _TOKEN_RE.match(raw) else ""


def send_url(token: str) -> str:
    """Küldési URL: saját token -> Telegram Bot API, egyébként a központi webhook. PURE."""
    return _TELEGRAM_API.format(token=token) if token else _NOTIFY_URL


def _compose(tenant, preview: str, test: bool = False) -> str:
    shop = str(getattr(tenant, "client_id", "") or "")
    bot_name = str(getattr(tenant, "bot_name", "") or "")
    snippet = (preview or "").strip().replace("\n", " ")
    if len(snippet) > 160:
        snippet = snippet[:157] + "…"
    shop_line = shop + (f" ({bot_name})" if bot_name else "")
    head = "🧪 Teszt-üzenet (CX admin)" if test else "🔔 Új élő ügyintéző-kérés"
    return (
        f"{head}\n"
        f"Bolt: {shop_line}\n"
        f'Üzenet: „{snippet}”\n'
        f"Válasz: {_OPERATOR_URL}"
    )


async def notify_operators_ex(tenant, preview: str, test: bool = False) -> dict:
    """Ping minden beállított chatId-re. Vissza: {sent, total, via, error}.

    Fail-safe: kivételt nem propagál (csak logol). A token sosem kerül logba.
    """
    chat_ids = _parse_chat_ids(getattr(tenant, "operator_telegram_chat_id", None))
    if not chat_ids:
        return {"sent": 0, "total": 0, "via": None, "error": "nincs_chat_id"}

    token = bot_token(tenant)
    via = VIA_OWN if token else VIA_CENTRAL
    url = send_url(token)
    text = _compose(tenant, preview, test=test)
    sent = 0
    err: str | None = None

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            for cid in chat_ids:
                body: dict = {"chat_id": cid, "text": text}
                if token:
                    body["disable_web_page_preview"] = True
                try:
                    r = await client.post(url, json=body)
                    if r.status_code < 400:
                        sent += 1
                    else:
                        err = err or f"HTTP {r.status_code}"
                        logger.warning(
                            "operator-notify[%s]: %s -> HTTP %s", via, cid, r.status_code
                        )
                except Exception:  # noqa: BLE001
                    err = err or "kapcsolati_hiba"
                    logger.exception("operator-notify[%s]: POST hiba chat_id=%s", via, cid)
    except Exception:  # noqa: BLE001
        err = err or "httpx_kliens_hiba"
        logger.exception("operator-notify: httpx kliens hiba")

    return {"sent": sent, "total": len(chat_ids), "via": via, "error": err}


async def notify_operators(tenant, preview: str) -> int:
    """Visszafelé kompatibilis wrapper: a sikeres küldések száma."""
    return int((await notify_operators_ex(tenant, preview))["sent"])

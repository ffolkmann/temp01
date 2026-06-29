"""Rendelés-státusz ág — Sellvio order-lekérés + semleges válasz + e-mail.

A prod Chat workflow (7ZtoREZGxJUxLYFU) node-jainak portja:
"Sellvio Token (Order)" + "Get Order" + "Verify Order" + "Send Status Email"
(lásd seed/prod_retrieval.txt 67–77). MOST csak Sellvio (teslashop); SR/Unas/WC később.

Adatvédelem: a /chat VÁLASZ matched ÉS nem-matched esetben is UGYANAZ a semleges
szöveg, hogy ne szivárogjon rendelési adat. A státusz csak e-mailben megy a
rendeléskor használt címre, háttérben (schedule_email — a /chat latencyt nem növeli).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from app.core.mailer import schedule_email

if TYPE_CHECKING:
    from app.models.db_models import Tenant
    from app.services.intent import OrderIntent

logger = logging.getLogger("cx.order")

# semleges válasz — matched ÉS nem-matched esetben is (adat-szivárgás ellen)
ORDER_STATUS_REPLY = (
    "Ha a megadott rendelésszámhoz és e-mail-címhez tartozik rendelés, a "
    "részleteket elküldtük arra az e-mail-címre. Kérlek, nézd meg a postafiókod "
    "(a spam mappát is)."
)


async def _sellvio_token(
    client: httpx.AsyncClient, api_base: str, client_id: str, client_secret: str
) -> str:
    """OAuth client_credentials -> access_token (üres string, ha nincs)."""
    resp = await client.post(
        f"{api_base}/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    body = resp.json()
    return str((body or {}).get("access_token") or "")


async def _sellvio_get_order(
    client: httpx.AsyncClient, api_base: str, order_id: str, token: str
) -> dict:
    resp = await client.get(
        f"{api_base}/api/v2/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    body = resp.json()
    return body if isinstance(body, dict) else {}


def _verify_order(payload: dict, order_email: str) -> tuple[bool, str]:
    """Verify Order: status=="success" + data.id + data.email == megadott email -> matched.

    Visszaad: (matched, status_name). status_name = data.status.name, különben 'ismeretlen'.
    """
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return False, "ismeretlen"
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not data.get("id"):
        return False, "ismeretlen"

    status_obj = data.get("status") or {}
    status_name = status_obj.get("name") if isinstance(status_obj, dict) else None
    status = str(status_name or "ismeretlen")

    resp_email = str(data.get("email") or "").strip().lower()
    if not resp_email or resp_email != str(order_email or "").strip().lower():
        return False, status
    return True, status


async def handle_order_status(tenant: "Tenant", order: "OrderIntent") -> str:
    """Sellvio order-lekérés. MINDIG a semleges választ adja vissza; matched esetén
    háttérben e-mailt ütemez a vevőnek. Hiba/timeout -> semleges válasz, e-mail
    nélkül; logol, nem dob (a /chat mindig fusson tovább).
    """
    client_id = tenant.client_id
    api_base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    secret = str(tenant.api_client_secret or "").strip()
    order_id = order.order_id
    order_email = order.order_email

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token = await _sellvio_token(client, api_base, cid, secret)
            if not token:
                logger.warning("ORDER[%s] nincs Sellvio token — semleges válasz", client_id)
                return ORDER_STATUS_REPLY
            payload = await _sellvio_get_order(client, api_base, order_id, token)
    except Exception:  # noqa: BLE001 — Sellvio hiba SOHA ne törje meg a /chat-et
        logger.exception("ORDER[%s] Sellvio hívás hiba (id=%s)", client_id, order_id)
        return ORDER_STATUS_REPLY

    matched, status = _verify_order(payload, order_email)
    if matched:
        bot = str(tenant.bot_name or "").strip() or client_id
        subject = f"Rendelésed állapota – #{order_id}"
        text = (
            "Kedves Vásárlónk!\n\n"
            f"A(z) #{order_id} számú rendelésed állapota: {status}\n\n"
            f"Üdvözlettel,\n{bot}"
        )
        logger.info("ORDER[%s] matched id=%s -> e-mail to=%s", client_id, order_id, order_email)
        schedule_email(order_email, subject, text)
    else:
        logger.info(
            "ORDER[%s] nem matched id=%s — semleges válasz, nincs e-mail", client_id, order_id
        )

    return ORDER_STATUS_REPLY

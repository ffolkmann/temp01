"""Rendelés-státusz ág — platform szerinti order-lekérés + semleges válasz + e-mail.

A prod Chat workflow "platform order-lekérés -> Verify Order -> Send Status Email"
ágának portja. Platformok: Sellvio (eredeti), Shoprenter, Unas, WooCommerce.
A közös auth/XML primitívek a platform_api.py-ben (live_product.py is osztja).

Adatvédelem: a /chat VÁLASZ matched ÉS nem-matched esetben is UGYANAZ a semleges
szöveg, hogy ne szivárogjon rendelési adat. A státusz csak e-mailben megy a
rendeléskor használt címre, háttérben (schedule_email). Bármely hiba -> semleges
válasz + log, SOHA nem dob a widget felé.

API-kontraktusok (VPS-en igazolt / web):
 - Sellvio:     OAuth, GET /api/v2/orders/{id} (302->follow), data.* (élő).
 - WooCommerce: GET {base}/wp-json/wc/v3/orders/{id}, Basic (ck/cs), billing.email + status.
 - Shoprenter:  OAuth2, GET {api_base}/orders/{base64('order-order_id=<N>')}; az api2 csupasz
                top-level objektumot ad (email top-level); a status href-dict -> guard + generikus.
 - Unas:        login(ApiKey)->Token, POST /getOrder XML Bearer, Order <Status> + <Email>.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import httpx

from app.core.mailer import schedule_email
from app.services.platform_api import (
    UNAS_BASE,
    norm_email,
    sellvio_token,
    shoprenter_resource_id,
    shoprenter_shop,
    shoprenter_token,
    unas_login,
    xml_first_text,
    xml_root,
)

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


def _safe_status(*candidates) -> str:
    """Az első str (nem dict/href/None) jelölt; különben generikus 'ismeretlen'.

    Védi az e-mailt attól, hogy egy href-dict ({'href': ...}) string-elve menjen ki.
    """
    for v in candidates:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "ismeretlen"


# --------------------------------------------------------------------------- #
# Sellvio
# --------------------------------------------------------------------------- #
async def _sellvio_get_order(
    client: httpx.AsyncClient, api_base: str, order_id: str, token: str
) -> dict:
    resp = await client.get(
        f"{api_base}/api/v2/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    resp.raise_for_status()
    body = resp.json()
    return body if isinstance(body, dict) else {}


def _verify_order(payload: dict, order_email: str) -> tuple[bool, str]:
    """Verify Order: status=="success" + data.id + data.email == megadott email -> matched."""
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return False, "ismeretlen"
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not data.get("id"):
        return False, "ismeretlen"
    status_obj = data.get("status") or {}
    status_name = status_obj.get("name") if isinstance(status_obj, dict) else None
    status = str(status_name or "ismeretlen")
    if not norm_email(data.get("email")) or norm_email(data.get("email")) != norm_email(order_email):
        return False, status
    return True, status


async def _sellvio_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str]:
    api_base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    secret = str(tenant.api_client_secret or "").strip()
    # follow_redirects: a Sellvio /api/v2/orders/{id} 302-t ad (Accept: json + redirect -> 200).
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        token = await sellvio_token(client, api_base, cid, secret)
        if not token:
            logger.warning("ORDER[%s] nincs Sellvio token", tenant.client_id)
            return False, "ismeretlen"
        payload = await _sellvio_get_order(client, api_base, order.order_id, token)
    return _verify_order(payload, order.order_email)


# --------------------------------------------------------------------------- #
# WooCommerce — GET /wp-json/wc/v3/orders/{id}, Basic auth (consumer key/secret)
# --------------------------------------------------------------------------- #
async def _woo_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str]:
    base = str(tenant.api_base or "").strip().rstrip("/")
    ck = str(tenant.api_client_id or "").strip()        # ck_...
    cs = str(tenant.api_client_secret or "").strip()    # cs_...
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(
            f"{base}/wp-json/wc/v3/orders/{order.order_id}",
            auth=(ck, cs),
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, dict) or not data.get("id"):
        return False, "ismeretlen"
    status = str(data.get("status") or "ismeretlen")
    billing = data.get("billing") if isinstance(data.get("billing"), dict) else {}
    email = norm_email((billing or {}).get("email"))
    if not email or email != norm_email(order.order_email):
        return False, status
    return True, status


# --------------------------------------------------------------------------- #
# Shoprenter — OAuth2 (Basic deprecated->403); base64 order id
# --------------------------------------------------------------------------- #
async def _shoprenter_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str]:
    api_base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    secret = str(tenant.api_client_secret or "").strip()
    shop = shoprenter_shop(api_base)
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        token = await shoprenter_token(client, shop, cid, secret)
        if not token:
            logger.warning("ORDER[%s] nincs Shoprenter token", tenant.client_id)
            return False, "ismeretlen"
        resp = await client.get(
            f"{api_base}/orders/{shoprenter_resource_id('order', order.order_id)}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, dict):
        return False, "ismeretlen"
    # az api2 single GET csupasz top-level objektumot ad (nincs response/order burkoló),
    # az email top-level mező — a match-logika HELYES, ne nyúlj hozzá.
    o = data.get("order") if isinstance(data.get("order"), dict) else data
    if not o or not (o.get("id") or o.get("innerId") or o.get("orderNumber")):
        return False, "ismeretlen"
    # GUARD: a valós orderStatus egy href-dict ({'href': '.../orderStatuses/<b64>'}, full=1-gyel
    # is) -> NEM stringeljük; csak str státuszt fogadunk el, különben generikus.
    # (Opcionális, Fecó-visszaigazolásra váró ág a valódi HU névhez: orderStatus['href']
    #  host-rewrite *.api.myshoprenter.hu -> *.api2.myshoprenter.hu/api + Bearer ->
    #  GET /orderStatuses/{b64}?full=1 -> lokalizált név az orderStatusDescriptions-ön. Addig generikus.)
    status = _safe_status(o.get("statusName"), o.get("orderStatus"), o.get("status"))
    email = norm_email(o.get("email") or o.get("customerEmail"))
    if not email or email != norm_email(order.order_email):
        return False, status
    return True, status


# --------------------------------------------------------------------------- #
# Unas — login(ApiKey)->Token, POST /getOrder XML, Bearer
# --------------------------------------------------------------------------- #
async def _unas_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str]:
    api_key = str(tenant.api_client_secret or "").strip() or str(tenant.api_client_id or "").strip()
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        token = await unas_login(client, api_key)
        if not token:
            logger.warning("ORDER[%s] nincs Unas token", tenant.client_id)
            return False, "ismeretlen"
        # Contents nélkül is teljes a válasz (smartzillán élesben igazolva); a full param nem igazolt.
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<Params><Key>{escape(order.order_id)}</Key></Params>"
        )
        resp = await client.post(
            f"{UNAS_BASE}/getOrder",
            content=body.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
        )
        resp.raise_for_status()
        root = xml_root(resp.text)
    if root is None:
        return False, "ismeretlen"
    order_el = root.find(".//Order")
    if order_el is None:
        return False, "ismeretlen"
    status = xml_first_text(order_el, "Status", "StatusName") or "ismeretlen"
    email = norm_email(xml_first_text(order_el, "Email"))
    if not email or email != norm_email(order.order_email):
        return False, status
    return True, status


# --------------------------------------------------------------------------- #
# Dispatch + e-mail
# --------------------------------------------------------------------------- #
_LOOKUPS = {
    "sellvio": _sellvio_lookup,
    "woocommerce": _woo_lookup,
    "shoprenter": _shoprenter_lookup,
    "unas": _unas_lookup,
}


def _send_status_email(tenant: "Tenant", order: "OrderIntent", status: str) -> None:
    bot = str(tenant.bot_name or "").strip() or tenant.client_id
    subject = f"Rendelésed állapota – #{order.order_id}"
    text = (
        "Kedves Vásárlónk!\n\n"
        f"A(z) #{order.order_id} számú rendelésed állapota: {status}\n\n"
        f"Üdvözlettel,\n{bot}"
    )
    logger.info(
        "ORDER[%s] matched id=%s -> e-mail to=%s", tenant.client_id, order.order_id, order.order_email
    )
    schedule_email(order.order_email, subject, text)


async def handle_order_status(tenant: "Tenant", order: "OrderIntent") -> str:
    """Platform szerinti order-lekérés. MINDIG a semleges választ adja vissza; matched
    esetén háttérben e-mailt ütemez a vevőnek. Hiba/timeout/ismeretlen platform ->
    semleges válasz, e-mail nélkül; logol, nem dob.
    """
    platform = str(tenant.platform or "").strip().lower()
    lookup = _LOOKUPS.get(platform)
    if lookup is None:
        logger.info("ORDER[%s] platform=%s nincs portolva — semleges válasz", tenant.client_id, platform)
        return ORDER_STATUS_REPLY

    try:
        matched, status = await lookup(tenant, order)
    except Exception:  # noqa: BLE001 — platform-hiba SOHA ne törje meg a /chat-et
        logger.exception(
            "ORDER[%s] %s hívás hiba (id=%s)", tenant.client_id, platform, order.order_id
        )
        return ORDER_STATUS_REPLY

    if matched:
        _send_status_email(tenant, order, status)
    else:
        logger.info(
            "ORDER[%s] nem matched id=%s (%s) — semleges válasz, nincs e-mail",
            tenant.client_id, order.order_id, platform,
        )
    return ORDER_STATUS_REPLY

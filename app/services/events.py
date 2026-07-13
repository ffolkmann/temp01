"""Esemény-számlálók (events tábla) — m22.

Fajták: link_click (widgetből), product_rec (válaszban linkelt termékek),
order_lookup (rendelés-státusz ág), handoff (élő segítségkérés),
configurator (konfigurátor-indítás). A /stats kártyák és a top-lista forrása.

Fail-safe: hiba esetén logol, a /chat-et SOHA nem töri.
"""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Event, Tenant

logger = logging.getLogger("cx.events")

# a widgetből fogadható event-fajták (whitelist)
WIDGET_KINDS = {"link_click", "impression"}  # m30: impression = widget-boot munkamenetenkent egyszer (konverzios nevezo)

_MD_LINK = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")


async def log_event(
    session: AsyncSession, client_id: str, session_id: str | None,
    kind: str, meta: dict | None = None,
) -> None:
    try:
        session.add(Event(client_id=client_id, session_id=session_id, kind=kind, meta=meta))
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("events: log hiba (%s, %s)", client_id, kind)
        await session.rollback()


def _shop_hosts(tenant: Tenant) -> set[str]:
    hosts: set[str] = set()
    for raw in (tenant.domain, tenant.public_url):
        for d in str(raw or "").split(","):
            d = d.strip().lower()
            if not d:
                continue
            d = d.split("//")[-1].split("/")[0]
            if d.startswith("www."):
                d = d[4:]
            if d:
                hosts.add(d)
    return hosts


def count_product_links(reply: str, tenant: Tenant) -> int:
    """A válaszban linkelt webshop-termékek száma (markdown linkek, shop-domain szűréssel).

    Ha a tenantnak nincs ismert domainje, minden http(s) linket számol.
    """
    urls = _MD_LINK.findall(reply or "")
    if not urls:
        return 0
    hosts = _shop_hosts(tenant)
    n = 0
    for u in urls:
        h = u.split("//")[-1].split("/")[0].lower()
        if h.startswith("www."):
            h = h[4:]
        if not hosts or h in hosts:
            n += 1
    return n

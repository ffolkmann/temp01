"""Kupon-modul — aktív, nem lejárt kuponok a tenanthoz (CLAUDE.md 11.).

A bot AJÁNL; a működő kupont a webshop saját adminjában is létre kell hozni.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Coupon


async def active_coupons(session: AsyncSession, client_id: str) -> list[Coupon]:
    rows = (
        await session.execute(
            select(Coupon).where(Coupon.client_id == client_id, Coupon.active.is_(True))
        )
    ).scalars().all()

    today = date.today().isoformat()
    out: list[Coupon] = []
    for c in rows:
        vu = (c.valid_until or "").strip()
        if vu and vu < today:  # ISO dátum string-összehasonlítás
            continue
        out.append(c)
    return out

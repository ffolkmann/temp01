"""Per-tenant CORS allowlist — Starlette BaseHTTPMiddleware (CLAUDE.md B.6.2).

Az engedélyezett originek forrása a Postgres tenants.domain oszlopa (lazy, process-
szintű cache): minden doménre https://<domain> ÉS https://www.<domain>. Plusz a
platform-suffixek BÁRMELY aldoménje engedett (.mysellvio.com, .unas.hu,
.myshoprenter.hu, .shoprenter.hu).

Engedett Origin -> reflektáljuk: Access-Control-Allow-Origin: <origin> + Vary: Origin.
Nem engedett -> nincs ACAO. Credentials NINCS. A preflight (OPTIONS) mindig 200.

Megjegyzés: a cache process-szintű és lusta — új tenant-domén csak újraindítás után
látszik (a folyamat élettartamára cache-elünk, ahogy a spec kéri).
"""

import asyncio
import logging
from urllib.parse import urlsplit

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.db import SessionLocal
from app.models.db_models import Tenant

logger = logging.getLogger("cx.cors")

# platform-suffixek: BÁRMELY aldoménjük engedett (host endswith)
PLATFORM_SUFFIXES = (".mysellvio.com", ".unas.hu", ".myshoprenter.hu", ".shoprenter.hu")

# process-szintű lusta cache
_ALLOWSET: set[str] | None = None
_ALLOWSET_LOCK = asyncio.Lock()


def _build_allowset(domains) -> set[str]:
    """Domének -> engedett origin-stringek (apex + www, https)."""
    out: set[str] = set()
    for d in domains:
        d = (d or "").strip().lower()
        if not d:
            continue
        base = d[4:] if d.startswith("www.") else d
        out.add(f"https://{base}")
        out.add(f"https://www.{base}")
    return out


async def _load_allowset() -> set[str]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(Tenant.domain))).scalars().all()
    return _build_allowset(rows)


async def _get_allowset() -> set[str]:
    """Lusta, process-szintű cache. Hiba esetén átmeneti üres lista (nem cache-eljük)."""
    global _ALLOWSET
    if _ALLOWSET is not None:
        return _ALLOWSET
    async with _ALLOWSET_LOCK:
        if _ALLOWSET is not None:
            return _ALLOWSET
        try:
            built = await _load_allowset()
        except Exception:  # noqa: BLE001 — DB hiba ne 500-azzon minden kérést
            logger.exception("CORS allowlist betöltés hiba — átmeneti üres lista")
            return set()
        _ALLOWSET = built
        logger.info("CORS allowlist betöltve: %d origin", len(_ALLOWSET))
        return _ALLOWSET


def _is_allowed(origin: str, allowset: set[str]) -> bool:
    if not origin:
        return False
    if origin in allowset:
        return True
    parts = urlsplit(origin)
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    return any(host.endswith(suf) for suf in PLATFORM_SUFFIXES)


class TenantCORSMiddleware(BaseHTTPMiddleware):
    """Tenant-tudatos CORS: engedett originnél reflektál, egyébként semmit."""

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = bool(origin) and _is_allowed(origin, await _get_allowset())

        if request.method == "OPTIONS":
            # preflight — mindig 200; engedettnél CORS-fejlécek, egyébként ACAO nélkül
            headers: dict[str, str] = {}
            if allowed:
                req_headers = request.headers.get("access-control-request-headers") or "content-type"
                headers = {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": req_headers,
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                }
            return Response(status_code=200, headers=headers)

        response = await call_next(request)
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

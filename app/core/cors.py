"""Per-tenant CORS — a prod n8n / Google Ads minta portja (CLAUDE.md B.6.2).

A böngészőből hívott végpontoknál (POST /chat) a TÉNYLEGES kérésnél a body
client_id -> tenants.domain alapján döntünk: az Origint CSAK akkor reflektáljuk
vissza (Access-Control-Allow-Origin), ha az Origin host a tenant doménje — apex,
www vagy bármely aldomén, http/https. Credentials NINCS. Minden válaszon Vary: Origin.

Sorrend (B.6.2): (1) DB tenants.domain -> (2) beépített DOMAIN_MAP fallback ->
(3) egyik sincs: fail-open reflect (nehogy egy működő tenantot eltörjünk).

A preflight (OPTIONS) a main.py middleware-ében dől el (a body ott még nem
elérhető, ezért reflektál); az érdemi POST-on ez a dependency dönt. Így az ACAO-t
EGYETLEN logika (resolve_allowed_origin) állítja — nincs globális CORSMiddleware '*'.
"""

from urllib.parse import urlsplit

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.db_models import Tenant

# preflight konstansok (a main.py middleware is ezeket használja)
CORS_ALLOW_METHODS = "POST, OPTIONS"
CORS_ALLOW_HEADERS = "content-type"
CORS_MAX_AGE = "86400"

# fallback domén-térkép (CLAUDE.md 6.3) — a DB tenants.domain az ELSŐDLEGES forrás
DOMAIN_MAP = {
    "welltechnik": "welltechnik.hu",
    "teslashop": "teslashop.hu",
    "cegalkusz": "cegalkusz.hu",
    "ecowindoor": "ecowin.hu",
    "mastercool": "klimaszereles-budapest-karbantartas.hu",
    "plcomfort": "plcomfortwebshop.hu",
    "adlogic": "adlogic.unas.hu",
    "smartzilla": "smartzilla.hu",
    "4mfrigo": "webshop.4mfrigo.hu",
    "rmweb": "rmweb.hu",
    "kellegyszerszam": "kellegyszerszam.hu",
    "codexpress": "codexpress.hu",
    "nagyonallatshop": "nagyonallatshop.hu",
    "notebookstore": "notebookstore.hu",
}


def origin_host(origin: str) -> str | None:
    """Az Origin host-ja kisbetűsen, ha a séma http/https; különben None."""
    try:
        parts = urlsplit(origin or "")
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    return (parts.hostname or "").lower() or None


def origin_matches_domain(origin: str, domain: str) -> bool:
    """Igaz, ha az Origin a tenant doménje: apex, www vagy bármely aldomén."""
    host = origin_host(origin)
    domain = (domain or "").strip().lower().lstrip(".")
    if not host or not domain:
        return False
    return host == domain or host.endswith("." + domain)


async def _tenant_domain(session: AsyncSession, client_id: str | None) -> str | None:
    if not client_id:
        return None
    dom = (
        await session.execute(select(Tenant.domain).where(Tenant.client_id == client_id))
    ).scalar_one_or_none()
    return (dom or "").strip() or None


async def resolve_allowed_origin(
    session: AsyncSession, origin: str, client_id: str | None
) -> str | None:
    """Az ACAO értéke: az Origin (reflect) vagy None (blokk) — EGYETLEN döntési hely.

    (1) DB tenants.domain -> (2) DOMAIN_MAP -> (3) egyik sincs: fail-open reflect.
    """
    if not origin:
        return None
    domain = await _tenant_domain(session, client_id)
    if not domain:
        domain = DOMAIN_MAP.get((client_id or "").strip().lower())
    if not domain:
        return origin  # fail-open (B.6.2 3.)
    return origin if origin_matches_domain(origin, domain) else None


async def cors_headers(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Dependency a böngésző-POST végpontokra: tenant-tudatos ACAO + Vary: Origin.

    A body-t a cache-ből olvassa (FastAPI a body-t a dependency-k előtt beolvassa a
    ChatRequest-hez), ezért a request.json() itt nem ütközik a route paraméterrel.
    Hibás/üres body -> a fail-open ágra esünk (ismeretlen tenant).
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    response.headers["Vary"] = "Origin"
    client_id = None
    try:
        data = await request.json()
        if isinstance(data, dict):
            client_id = data.get("client_id")
    except Exception:  # noqa: BLE001 — rossz/üres body: ismeretlen tenant -> fail-open
        client_id = None
    allowed = await resolve_allowed_origin(session, origin, client_id)
    if allowed:
        response.headers["Access-Control-Allow-Origin"] = allowed

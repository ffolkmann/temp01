"""CX Konfigurator widget-vegpontok (K2).

- ``GET  /konf/settings?client_id=...`` — a tenant kerdes->szuro rulesetje a
  widgetnek (konfcfg.normalize_ruleset-tel tisztitva; kikapcsolt/ismeretlen
  tenantra {"enabled": false}).
- ``POST /konf/event`` — ``kf_start`` | ``kf_done`` | ``kf_lead`` az ``events``
  tablaba (funnel-statisztika; a widget sendBeacon-nel, text/plain-nel kuld,
  ezert a body-t nyersen parse-oljuk — az S2 search_event mintaja).

Igazsag-forras: ``tenants.konf_config`` jsonb; ures/hianyzo/hibas eseten a
mountolt ``data/konfigurator.json`` (KONF_CONFIG env) — az s3 search-feloldas.
Fail-safe: barmilyen hiba eseten kikapcsolt config ill. csendes 204.
CORS: TenantCORSMiddleware (a tenant domainje engedett).
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.services.events import log_event

logger = logging.getLogger("cx.konf")
router = APIRouter()

KONF_KINDS = {"kf_start", "kf_done", "kf_lead"}
CACHE_SECONDS = 300

_SQL_TENANT_CFG = text("SELECT konf_config FROM tenants WHERE client_id = :cid")


def _konfcfg():
    """Lazy import — a fajl-betoltos tesztkornyezetek fake app.services-e miatt."""
    try:
        from app.services import konfcfg
        return konfcfg
    except Exception:  # noqa: BLE001
        import importlib.util as _ilu
        import pathlib as _pl
        _pp = _pl.Path(__file__).resolve().parents[1] / "services" / "konfcfg.py"
        _sp = _ilu.spec_from_file_location("konfcfg_fb", _pp)
        _pm = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_pm)
        return _pm


async def db_config(session: Any, client_id: str) -> dict[str, Any]:
    """A tenant ``tenants.konf_config`` jsonb-je (hibara/hianyra ures dict)."""
    try:
        row = (await session.execute(_SQL_TENANT_CFG, {"cid": client_id})).scalar()
    except Exception:  # noqa: BLE001 — pl. az oszlop meg nem letezik -> fajl-fallback
        logger.warning("konf: konf_config olvasas sikertelen (%s)", client_id)
        return {}
    if isinstance(row, str):
        try:
            row = json.loads(row)
        except Exception:  # noqa: BLE001
            return {}
    return row if isinstance(row, dict) else {}


async def get_config(session: Any, client_id: str) -> dict[str, Any]:
    """DB -> ha ures/hibas -> data/konfigurator.json."""
    if not client_id:
        return {}
    cfg = await db_config(session, client_id)
    return cfg if cfg else _konfcfg().load_file_config(client_id)


@router.get("/konf/settings")
async def konf_settings(
    client_id: str = Query("", max_length=64),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """A widget rulesetje. Ismeretlen/kikapcsolt tenantnal enabled:false valasz."""
    cid = (client_id or "").strip().lower()
    body = _konfcfg().normalize_ruleset(await get_config(session, cid))
    body["tenant"] = cid
    return JSONResponse(body, headers={"Cache-Control": f"public, max-age={CACHE_SECONDS}"})


def _meta_int(v: Any, lo: int = 0, hi: int = 10**9) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return 0
    return max(lo, min(hi, n))


@router.post("/konf/event")
async def konf_event(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Konfigurator-esemeny naplozasa. Mindig 204 — a beacont sosem buntetjuk."""
    try:
        raw = await request.body()
        data = json.loads((raw or b"").decode("utf-8", "replace") or "{}")
    except Exception:  # noqa: BLE001
        return Response(status_code=204)
    if not isinstance(data, dict):
        return Response(status_code=204)

    kind = str(data.get("event") or "").strip().lower()
    cid = str(data.get("client_id") or "").strip()[:64]
    if kind not in KONF_KINDS or not cid:
        return Response(status_code=204)
    if not (await get_config(session, cid)).get("enabled"):
        return Response(status_code=204)

    raw_meta = data.get("meta")
    meta_in = raw_meta if isinstance(raw_meta, dict) else {}
    meta = {
        "n": _meta_int(meta_in.get("n")),
        "answers": str(meta_in.get("answers") or "")[:400],
        "top": str(meta_in.get("top") or "")[:200],
    }
    sid = str(data.get("session_id") or "")[:64] or None
    await log_event(session, cid, sid, kind, meta)
    return Response(status_code=204)

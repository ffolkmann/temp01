"""CX Konfigurator widget-vegpontok (K2).

- ``GET  /konf/settings?client_id=...`` — a tenant kerdes->szuro rulesetje a
  widgetnek (konfcfg.normalize_ruleset-tel tisztitva; kikapcsolt/ismeretlen
  tenantra {"enabled": false}).
- ``POST /konf/event`` — ``kf_start`` | ``kf_step`` | ``kf_done`` | ``kf_lead`` az ``events``
  tablaba (funnel-statisztika; a widget sendBeacon-nel, text/plain-nel kuld,
  ezert a body-t nyersen parse-oljuk — az S2 search_event mintaja).

- ``POST /konf/lead`` -- KOZOS lead-vegpont (kf/9): a leadet a ``leads``
  tablaba irja, es ertesito e-mailt kuld a tenant cimzettjere (a ruleset
  ``lead`` blokkjabol). A tenantonkent klonozott n8n-webhook
  (``lead.post_url``) ezzel OPCIONALISSA valik: ha be van allitva, a widget
  tovabbra is azt hasznalja (visszafele kompatibilitas).

Igazsag-forras: ``tenants.konf_config`` jsonb; ures/hianyzo/hibas eseten a
mountolt ``data/konfigurator.json`` (KONF_CONFIG env) — az s3 search-feloldas.
Fail-safe: barmilyen hiba eseten kikapcsolt config ill. csendes 204.
CORS: TenantCORSMiddleware (a tenant domainje engedett).
"""

import asyncio
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

KONF_KINDS = {"kf_start", "kf_step", "kf_done", "kf_lead", "kf_click"}
POPULAR_DAYS = 30
POPULAR_LIMIT = 60
CACHE_SECONDS = 300

_SQL_TENANT_CFG = text("SELECT konf_config FROM tenants WHERE client_id = :cid")
_SQL_TENANT_LEAD = text("SELECT lead_email FROM tenants WHERE client_id = :cid")

# kf/9: a lead ugyanabba a ``leads`` tablaba megy, mint a chatbot-lead
# (source=konflead.SOURCE), igy az admin megevo lead-listaja valtozatlanul mutatja
_SQL_INSERT_LEAD = text(
    "INSERT INTO leads (client_id, session_id, name, email, phone, message, "
    "source, history) VALUES (:cid, :sid, :name, :email, :phone, :msg, :src, "
    "CAST(:hist AS jsonb)) RETURNING id"
)

# nepszeruseg = a widgetbol jott termek-kattintasok (kf_click) az utolso
# POPULAR_DAYS napban; a widget ez alapjan kinal "Nepszeruseg" rendezest
_SQL_POPULAR = text(
    "SELECT meta->>'sku' AS sku, count(*) AS c FROM events "
    "WHERE client_id = :cid AND kind = 'kf_click' "
    "AND created_at > now() - make_interval(days => :days) "
    "AND coalesce(meta->>'sku', '') <> '' "
    "GROUP BY 1 ORDER BY c DESC, 1 LIMIT :lim"
)


async def popular_skus(session: Any, client_id: str) -> list[str]:
    """Legtobbet kattintott cikkszamok (hibara ures lista)."""
    if not client_id:
        return []
    try:
        rows = (await session.execute(
            _SQL_POPULAR,
            {"cid": client_id, "days": POPULAR_DAYS, "lim": POPULAR_LIMIT},
        )).all()
    except Exception:  # noqa: BLE001 - a nepszeruseg sosem torheti a widgetet
        logger.warning("konf: popular lekerdezes sikertelen (%s)", client_id)
        return []
    return [str(r[0])[:64] for r in rows if r and r[0]]


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


def _konflead():
    """Lazy import — lasd _konfcfg (stdlib-only modul, fajlbol is betoltheto)."""
    try:
        from app.services import konflead
        return konflead
    except Exception:  # noqa: BLE001
        import importlib.util as _ilu
        import pathlib as _pl
        _pp = _pl.Path(__file__).resolve().parents[1] / "services" / "konflead.py"
        _sp = _ilu.spec_from_file_location("konflead_fb", _pp)
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
    body["popular"] = await popular_skus(session, cid) if body.get("enabled") else []
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
        "sku": str(meta_in.get("sku") or "")[:64],
        "pos": _meta_int(meta_in.get("pos"), 0, 999),
        # kf/11: melyik kerdesnel tart (kf_step) - ebbol lesz a tolcser kieses-sora
        "q": str(meta_in.get("q") or "")[:40],
    }
    sid = str(data.get("session_id") or "")[:64] or None
    await log_event(session, cid, sid, kind, meta)
    return Response(status_code=204)



async def _tenant_lead_email(session: Any, client_id: str) -> str:
    """A tenant chatbot-lead cimzettje (hibara ures -> a ruleset donti el)."""
    try:
        row = (await session.execute(_SQL_TENANT_LEAD, {"cid": client_id})).scalar()
    except Exception:  # noqa: BLE001
        logger.warning("konf-lead: lead_email olvasas sikertelen (%s)", client_id)
        return ""
    return str(row or "")


async def _rl_blocked(key: str, limit: int) -> bool:
    """Fail-open: Redis-hiba eseten atengedjuk (inkabb jojjon be a lead)."""
    try:
        from app.services.rate_limit import is_blocked
        return await is_blocked(key, limit)
    except Exception:  # noqa: BLE001
        return False


async def _rl_hit(key: str, window: int) -> None:
    """Egy elfogadott lead konyvelese (az ablak az elsonel indul)."""
    try:
        from app.services.rate_limit import register_failure
        await register_failure(key, window)
    except Exception:  # noqa: BLE001
        logger.warning("konf-lead: rate-limit szamlalo sikertelen")


_FWD_TASKS: set = set()


def _forward(url: str, payload: dict) -> None:
    """Opcionalis tovabbitas a tenant sajat folyamataba (fire-and-forget)."""

    async def _run() -> None:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                await client.post(url, json=payload)
        except Exception:  # noqa: BLE001 - a tovabbitas sosem buktathatja a leadet
            logger.warning("konf-lead: forward sikertelen (%s)", url)

    try:
        task = asyncio.create_task(_run())
        _FWD_TASKS.add(task)
        task.add_done_callback(_FWD_TASKS.discard)
    except Exception:  # noqa: BLE001
        logger.warning("konf-lead: forward task inditas sikertelen")


@router.post("/konf/lead")
async def konf_lead(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Kozos lead-vegpont: tarolas + ertesito e-mail, tenantonkenti n8n-klon nelkul.

    A body lehet urlencoded (a widget igy kuld, hogy ne legyen CORS-preflight)
    vagy JSON. A tarolas a lenyeg: az e-mail es a tovabbitas hattertask, egyik
    hibaja sem valtoztat a valaszon.
    """
    kl = _konflead()
    try:
        raw = await request.body()
    except Exception:  # noqa: BLE001
        raw = b""
    p = kl.normalize(kl.parse_body(raw, request.headers.get("content-type", "")))
    cid = p["client_id"]
    if not cid:
        return JSONResponse({"ok": False, "error": "client_id"}, status_code=400)

    cfg = await get_config(session, cid)
    lead_cfg = cfg.get("lead") if isinstance(cfg.get("lead"), dict) else {}
    if not (cfg.get("enabled") and lead_cfg.get("enabled")):
        return JSONResponse({"ok": False, "error": "disabled"}, status_code=404)

    # honeypot: a botnak sikeres valasz, de nem tarolunk es nem kuldunk
    if p["hp"]:
        logger.info("konf-lead[%s]: honeypot", cid)
        return JSONResponse({"ok": True})

    if not kl.has_contact(p):
        return JSONResponse({"ok": False, "error": "contact"}, status_code=400)

    ip = kl.client_ip(dict(request.headers), getattr(request.client, "host", ""))
    key = kl.rl_key(cid, ip)
    if await _rl_blocked(key, kl.RATE_LIMIT):
        logger.warning("konf-lead[%s]: rate limit (%s)", cid, ip)
        return JSONResponse({"ok": False, "error": "rate_limit"}, status_code=429)

    try:
        lead_id = (await session.execute(_SQL_INSERT_LEAD, {
            "cid": cid,
            "sid": p["session_id"] or None,
            "name": p["name"] or None,
            "email": p["email"] or None,
            "phone": p["phone"] or None,
            "msg": kl.stored_message(p) or None,
            "src": kl.SOURCE,
            "hist": json.dumps(kl.history_blob(p), ensure_ascii=False),
        })).scalar()
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("konf-lead[%s]: tarolas sikertelen", cid)
        return JSONResponse({"ok": False, "error": "store"}, status_code=500)
    await _rl_hit(key, kl.RATE_WINDOW)

    to = kl.recipient(lead_cfg, await _tenant_lead_email(session, cid))
    if to:
        subject, body = kl.compose(cid, p, lead_cfg)
        try:
            from app.core.mailer import schedule_email
            schedule_email(to, subject, body)
        except Exception:  # noqa: BLE001 - a lead mar el van mentve
            logger.exception("konf-lead[%s]: e-mail utemezes sikertelen", cid)
    else:
        logger.warning("konf-lead[%s]: NINCS cimzett - a lead tarolva, e-mail nem ment", cid)

    fwd = kl.forward_url(lead_cfg)
    if fwd:
        _forward(fwd, kl.forward_payload(cid, p))

    logger.info("konf-lead[%s]: id=%s to=%s fwd=%s", cid, lead_id, to or "-", bool(fwd))
    return JSONResponse({"ok": True, "id": lead_id})

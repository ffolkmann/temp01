"""FastAPI config / popup / admin — az n8n chat-config, chat-popup, chat-admin webhookok kiváltása.

- GET  /chat-config?client_id=...                 -> widget branding JSON (Postgres `tenants`)
- GET  /chat-popup?client_id&trigger&page_url      -> teaser (popup_config + Qdrant v2 + coupon)
- POST /admin                                       -> admin-panel API (token-auth: config/plans/leads/coupons/docs)

CORS: a /chat-config és /chat-popup egyszerű GET (a TenantCORSMiddleware reflektál engedett
originnél); a /admin reflect-any (a token az auth) — lásd app/core/cors.py.

Parity forrás: az n8n 'Chatbot – Config' (gwGmkSVpSmI5i90Q), 'Chatbot – Popup' (ACVMhs9NUIIWFMPj),
'Chatbot – Admin' (zyCefQXtQ0c9ZsLt) Code-node logikája. A régi n8n a cx_chatbot (v1) kollekciót
olvassa; itt a beállított qdrant_collection (v2) megy — a chat-tel konzisztensen.
"""

import json
import logging
import random
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.settings import get_settings
from app.models.db_models import Coupon, Lead, Plan, Tenant
from app.services.current_product import get_current_product, normalize_url
from app.services.operator_notify import notify_operators_ex

logger = logging.getLogger("cx.config")
router = APIRouter()
_settings = get_settings()

# a FastAPI chat-szolgáltatás publikus alap-URL-je (a widget innen veszi az EP.chat-et)
CHAT_API_BASE = "https://chatapi.codexpress.cloud"


# --------------------------------------------------------------------------- #
# segédek
# --------------------------------------------------------------------------- #
def _num(v: Any, default: float) -> float | int:
    """n8n `Number(v) || default`: 0/NaN/üres -> default; egész -> int."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    if not n:
        return default
    return int(n) if n == int(n) else n


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in ("true", "1", "yes", "on")


def _gen_stat_key() -> str:
    c = "0123456789abcdef"
    return "".join(random.choice(c) for _ in range(32))


def _first_rel(s: Any) -> dict[str, str] | None:
    """'Név — url; Név2 — url2' -> {name,url} az első elemből (n8n firstRel)."""
    txt = str(s or "").strip()
    if not txt:
        return None
    piece = txt.split(";", 1)[0].strip()
    sep = " \u2014 "  # ' — ' (szóköz, em-dash, szóköz)
    idx = piece.rfind(sep)
    if idx >= 0:
        nm = piece[:idx].strip()
        url = piece[idx + len(sep):].strip()
    else:
        nm = piece
        url = ""
    if not nm:
        return None
    return {"name": nm, "url": url}


async def _get_tenant(session: AsyncSession, client_id: str) -> Tenant | None:
    return (
        await session.execute(select(Tenant).where(Tenant.client_id == client_id))
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# GET /chat-config  — widget branding (n8n Build Response parity)
# --------------------------------------------------------------------------- #
def _config_body(t: Tenant | None) -> dict[str, Any]:
    plan = t.plan if t else None
    pc = t.popup_config if (t and isinstance(t.popup_config, dict)) else {}
    pc = pc or {}
    return {
        "chat_api_base": CHAT_API_BASE if (t and bool(t.use_fastapi)) else "",
        "search_fallback": bool(t.search_fallback) if t else False,
        "launcher": (t.launcher_config or {}) if t else {},
        "bot_name": t.bot_name if t else None,
        "header_color": t.header_color if t else None,
        "bubble_color": t.bubble_color if t else None,
        "welcome_message": t.welcome_message if t else None,
        "launcher_position": t.launcher_position if t else None,
        "launcher_anim": (t.launcher_anim if t and t.launcher_anim else "none"),
        "powered_by": plan != "white_label",
        "auto_open": bool(t.auto_open) if t else False,
        "auto_open_delay": _num(t.auto_open_delay if t else None, 25),
        "proactive_message": (t.proactive_message or "") if t else "",
        "proactive_product_message": (t.proactive_product_message or "") if t else "",
        "popup": {
            "enabled": pc.get("enabled") is True,
            "trigger_product": pc.get("trigger_product") is True,
            "product_delay": _num(pc.get("product_delay"), 15),
            "trigger_exit": pc.get("trigger_exit") is True,
        },
    }


@router.get("/chat-config")
async def chat_config(
    client_id: str = Query(""),
    session: AsyncSession = Depends(get_session),
) -> dict:
    cid = (client_id or "").strip().lower()
    t = await _get_tenant(session, cid) if cid else None
    return _config_body(t)


# --------------------------------------------------------------------------- #
# GET /chat-popup  — teaser (n8n Popup Build Payload parity)
# --------------------------------------------------------------------------- #
@router.get("/chat-popup")
async def chat_popup(
    client_id: str = Query(""),
    trigger: str = Query("product"),
    page_url: str = Query(""),
    session: AsyncSession = Depends(get_session),
) -> dict:
    cid = (client_id or "").strip().lower()
    trig = (trigger or "product").strip().lower()
    norm = normalize_url(page_url)

    t = await _get_tenant(session, cid) if cid else None
    pc = (t.popup_config if (t and isinstance(t.popup_config, dict)) else {}) or {}

    enabled = pc.get("enabled") is True
    trigger_on = (
        (pc.get("trigger_exit") is True) if trig == "exit" else (pc.get("trigger_product") is True)
    )
    if not (enabled and trigger_on):
        return {"show": False}

    text_product = str(pc.get("text_product") or "")
    text_exit = str(pc.get("text_exit") or "")
    exit_coupon = str(pc.get("exit_coupon") or "").strip()
    exit_cta_label = str(pc.get("exit_cta_label") or "")
    exit_cta_url = str(pc.get("exit_cta_url") or "")

    # termék-találat a page_url alapján (Qdrant v2, url-horgony) — a chat current_product újrahasznosítva
    prod = None
    if norm:
        prod = await get_current_product(cid, norm)
        if prod is None:
            # nehany platform (pl. WooCommerce) trailing slash-sel tarolja az url-t -> retry
            prod = await get_current_product(cid, norm + "/")
    if prod is not None:
        rec = _first_rel(prod.related_additional) or _first_rel(prod.related_similar)
        if rec:
            return {"show": True, "kind": "product", "text": text_product, "product": rec}
        if trig != "exit":
            return {"show": False}

    if trig == "exit":
        out: dict[str, Any] = {"show": True, "kind": "general", "text": text_exit}
        if exit_coupon:
            coup = (
                await session.execute(
                    select(Coupon).where(Coupon.client_id == cid, Coupon.code == exit_coupon)
                )
            ).scalars().first()
            if coup and coup.code:
                out["coupon"] = {
                    "code": str(coup.code or ""),
                    "discount": str(coup.discount or ""),
                    "conditions": str(coup.conditions or ""),
                }
        if exit_cta_url:
            out["cta"] = {"label": (exit_cta_label or "Megnézem"), "url": exit_cta_url}
        return out

    return {"show": False}


# --------------------------------------------------------------------------- #
# POST /admin  — admin-panel API (n8n chat-admin parity)
# --------------------------------------------------------------------------- #
_TENANT_COLS = tuple(Tenant.__table__.columns.keys())


def _tenant_to_dict(t: Tenant) -> dict[str, Any]:
    d: dict[str, Any] = {c: getattr(t, c) for c in _TENANT_COLS}
    pcv = d.get("popup_config")
    # admin JS `JSON.parse(p.popup_config||"{}")`-ot vár -> stringként adjuk vissza
    d["popup_config"] = (
        json.dumps(pcv, ensure_ascii=False) if isinstance(pcv, (dict, list)) else (pcv or "")
    )
    wcv = d.get("warehouse_config")
    d["warehouse_config"] = (
        json.dumps(wcv, ensure_ascii=False) if isinstance(wcv, (dict, list)) else (wcv or "")
    )
    osm = d.get("order_status_map")  # m29: Webdoc kod -> megnevezes
    d["order_status_map"] = (
        json.dumps(osm, ensure_ascii=False) if isinstance(osm, (dict, list)) else (osm or "")
    )
    ohv = d.get("operator_hours")  # m28: admin JS JSON.parse-t vár -> stringként
    d["operator_hours"] = (
        json.dumps(ohv, ensure_ascii=False) if isinstance(ohv, (dict, list)) else (ohv or "")
    )
    return d


def _coupon_to_dict(c: Coupon) -> dict[str, Any]:
    return {
        "id": c.id, "client_id": c.client_id, "code": c.code, "discount": c.discount,
        "kind": c.kind, "conditions": c.conditions, "valid_until": c.valid_until, "active": c.active,
    }


def _iso(dt: Any) -> str:
    if dt is None:
        return ""
    try:
        return dt.isoformat()
    except Exception:  # noqa: BLE001
        return str(dt)


async def _save_config(session: AsyncSession, row_in: dict[str, Any]) -> dict[str, Any]:
    row = dict(row_in or {})
    cid = str(row.get("client_id") or "").strip().lower()
    if not cid:
        return {"error": "client_id required"}
    row["client_id"] = cid
    existing = await _get_tenant(session, cid)

    # popup_config: string-JSON -> dict (JSONB)
    if "popup_config" in row:
        pcv = row["popup_config"]
        if isinstance(pcv, str):
            try:
                row["popup_config"] = json.loads(pcv) if pcv.strip() else {}
            except Exception:  # noqa: BLE001
                row["popup_config"] = {}

    # warehouse_config: string-JSON -> dict (JSONB) — popup_config mintájára (m24)
    if "launcher_config" in row and isinstance(row["launcher_config"], str):
        try:
            row["launcher_config"] = json.loads(row["launcher_config"]) if row["launcher_config"].strip() else None
        except Exception:  # noqa: BLE001
            row.pop("launcher_config", None)
    if "search_fallback" in row:
        row["search_fallback"] = _as_bool(row["search_fallback"])
    # m28 élő operátor: bool-kapcsolók + operator_hours JSONB (launcher_config mintájára)
    for _laf in ("live_agent_enabled", "handoff_bot_silent"):
        if _laf in row:
            row[_laf] = _as_bool(row[_laf])
    if "operator_hours" in row and isinstance(row["operator_hours"], str):
        try:
            row["operator_hours"] = json.loads(row["operator_hours"]) if row["operator_hours"].strip() else None
        except Exception:  # noqa: BLE001
            row.pop("operator_hours", None)
    if "warehouse_config" in row:
        wcv = row["warehouse_config"]
        if isinstance(wcv, str):
            try:
                row["warehouse_config"] = json.loads(wcv) if wcv.strip() else {}
            except Exception:  # noqa: BLE001
                row["warehouse_config"] = {}

    # order_status_map: string-JSON -> dict (JSONB) — warehouse_config mintajara (m29)
    if "order_status_map" in row:
        osv = row["order_status_map"]
        if isinstance(osv, str):
            try:
                row["order_status_map"] = json.loads(osv) if osv.strip() else {}
            except Exception:  # noqa: BLE001
                row["order_status_map"] = {}

    # stat_key: megőriz vagy generál (a gatherForm NEM küldi)
    sk = str(row.get("stat_key") or "")
    if not sk:
        sk = existing.stat_key if (existing and existing.stat_key) else _gen_stat_key()
    row["stat_key"] = sk

    # m31: üres bot token -> NULL (a küldés a központi botra esik vissza)
    if "operator_bot_token" in row:
        _bt = str(row["operator_bot_token"] or "").strip()
        row["operator_bot_token"] = _bt or None

    # m30: operator_token — per-tenant operátor-konzol token (a gatherForm NEM küldi).
    # Megőrizzük; ha az élő átvétel be van kapcsolva és még nincs token, generálunk.
    ot = str(row.get("operator_token") or "") or (
        existing.operator_token if (existing and existing.operator_token) else ""
    )
    lae = row.get("live_agent_enabled")
    if lae is None:
        lae = bool(existing.live_agent_enabled) if existing else False
    if not ot and bool(lae):
        ot = _gen_stat_key()
    if ot:
        row["operator_token"] = ot
    else:
        row.pop("operator_token", None)

    # típus-koerció
    if "active" in row:
        row["active"] = _as_bool(row["active"])
    if "auto_open" in row:
        row["auto_open"] = _as_bool(row["auto_open"])
    for fld in ("auto_open_delay", "fast_sync_minutes"):
        if fld in row and row[fld] not in (None, ""):
            try:
                row[fld] = float(row[fld])
            except (TypeError, ValueError):
                row.pop(fld, None)

    # csak ismert oszlopok (drift-védelem: új admin-mező ne dobja el a mentést); use_fastapi-t
    # az admin sosem küld -> meglévőnél megőrződik, újnál a DB default (true).
    row = {k: v for k, v in row.items() if k in _TENANT_COLS}

    if existing is not None:
        for k, v in row.items():
            setattr(existing, k, v)
    else:
        session.add(Tenant(**row))
    await session.commit()
    return {"ok": True, "client_id": cid}


async def _qdrant_list_docs(client_id: str) -> dict[str, Any]:
    coll = _settings.qdrant_collection
    counts: dict[str, int] = {}
    offset: Any = None
    async with httpx.AsyncClient(base_url=_settings.qdrant_url.rstrip("/"), timeout=30) as cl:
        while True:
            body: dict[str, Any] = {
                "filter": {"must": [{"key": "client_id", "match": {"value": client_id}}]},
                "limit": 1000,
                "with_payload": ["filename"],
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            r = await cl.post(f"/collections/{coll}/points/scroll", json=body)
            r.raise_for_status()
            res = r.json().get("result", {})
            for p in res.get("points", []):
                fn = ((p.get("payload") or {}).get("filename")) or "?"
                counts[fn] = counts.get(fn, 0) + 1
            offset = res.get("next_page_offset")
            if not offset:
                break
    docs = [
        {"filename": fn, "chunks": counts[fn]}
        for fn in sorted(counts)
        if not (fn.startswith("__") and fn.endswith("__"))
    ]
    return {"docs": docs}


async def _qdrant_delete_doc(client_id: str, filename: str) -> dict[str, Any]:
    coll = _settings.qdrant_collection
    async with httpx.AsyncClient(base_url=_settings.qdrant_url.rstrip("/"), timeout=30) as cl:
        r = await cl.post(
            f"/collections/{coll}/points/delete?wait=true",
            json={"filter": {"must": [
                {"key": "client_id", "match": {"value": client_id}},
                {"key": "filename", "match": {"value": filename}},
            ]}},
        )
        r.raise_for_status()
    return {"ok": True}


@router.get("/admin/warehouses")
async def admin_warehouses(
    client_id: str = Query(...),
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Unas raktar-lista az admin panel raktar-felulirojahoz.

    Vissza: {platform, warehouses:[{id,name,info,active}]}. Csak Unasnal ad listat;
    mas platformnal ures (a Shoprenter admin-blokk fix 1-4 slotos, nem ide tartozik).
    """
    import os
    import re as _re

    import httpx

    if not token or token != os.environ.get("ADMIN_PANEL_TOKEN", ""):
        raise HTTPException(status_code=403, detail="forbidden")
    cid = str(client_id or "").strip().lower()
    t = await _get_tenant(session, cid)
    if t is None:
        return {"error": "not_found", "warehouses": []}
    plat = str(getattr(t, "platform", "") or "")
    if plat != "unas":
        return {"platform": plat, "warehouses": []}

    from app.services.platform_api import UNAS_BASE, unas_login

    api_key = str(getattr(t, "api_client_secret", "") or "").strip()
    if not api_key:
        return {"platform": plat, "warehouses": [], "error": "no_api_key"}
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
            tok = await unas_login(c, api_key)
            if not tok:
                return {"platform": plat, "warehouses": [], "error": "login_failed"}
            r = await c.post(
                f"{UNAS_BASE}/getWarehouse",
                content=b'<?xml version="1.0" encoding="UTF-8"?><Params></Params>',
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/xml"},
            )
            r.raise_for_status()
            xml = r.text
        for blk in _re.findall(r"<Warehouse>.*?</Warehouse>", xml, _re.S):
            def _g(tag: str, _b: str = blk) -> str:
                m = _re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", _b, _re.S)
                return (m.group(1).strip() if m else "")
            wid = _g("Id")
            if not wid:
                continue
            out.append({
                "id": wid,
                "name": _g("PublicName") or _g("Name"),
                "info": _g("Info"),
                "active": (_g("Active").lower() == "yes"),
            })
    except Exception as e:  # noqa: BLE001 — a raktar-lekeres hibaja ne dobjon 500-at
        return {"platform": plat, "warehouses": [], "error": str(e)[:140]}
    return {"platform": plat, "warehouses": out}


@router.post("/admin")
async def admin(request: Request, session: AsyncSession = Depends(get_session)) -> Any:
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    b = raw.get("body") if isinstance(raw.get("body"), dict) else raw

    token = str(b.get("admin_token") or "")
    if token != _settings.admin_panel_token:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    action = str(b.get("action") or "")
    cid = str(b.get("client_id") or "").strip().lower()
    row = b.get("row") if isinstance(b.get("row"), dict) else {}
    coupon = b.get("coupon") if isinstance(b.get("coupon"), dict) else {}
    cid_id = b.get("id")
    filename = str(b.get("filename") or "")

    if action == "list_config":
        rows = (await session.execute(select(Tenant).order_by(Tenant.client_id))).scalars().all()
        return [_tenant_to_dict(t) for t in rows]

    if action == "list_plans":
        rows = (await session.execute(select(Plan))).scalars().all()
        return [
            {"plan": p.plan, "live_api": p.live_api, "white_label": p.white_label,
             "monthly_limit": p.monthly_limit}
            for p in rows
        ]

    if action == "save_config":
        return await _save_config(session, row)

    if action == "delete_config":
        if not cid:
            return {"error": "client_id required"}
        await session.execute(sa_delete(Tenant).where(Tenant.client_id == cid))
        await session.commit()
        return {"ok": True, "deleted": cid}

    if action == "list_leads":
        rows = (
            await session.execute(
                select(Lead).where(Lead.client_id == cid).order_by(Lead.created_at.desc())
            )
        ).scalars().all()
        return [
            {"name": ld.name or "", "email": ld.email or "", "phone": ld.phone or "",
             "message": ld.message or "", "source": ld.source or "",
             "created": _iso(ld.created_at), "session_id": ld.session_id or ""}
            for ld in rows
        ]

    if action == "list_coupons":
        rows = (
            await session.execute(select(Coupon).where(Coupon.client_id == cid).order_by(Coupon.id))
        ).scalars().all()
        return [_coupon_to_dict(c) for c in rows]

    if action == "add_coupon":
        cc = coupon or {}
        c = Coupon(
            client_id=str(cc.get("client_id") or cid).strip().lower(),
            code=cc.get("code"), discount=cc.get("discount"), kind=cc.get("kind"),
            conditions=cc.get("conditions"), valid_until=cc.get("valid_until"),
            active=_as_bool(cc.get("active", True)),
        )
        session.add(c)
        await session.commit()
        return {"ok": True}

    if action == "update_coupon":
        cc = coupon or {}
        try:
            rid = int(cid_id)
        except (TypeError, ValueError):
            return {"error": "id required"}
        c = (await session.execute(select(Coupon).where(Coupon.id == rid))).scalar_one_or_none()
        if c is None:
            return {"error": "not found"}
        for fld in ("code", "discount", "kind", "conditions", "valid_until"):
            if fld in cc:
                setattr(c, fld, cc[fld])
        if "active" in cc:
            c.active = _as_bool(cc["active"])
        await session.commit()
        return {"ok": True}

    if action == "delete_coupon":
        try:
            rid = int(cid_id)
        except (TypeError, ValueError):
            return {"error": "id required"}
        await session.execute(sa_delete(Coupon).where(Coupon.id == rid))
        await session.commit()
        return {"ok": True}

    if action == "list_docs":
        return await _qdrant_list_docs(cid)

    if action == "delete_doc":
        return await _qdrant_delete_doc(cid, filename)

    if action == "test_telegram":
        # m31: próbaüzenet a tenant chatId-jeire (saját bot, vagy a központi)
        cid = str(b.get("client_id") or "").strip().lower()
        t = await _get_tenant(session, cid)
        if not t:
            return JSONResponse({"error": "unknown_client"}, status_code=404)
        return await notify_operators_ex(
            t, "Ha ezt látod, az operátor-értesítés működik.", test=True
        )

    return JSONResponse({"error": "unknown_action", "action": action}, status_code=400)


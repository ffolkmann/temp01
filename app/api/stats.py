"""GET /stats?k=<stat_key> — a stat.html adatforrása (az n8n stat-webhook kiváltása).

A `k` a titok (stat_key), nincs egyéb auth. Böngészőből hívódik (nyitott GET, CORS public).
A válasz JSON KULCSRA PONTOS a régi n8n shape-pel — a stat.html render erre épül.

Period kulcs: aktuális hónap Europe/Budapest 'YYYY-MM'. order_lookups/product_recs: 0 (fázis-1).
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session

logger = logging.getLogger("cx.stats")
router = APIRouter()

BUDAPEST = ZoneInfo("Europe/Budapest")


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_week(dt: datetime) -> str:
    y, w, _ = dt.astimezone(BUDAPEST).isocalendar()
    return f"{y}-W{w:02d}"


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


@router.get("/stats")
async def stats(k: str = Query(...), session: AsyncSession = Depends(get_session)) -> dict:
    tenant = (await session.execute(text(
        "SELECT t.client_id, t.plan, t.platform, t.bot_name, t.header_color, "
        "p.white_label, p.live_api, p.monthly_limit "
        "FROM tenants t LEFT JOIN plans p ON p.plan = t.plan WHERE t.stat_key = :k"
    ), {"k": k})).mappings().first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="ismeretlen stat_key")

    cid = tenant["client_id"]
    now = datetime.now(timezone.utc)
    cp = now.astimezone(BUDAPEST).strftime("%Y-%m")
    cw = _iso_week(now)
    monthly_limit = _int(tenant["monthly_limit"])
    P = {"c": cid}

    # --- usage (conversations/messages) ---
    cur_u = (await session.execute(text(
        "SELECT conversations, messages FROM usage WHERE client_id=:c AND period=:p"
    ), {"c": cid, "p": cp})).mappings().first()
    tot_u = (await session.execute(text(
        "SELECT COALESCE(SUM(conversations),0) c, COALESCE(SUM(messages),0) m FROM usage WHERE client_id=:c"
    ), P)).mappings().first()
    usage_monthly = {r["period"]: r for r in (await session.execute(text(
        "SELECT period, conversations, messages FROM usage WHERE client_id=:c"
    ), P)).mappings().all()}

    # --- leads ---
    leads_total = (await session.execute(text(
        "SELECT COUNT(*) n FROM leads WHERE client_id=:c"
    ), P)).scalar() or 0
    leads_by_period = {r["period"]: _int(r["n"]) for r in (await session.execute(text(
        "SELECT to_char(created_at AT TIME ZONE 'Europe/Budapest','YYYY-MM') period, COUNT(*) n "
        "FROM leads WHERE client_id=:c GROUP BY 1"
    ), P)).mappings().all()}
    leads_rows = (await session.execute(text(
        "SELECT name,email,phone,message,created_at FROM leads WHERE client_id=:c "
        "ORDER BY created_at DESC LIMIT 60"
    ), P)).mappings().all()
    leads = [{"name": r["name"] or "", "email": r["email"] or "", "phone": r["phone"] or "",
              "message": r["message"] or "", "created": _iso(r["created_at"])} for r in leads_rows]

    # --- feedback ---
    fb_counts = {r["rating"]: _int(r["n"]) for r in (await session.execute(text(
        "SELECT rating, COUNT(*) n FROM feedback WHERE client_id=:c GROUP BY rating"
    ), P)).mappings().all()}
    down_items = [{"question": r["question"], "answer": r["answer"],
                   "created": _iso(r["created_at"]), "page_context": r["page_context"]}
                  for r in (await session.execute(text(
                      "SELECT question, answer, page_context, created_at FROM feedback "
                      "WHERE client_id=:c AND rating='down' ORDER BY created_at DESC LIMIT 50"
                  ), P)).mappings().all()]
    feedback = {
        "total": sum(fb_counts.values()), "up": fb_counts.get("up", 0),
        "down": fb_counts.get("down", 0), "down_items": down_items,
    }

    # --- unanswered (Python-aggregáció: weekly + questions score/reasons) ---
    ua_rows = (await session.execute(text(
        "SELECT question, score, reasons, created_at FROM unanswered WHERE client_id=:c "
        "ORDER BY created_at DESC"
    ), P)).mappings().all()
    weekly_counts: dict[str, int] = {}
    groups: dict[str, dict] = {}
    for r in ua_rows:
        wk = _iso_week(r["created_at"])
        weekly_counts[wk] = weekly_counts.get(wk, 0) + 1
        q = r["question"] or ""
        g = groups.get(q)
        if g is None:  # első előfordulás = legutóbbi (DESC) -> innen a score + last_ts
            g = groups[q] = {"count": 0, "last_ts": r["created_at"],
                             "score": r["score"], "reasons": set()}
        g["count"] += 1
        for rs in (r["reasons"] or []):
            g["reasons"].add(rs)
    questions = [{
        "question": q, "count": g["count"],
        "score": round(float(g["score"]), 4) if g["score"] is not None else 0.0,
        "reasons": sorted(g["reasons"]), "last_ts": _iso(g["last_ts"]),
    } for q, g in groups.items()]
    questions.sort(key=lambda x: x["last_ts"], reverse=True)
    questions.sort(key=lambda x: x["count"], reverse=True)   # stabil: count DESC, majd last_ts DESC
    questions = questions[:60]
    weekly = [{"week": w, "count": weekly_counts[w]} for w in sorted(weekly_counts)]

    # --- usage/leads összevont current + totals + monthly ---
    cur_conv = _int(cur_u["conversations"]) if cur_u else 0
    cur_msg = _int(cur_u["messages"]) if cur_u else 0
    cur_leads = leads_by_period.get(cp, 0)
    tot_conv = _int(tot_u["c"]) if tot_u else 0

    periods = sorted(set(usage_monthly) | set(leads_by_period))
    monthly = []
    for per in periods:
        u = usage_monthly.get(per)
        monthly.append({
            "period": per,
            "conversations": _int(u["conversations"]) if u else 0,
            "messages": _int(u["messages"]) if u else 0,
            "order_lookups": 0, "product_recs": 0,
            "leads": leads_by_period.get(per, 0),
        })

    return {
        "client_id": cid, "plan": tenant["plan"] or "", "platform": tenant["platform"] or "",
        "bot_name": tenant["bot_name"] or "", "header_color": tenant["header_color"] or "",
        "white_label": bool(tenant["white_label"]), "live_api": bool(tenant["live_api"]),
        "monthly_limit": monthly_limit,
        "generated_at": _iso(now), "current_period": cp,
        "current": {"period": cp, "conversations": cur_conv, "messages": cur_msg,
                    "order_lookups": 0, "product_recs": 0, "leads": cur_leads},
        "limit_pct": round(cur_conv / monthly_limit * 100) if monthly_limit else 0,
        "totals": {"conversations": tot_conv, "messages": _int(tot_u["m"]) if tot_u else 0,
                   "leads": _int(leads_total), "order_lookups": 0, "product_recs": 0},
        "conversion_rate": round(_int(leads_total) / tot_conv * 100, 1) if tot_conv else 0.0,
        "monthly": monthly,
        "leads": leads,
        "feedback": feedback,
        "unanswered": {
            "total": len(ua_rows), "current_week": weekly_counts.get(cw, 0),
            "current_week_label": cw, "weekly": weekly, "questions": questions,
        },
    }

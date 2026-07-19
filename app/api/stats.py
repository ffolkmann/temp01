"""GET /stats?k=<stat_key> — a stat.html adatforrása (az n8n stat-webhook kiváltása).

A `k` a titok (stat_key), nincs egyéb auth. Böngészőből hívódik (nyitott GET, CORS public).
A válasz JSON KULCSRA PONTOS a régi n8n shape-pel — a stat.html render erre épül.

Period kulcs: aktuális hónap Europe/Budapest 'YYYY-MM'. order_lookups/product_recs: 0 (fázis-1).
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.services.unanswered_export import build_unanswered_xlsx
from app.services.conversations_export import build_conversations_xlsx

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


_PERIOD_DAYS = {7, 14, 30, 60, 90}


def _period_window(days, from_s, to_s, now):
    """m70: (from_dt, to_dt, label, days) vagy None, ha nincs idoszak-szures.

    Prioritas: from&to egyutt > days. Hibas parameter -> 400.
    A datumok Europe/Budapest szerinti naphatarok (from 00:00 -> to masnap 00:00).
    """
    if from_s or to_s:
        if not (from_s and to_s):
            raise HTTPException(status_code=400, detail="from es to egyutt kotelezo")
        try:
            f_d = datetime.strptime(from_s, "%Y-%m-%d")
            t_d = datetime.strptime(to_s, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="hibas datum (YYYY-MM-DD)")
        if t_d < f_d or (t_d - f_d).days > 366:
            raise HTTPException(status_code=400, detail="hibas idoszak")
        f_dt = f_d.replace(tzinfo=BUDAPEST)
        t_dt = (t_d + timedelta(days=1)).replace(tzinfo=BUDAPEST)
        return f_dt, t_dt, "%s – %s" % (from_s, to_s), (t_d - f_d).days + 1
    if days is not None:
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="hibas days")
        if days not in _PERIOD_DAYS:
            raise HTTPException(status_code=400, detail="days: 7|14|30|60|90")
        return now - timedelta(days=days), now, "Utolsó %d nap" % days, days
    return None


def _months_between(f_dt: datetime, t_dt: datetime) -> list[str]:
    """Az idoszak altal erintett Europe/Budapest honapok ('YYYY-MM') listaja."""
    a = f_dt.astimezone(BUDAPEST)
    b = (t_dt - timedelta(microseconds=1)).astimezone(BUDAPEST)
    out = []
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


@router.get("/stats")
async def stats(
    k: str = Query(...),
    days: int | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_session),
) -> dict:
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
    pw = _period_window(days, date_from, date_to, now)  # m70: hibas parameter -> 400 mar itt

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

    # --- events (m22): order_lookup / product_rec / link_click / handoff / configurator ---
    ev_rows = (await session.execute(text(
        "SELECT kind, to_char(created_at AT TIME ZONE 'Europe/Budapest','YYYY-MM') period, "
        "COUNT(*) n, COALESCE(SUM(NULLIF(meta->>'count','')::int),0) s "
        "FROM events WHERE client_id=:c GROUP BY 1,2"
    ), P)).mappings().all()
    ev_by_kind: dict[str, dict[str, int]] = {}   # kind -> {period: ertek}
    for r in ev_rows:
        val = _int(r["s"]) if r["kind"] == "product_rec" else _int(r["n"])
        ev_by_kind.setdefault(r["kind"], {})[r["period"]] = val

    def _ev(kind: str, period: str | None = None) -> int:
        d_ = ev_by_kind.get(kind, {})
        return _int(d_.get(period)) if period else sum(d_.values())

    top_links = [{"url": r["url"] or "", "title": r["title"] or "", "count": _int(r["n"])}
                 for r in (await session.execute(text(
                     "SELECT meta->>'url' url, max(meta->>'title') title, COUNT(*) n "
                     "FROM events WHERE client_id=:c AND kind='link_click' "
                     "GROUP BY 1 ORDER BY n DESC LIMIT 10"
                 ), P)).mappings().all()]

    # --- beszélgetés-statisztika (m22, messages napló — 30 napos ablak) ---
    # --- chat-asszisztalt vasarlasok (m48): darabszam az ev_by_kind-bol, ertek kulon ---
    pv = {r["period"]: float(r["v"] or 0) for r in (await session.execute(text(
        "SELECT to_char(created_at AT TIME ZONE 'Europe/Budapest','YYYY-MM') period, "
        "COALESCE(SUM(NULLIF(meta->>'value','')::numeric),0) v "
        "FROM events WHERE client_id=:c AND kind='purchase' GROUP BY 1"
    ), P)).mappings().all()}

    avg_msgs = (await session.execute(text(
        "SELECT ROUND((COUNT(*)::numeric / NULLIF(COUNT(DISTINCT session_id),0)), 1) "
        "FROM messages WHERE client_id=:c"
    ), P)).scalar()
    hourly_rows = (await session.execute(text(
        "SELECT EXTRACT(HOUR FROM created_at AT TIME ZONE 'Europe/Budapest')::int h, COUNT(*) n "
        "FROM messages WHERE client_id=:c GROUP BY 1"
    ), P)).mappings().all()
    hourly = [0] * 24
    for r in hourly_rows:
        h = _int(r["h"])
        if 0 <= h <= 23:
            hourly[h] = _int(r["n"])

    # --- engagement / konverzio (m38, javitva): SESSION-METSZET ---
    # A rata csak azokat a munkameneteket nezi, amelyekben volt impression
    # (a widget boot-kor munkamenetenkent egyszer kuldi). A szamlalo NEM a teljes
    # forgalom, hanem "ezen impression-sessionok kozul hanyban volt utana uzenet /
    # link-kattintas". Igy a nevezo mindig >= szamlalo (nincs 100% feletti rata),
    # es a regi, impression-t nem kuldo widget-verzio forgalma sem szennyezi.
    ENGAGE_WINDOW = 30
    eng = (await session.execute(text(
        "WITH impr AS ("
        "  SELECT DISTINCT session_id FROM events "
        "   WHERE client_id=:c AND kind='impression' "
        "     AND session_id IS NOT NULL "
        "     AND created_at > now() - (:d || ' days')::interval) "
        "SELECT "
        " (SELECT COUNT(*) FROM impr) AS impressions, "
        " (SELECT COUNT(*) FROM impr WHERE session_id IN "
        "     (SELECT session_id FROM messages WHERE client_id=:c)) AS chatted, "
        " (SELECT COUNT(*) FROM impr WHERE session_id IN "
        "     (SELECT session_id FROM events WHERE client_id=:c AND kind='link_click')) AS clicked"
    ), {"c": cid, "d": str(ENGAGE_WINDOW)})).mappings().first()
    eng_impr = _int(eng["impressions"]) if eng else 0
    eng_chat = _int(eng["chatted"]) if eng else 0
    eng_click = _int(eng["clicked"]) if eng else 0
    # a legelso impression datuma -> "meres kezdete" jelzes
    eng_since = (await session.execute(text(
        "SELECT MIN(created_at) FROM events WHERE client_id=:c AND kind='impression'"
    ), P)).scalar()
    # a ratak csak akkor ertelmesek, ha van eleg adat: >=1 teljes nap ES >=20 impression.
    # amig nem: a nyers szamok latszanak, de a szazalek helyett "gyulik" jelzes.
    days_span = 0
    if eng_since is not None:
        days_span = (now - eng_since).days + 1
    eng_ready = bool(eng_impr >= 20 and days_span >= 1)
    engagement = {
        "window_days": ENGAGE_WINDOW,
        "impressions": eng_impr,
        "chatted": eng_chat,
        "clicked": eng_click,
        "chat_rate": round(eng_chat / eng_impr * 100, 1) if eng_impr else 0.0,
        "click_rate": round(eng_click / eng_impr * 100, 1) if eng_impr else 0.0,
        "since": _iso(eng_since),
        "days_span": days_span,
        "tracking_active": bool(eng_impr),   # van-e egyaltalan impression
        "rates_ready": eng_ready,            # megbizhato-e mar a szazalek
    }

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
        "SELECT question, score, reasons, session_id, created_at FROM unanswered "
        "WHERE client_id=:c ORDER BY created_at DESC"
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
                             "score": r["score"], "reasons": set(), "sessions": []}
        g["count"] += 1
        sid = r["session_id"]
        if sid and sid not in g["sessions"] and len(g["sessions"]) < 5:
            g["sessions"].append(sid)  # DESC sorrend -> a legfrissebb sessionök
        for rs in (r["reasons"] or []):
            g["reasons"].add(rs)
    questions = [{
        "question": q, "count": g["count"],
        "score": round(float(g["score"]), 4) if g["score"] is not None else 0.0,
        "reasons": sorted(g["reasons"]), "last_ts": _iso(g["last_ts"]),
        "sessions": g["sessions"],
    } for q, g in groups.items()]
    questions.sort(key=lambda x: x["count"], reverse=True)
    questions.sort(key=lambda x: x["last_ts"], reverse=True)  # stabil: LEGFRISSEBB felül (last_ts DESC), azon belül count DESC
    questions = questions[:60]
    weekly = [{"week": w, "count": weekly_counts[w]} for w in sorted(weekly_counts)]

    # --- m70: idoszak-szures ("period" blokk, csak days= vagy from&to eseten) ---
    period_block = None
    if pw is not None:
        pf, pt, plabel, pdays = pw
        PP = {"c": cid, "f": pf, "t": pt}
        prs = (await session.execute(text(
            "SELECT kind, COUNT(*) n, "
            "COALESCE(SUM(NULLIF(meta->>'count','')::int),0) s, "
            "COALESCE(SUM(NULLIF(meta->>'value','')::numeric),0) v "
            "FROM events WHERE client_id=:c AND created_at >= :f AND created_at < :t "
            "AND kind IN ('product_rec','link_click','order_lookup','handoff','configurator','purchase') "
            "GROUP BY 1"
        ), PP)).mappings().all()
        pev = {r["kind"]: r for r in prs}

        def _pn(kind: str) -> int:
            r = pev.get(kind)
            if r is None:
                return 0
            return _int(r["s"]) if kind == "product_rec" else _int(r["n"])

        p_leads = _int((await session.execute(text(
            "SELECT COUNT(*) FROM leads WHERE client_id=:c AND created_at >= :f AND created_at < :t"
        ), PP)).scalar())
        p_approx = pf < now - timedelta(days=30)
        if not p_approx:
            cm = (await session.execute(text(
                "SELECT COUNT(*) m, COUNT(DISTINCT session_id) cv FROM messages "
                "WHERE client_id=:c AND created_at >= :f AND created_at < :t"
            ), PP)).mappings().first()
            p_conv = _int(cm["cv"]) if cm else 0
            p_msg = _int(cm["m"]) if cm else 0
        else:
            # 30 napnal regebbre nyulo ablak: a messages-naplo (30 nap retention) mar
            # nem teljes -> KOZELITES a havi usage-szamlalokbol (erintett honapok osszege).
            months = "','".join(_months_between(pf, pt))  # belso strftime-ertekek, nem user input
            um = (await session.execute(text(
                "SELECT COALESCE(SUM(conversations),0) cv, COALESCE(SUM(messages),0) m "
                "FROM usage WHERE client_id=:c AND period IN ('" + months + "')"
            ), P)).mappings().first()
            p_conv = _int(um["cv"]) if um else 0
            p_msg = _int(um["m"]) if um else 0
        p_pur = pev.get("purchase")
        period_block = {
            "from": _iso(pf), "to": _iso(pt), "label": plabel, "days": pdays,
            "conversations": p_conv, "messages": p_msg, "conv_msg_approx": p_approx,
            "leads": p_leads,
            "events": {
                "product_recs": _pn("product_rec"),
                "link_clicks": _pn("link_click"),
                "order_lookups": _pn("order_lookup"),
                "handoffs": _pn("handoff"),
                "configurator": _pn("configurator"),
                "purchases": {"count": _pn("purchase"),
                              "value": round(float(p_pur["v"] or 0)) if p_pur is not None else 0},
            },
        }

    # --- usage/leads összevont current + totals + monthly ---
    cur_conv = _int(cur_u["conversations"]) if cur_u else 0
    cur_msg = _int(cur_u["messages"]) if cur_u else 0
    cur_leads = leads_by_period.get(cp, 0)
    tot_conv = _int(tot_u["c"]) if tot_u else 0

    periods = sorted(set(usage_monthly) | set(leads_by_period)
                     | set(ev_by_kind.get("order_lookup", {})) | set(ev_by_kind.get("product_rec", {})))
    monthly = []
    for per in periods:
        u = usage_monthly.get(per)
        monthly.append({
            "period": per,
            "conversations": _int(u["conversations"]) if u else 0,
            "messages": _int(u["messages"]) if u else 0,
            "order_lookups": _ev("order_lookup", per),
            "product_recs": _ev("product_rec", per),
            "leads": leads_by_period.get(per, 0),
        })

    resp = {
        "client_id": cid, "plan": tenant["plan"] or "", "platform": tenant["platform"] or "",
        "bot_name": tenant["bot_name"] or "", "header_color": tenant["header_color"] or "",
        "white_label": bool(tenant["white_label"]), "live_api": bool(tenant["live_api"]),
        "monthly_limit": monthly_limit,
        "generated_at": _iso(now), "current_period": cp,
        "current": {"period": cp, "conversations": cur_conv, "messages": cur_msg,
                    "order_lookups": _ev("order_lookup", cp),
                    "product_recs": _ev("product_rec", cp), "leads": cur_leads},
        "limit_pct": round(cur_conv / monthly_limit * 100) if monthly_limit else 0,
        "totals": {"conversations": tot_conv, "messages": _int(tot_u["m"]) if tot_u else 0,
                   "leads": _int(leads_total),
                   "order_lookups": _ev("order_lookup"), "product_recs": _ev("product_rec")},
        "conversion_rate": round(_int(leads_total) / tot_conv * 100, 1) if tot_conv else 0.0,
        "monthly": monthly,
        "events": {
            "link_clicks": {"total": _ev("link_click"), "current": _ev("link_click", cp),
                            "top": top_links},
            "handoffs": {"total": _ev("handoff"), "current": _ev("handoff", cp)},
            "configurator": {"total": _ev("configurator"), "current": _ev("configurator", cp)},
            "purchases": {"total": _ev("purchase"), "current": _ev("purchase", cp),
                          "value_total": round(sum(pv.values())),
                          "value_current": round(pv.get(cp, 0.0))},
        },
        "conversation_stats": {
            "avg_messages": float(avg_msgs) if avg_msgs is not None else 0.0,
            "hourly": hourly, "window_days": 30,
        },
        "engagement": engagement,
        "leads": leads,
        "feedback": feedback,
        "unanswered": {
            "total": len(ua_rows), "current_week": weekly_counts.get(cw, 0),
            "current_week_label": cw, "weekly": weekly, "questions": questions,
        },
    }
    if period_block is not None:
        resp["period"] = period_block
    return resp


@router.get("/stats/unanswered/export")
async def stats_unanswered_export(
    k: str = Query(...), session: AsyncSession = Depends(get_session),
) -> Response:
    """XLSX-letoltes: a tenant osszes megvalaszolatlan kerdese (m44, stat.html gomb)."""
    tenant = (await session.execute(text(
        "SELECT client_id FROM tenants WHERE stat_key = :k"
    ), {"k": k})).mappings().first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="ismeretlen stat_key")
    cid = tenant["client_id"]
    rows = (await session.execute(text(
        "SELECT question, score, reasons, session_id, created_at FROM unanswered "
        "WHERE client_id=:c ORDER BY created_at DESC"
    ), {"c": cid})).mappings().all()
    msg_rows = (await session.execute(text(
        "SELECT session_id, question, answer, created_at FROM messages "
        "WHERE client_id=:c ORDER BY session_id, created_at, id"
    ), {"c": cid})).mappings().all()
    wanted = {r["session_id"] for r in rows if r["session_id"]}
    transcripts: dict[str, list[dict]] = {}
    for m in msg_rows:
        if m["session_id"] in wanted:
            transcripts.setdefault(m["session_id"], []).append(dict(m))
    data = build_unanswered_xlsx([dict(r) for r in rows], transcripts)
    fname = "megvalaszolatlan-%s-%s.xlsx" % (cid, datetime.now(BUDAPEST).strftime("%Y%m%d-%H%M"))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="%s"' % fname},
    )


@router.get("/stats/conversation")
async def stats_conversation(
    k: str = Query(...), sid: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Egy session teljes beszélgetése — a stat.html visszanéző modálja (m22).

    Auth: stat_key (mint a /stats). A messages napló 30 napos retentionű,
    régebbi sessionöknél a turns üres lehet.
    """
    tenant = (await session.execute(text(
        "SELECT client_id, bot_name FROM tenants WHERE stat_key = :k"
    ), {"k": k})).mappings().first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="ismeretlen stat_key")

    rows = (await session.execute(text(
        "SELECT question, answer, action, created_at FROM messages "
        "WHERE client_id=:c AND session_id=:s ORDER BY created_at, id"
    ), {"c": tenant["client_id"], "s": sid})).mappings().all()
    return {
        "session_id": sid,
        "bot_name": tenant["bot_name"] or "Bot",
        "turns": [{
            "question": r["question"] or "", "answer": r["answer"] or "",
            "action": r["action"] or "", "ts": _iso(r["created_at"]),
        } for r in rows],
    }


@router.get("/admin/overview")
async def admin_overview(
    token: str = Query(...),
    days: int = Query(7),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Osszes tenant forgalmi osszesito az admin panel Attekintes kartyajahoz."""
    import os
    if not token or token != os.environ.get("ADMIN_PANEL_TOKEN", ""):
        raise HTTPException(status_code=403, detail="forbidden")
    days = max(1, min(int(days or 7), 90))
    P = {"d": str(days)}

    trows = (await session.execute(text(
        "SELECT client_id, COALESCE(bot_name,'') bot_name, COALESCE(stat_key,'') stat_key, active "
        "FROM tenants ORDER BY client_id"
    ))).mappings().all()
    mrows = (await session.execute(text(
        "SELECT client_id, COUNT(*) q, COUNT(DISTINCT session_id) conv, MAX(created_at) last_act "
        "FROM messages WHERE created_at > now() - (:d || ' days')::interval GROUP BY client_id"
    ), P)).mappings().all()
    erows = (await session.execute(text(
        "SELECT client_id, kind, COUNT(*) n, COALESCE(SUM(NULLIF(meta->>'count','')::int),0) s "
        "FROM events WHERE created_at > now() - (:d || ' days')::interval GROUP BY 1,2"
    ), P)).mappings().all()
    frows = (await session.execute(text(
        "SELECT client_id, rating, COUNT(*) n FROM feedback "
        "WHERE created_at > now() - (:d || ' days')::interval GROUP BY 1,2"
    ), P)).mappings().all()
    urows = (await session.execute(text(
        "SELECT client_id, COUNT(*) n FROM unanswered "
        "WHERE created_at > now() - (:d || ' days')::interval GROUP BY 1"
    ), P)).mappings().all()

    msg = {r["client_id"]: r for r in mrows}
    ev: dict[str, dict[str, int]] = {}
    for r in erows:
        val = _int(r["s"]) if r["kind"] == "product_rec" else _int(r["n"])
        ev.setdefault(r["client_id"], {})[r["kind"]] = val
    fb_up: dict[str, int] = {}
    fb_down: dict[str, int] = {}
    for r in frows:
        key = str(r["rating"]).strip().lower()
        if key in ("up", "1", "true", "+1", "thumbs_up"):
            fb_up[r["client_id"]] = fb_up.get(r["client_id"], 0) + _int(r["n"])
        else:
            fb_down[r["client_id"]] = fb_down.get(r["client_id"], 0) + _int(r["n"])
    un = {r["client_id"]: _int(r["n"]) for r in urows}

    rows = []
    tot = {"conversations": 0, "questions": 0, "unanswered": 0, "fb_up": 0, "fb_down": 0,
           "product_rec": 0, "order_lookup": 0, "link_click": 0}
    for t in trows:
        cid = t["client_id"]
        m = msg.get(cid)
        e = ev.get(cid, {})
        row = {
            "client_id": cid,
            "bot_name": t["bot_name"],
            "stat_key": t["stat_key"],
            "active": bool(t["active"]),
            "conversations": _int(m["conv"]) if m else 0,
            "questions": _int(m["q"]) if m else 0,
            "unanswered": un.get(cid, 0),
            "fb_up": fb_up.get(cid, 0),
            "fb_down": fb_down.get(cid, 0),
            "product_rec": e.get("product_rec", 0),
            "order_lookup": e.get("order_lookup", 0),
            "link_click": e.get("link_click", 0),
            "last_activity": _iso(m["last_act"]) if m and m["last_act"] else "",
        }
        rows.append(row)
        for k in tot:
            tot[k] += row[k]
    return {"days": days, "rows": rows, "totals": tot}
@router.get("/stats/conversations/export")
async def stats_conversations_export(
    k: str = Query(...), session: AsyncSession = Depends(get_session),
) -> Response:
    """XLSX-letoltes: a tenant OSSZES naplozott beszelgetese (m48, stat.html gomb).

    Forras: a `messages` naplo (30 nap retention). Ket lap: session-onkent
    osszevonva (legfrissebb felul) + nyers turn-naplo."""
    tenant = (await session.execute(text(
        "SELECT client_id FROM tenants WHERE stat_key = :k"
    ), {"k": k})).mappings().first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="ismeretlen stat_key")
    cid = tenant["client_id"]
    rows = (await session.execute(text(
        "SELECT session_id, question, answer, action, created_at FROM messages "
        "WHERE client_id=:c ORDER BY session_id, created_at, id"
    ), {"c": cid})).mappings().all()
    data = build_conversations_xlsx([dict(r) for r in rows])
    fname = "beszelgetesek-%s-%s.xlsx" % (cid, datetime.now(BUDAPEST).strftime("%Y%m%d-%H%M"))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="%s"' % fname},
    )

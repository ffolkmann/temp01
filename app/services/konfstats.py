"""CX Konfigurator tolcser-statisztika (kf/11, stdlib-only, fajl-betoltheto).

Egy latogato esemeny-sora:

    kf_step (n=0)  ->  kf_start  ->  kf_step (n=1..)  ->  kf_done  ->  kf_click / kf_lead
    megjelent          elkezdte      tovabbi kerdesek     vegigert     kattintott / ajanlatot kert

MIERT SESSION-SZINTU: egy latogato tobb termeket is kattinthat, es a "Vissza"
gombbal ujra bejarhatja a kerdeseket, ezert minden lepcsot EGYEDI SESSION-okben
szamolunk (a nyers esemenyszam mellette marad, mert a kattintasnal az is erdekes).

A lead-lepcso KET forrasbol jon:
  - a widget ``kf_lead`` beaconja: akkor is megvan, ha a partner sajat webhookra
    kuld (lead.post_url),
  - a ``leads`` tabla ``source='configurator'`` sorai: ez a foldi igazsag, de
    csak a kozos vegpontnal keletkezik (lasd konflead.py).
Mindkettot visszaadjuk; a UI a nagyobbat mutatja fo szamkent, a masikat mellette.

Itt nincs sqlalchemy: a lekerdezesek NYERS SQL-szovegek, a futtatas a hivoe
(app/api/config.py konf_stats agа). Igy a fuggvenyek fajlbol betolthetok es
DB nelkul tesztelhetok.
"""

KINDS = ("kf_step", "kf_start", "kf_done", "kf_click", "kf_lead")

DEFAULT_DAYS = 30
MAX_DAYS = 365
TOP_LIMIT = 10

_WINDOW = "AND created_at > now() - make_interval(days => :days) "

SQL_FUNNEL = (
    "SELECT kind, count(*) AS c, count(DISTINCT session_id) AS s "
    "FROM events "
    "WHERE client_id = :cid "
    "AND kind IN ('kf_step','kf_start','kf_done','kf_click','kf_lead') "
    + _WINDOW +
    "GROUP BY kind"
)

# kerdesenkenti elerés: hany egyedi session latta az adott kerdest
SQL_STEPS = (
    "SELECT coalesce(meta->>'q','') AS q, coalesce(meta->>'n','0') AS n, "
    "count(DISTINCT session_id) AS s "
    "FROM events "
    "WHERE client_id = :cid AND kind = 'kf_step' "
    + _WINDOW +
    "GROUP BY 1, 2"
)

SQL_TOP = (
    "SELECT meta->>'sku' AS sku, count(*) AS c, count(DISTINCT session_id) AS s "
    "FROM events "
    "WHERE client_id = :cid AND kind = 'kf_click' "
    "AND coalesce(meta->>'sku','') <> '' "
    + _WINDOW +
    "GROUP BY 1 ORDER BY c DESC, 1 LIMIT %d" % TOP_LIMIT
)

SQL_LEADS = (
    "SELECT count(*) FROM leads "
    "WHERE client_id = :cid AND source = 'configurator' "
    + _WINDOW
)


def clamp_days(v, default=DEFAULT_DAYS):
    """Idoszak napokban, 1..365 koze szoritva (szemetre az alapertelmezes)."""
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return default
    return max(1, min(MAX_DAYS, n))


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _row3(r):
    """(a, b, c) barmilyen sor-alakbol (Row, tuple, lista, dict)."""
    if isinstance(r, dict):
        vals = list(r.values())
    else:
        try:
            vals = list(r)
        except TypeError:
            return None, 0, 0
    vals = vals + [None, None, None]
    return vals[0], vals[1], vals[2]


def pct(part, whole):
    """Szazalek egy tizedesre. Nulla nevezo -> None (a UI ilyenkor '-' jelet ir)."""
    p, w = _i(part), _i(whole)
    if w <= 0:
        return None
    return round(p * 100.0 / w, 1)


def _steps(step_rows, questions, done_s=0):
    """Kerdesenkenti eleres + kieses, a RULESET sorrendjeben.

    A parositas elsodlegesen a kerdes id-je szerint megy (a sorrend valtozhat
    ket mereskozott), tartalekban a lepes-index.
    """
    by_q, by_n = {}, {}
    for r in step_rows or []:
        q, n, s = _row3(r)
        q = str(q or "")
        if q:
            by_q[q] = max(by_q.get(q, 0), _i(s))
        by_n[_i(n)] = max(by_n.get(_i(n), 0), _i(s))

    qs = [q for q in (questions or []) if isinstance(q, dict)]
    out = []
    for i, q in enumerate(qs):
        qid = str(q.get("id") or "")
        reach = by_q.get(qid)
        if reach is None:
            reach = by_n.get(i, 0)
        out.append({
            "i": i,
            "id": qid,
            "title": str(q.get("title") or qid or ("%d. kerdes" % (i + 1)))[:160],
            "reach": _i(reach),
        })
    # a kieses mindig a KOVETKEZO lepcsohoz kepest; az utolso kerdes utan a befejezes
    for i, row in enumerate(out):
        nxt = out[i + 1]["reach"] if i + 1 < len(out) else _i(done_s)
        row["next"] = nxt
        row["drop"] = max(0, row["reach"] - nxt)
        row["drop_pct"] = pct(row["drop"], row["reach"])
    return out


def shape(funnel_rows, step_rows=None, top_rows=None, leads_n=0, questions=None, days=DEFAULT_DAYS):
    """A nyers sorokbol a UI-nak szant riport. Tiszta fuggveny, DB nelkul."""
    f = dict((k, {"n": 0, "s": 0}) for k in KINDS)
    for r in funnel_rows or []:
        kind, c, s = _row3(r)
        kind = str(kind or "")
        if kind in f:
            f[kind] = {"n": _i(c), "s": _i(s)}

    steps = _steps(step_rows, questions, f["kf_done"]["s"])
    start_s = f["kf_start"]["s"]
    # Megjelenes = az elso kerdest latok szama. MERT MAX: a kf_step bevezetese
    # elotti sessionoknel nincs step-adat, az inditasuk viszont megvan - enelkul
    # az "elkezdte" arany 100% fole szaladna az atmeneti idoszakban (merve: 425%).
    # Aki elkezdte kitolteni, az definicio szerint latta is az elso kerdest.
    shown = max(steps[0]["reach"] if steps else 0, start_s)
    done_s = f["kf_done"]["s"]
    lead_s = max(f["kf_lead"]["s"], _i(leads_n))

    top = []
    for r in top_rows or []:
        sku, c, s = _row3(r)
        if sku:
            top.append({"sku": str(sku)[:64], "n": _i(c), "s": _i(s)})

    worst = None
    for row in steps:
        if row["reach"] > 0 and row["drop"] > 0:
            if worst is None or row["drop"] > worst["drop"]:
                worst = row

    return {
        "days": clamp_days(days),
        "funnel": {
            "shown": shown,
            "start": start_s,
            "done": done_s,
            "click": f["kf_click"]["s"],
            "click_n": f["kf_click"]["n"],
            "lead": lead_s,
        },
        "rates": {
            "start": pct(start_s, shown),   # akik el is kezdtek kitolteni
            "done": pct(done_s, start_s),   # akik vegig is mentek
            "click": pct(f["kf_click"]["s"], done_s),
            "lead": pct(lead_s, done_s),
        },
        "leads_stored": _i(leads_n),
        "lead_events": f["kf_lead"]["s"],
        "steps": steps,
        "worst_step": ({"id": worst["id"], "title": worst["title"],
                        "drop": worst["drop"], "drop_pct": worst["drop_pct"]}
                       if worst else None),
        "top": top,
        "has_step_data": any(s["reach"] for s in steps),
    }

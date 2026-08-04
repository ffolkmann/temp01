"""SmartSearch kereso-statisztika: nyers DB-sorok -> stat.html blokk + CSV (S3).

A SQL a stats.py-ban van, itt csak a tiszta (fuggvenyszeru) osszefuzes es a
CSV-szerializalas -> fajlbol betoltve tesztelheto, STDLIB ONLY.

Sor-alakok (a stats.py adja igy):
    search_rows : (q, n, avg_total, zero_n)
    click_rows  : (q, n)
    device_rows : (extra_kod, n)
    purchase_rows: (rendelesszam, ertek, eltelt_nap, ts_iso)
"""

CAP = 15
DEVICE_LABELS = {"0": "asztali", "1": "mobil", "2": "tablet"}
CSV_HEADER = ("Keresés", "Keresések", "Átlagos találat", "Nulla találatos",
              "Kattintás", "Átkattintás %")


def _i(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _f(value):
    try:
        return round(float(value or 0), 1)
    except (TypeError, ValueError):
        return 0.0


def _q(value):
    return " ".join(str(value or "").split()).strip()[:120]


def _rate(part, whole):
    return round(part / whole * 100, 1) if whole else 0.0


def term_stats(search_rows, click_rows):
    """Keresesek + kattintasok osszefuzese kifejezesenkent (kattintas-arannyal)."""
    clicks = {}
    for row in click_rows or []:
        q = _q(row[0])
        if q:
            clicks[q] = clicks.get(q, 0) + _i(row[1])
    terms = []
    searches = zero = 0
    for row in search_rows or []:
        q = _q(row[0])
        if not q:
            continue
        n = _i(row[1])
        z = _i(row[3]) if len(row) > 3 else 0
        c = _i(clicks.get(q))
        searches += n
        zero += z
        terms.append({"q": q, "n": n, "avg_total": _f(row[2]) if len(row) > 2 else 0.0,
                      "zero": z, "clicks": c, "ctr": _rate(c, n)})
    terms.sort(key=lambda t: t["n"], reverse=True)
    total_clicks = sum(t["clicks"] for t in terms)
    return {"searches": searches, "clicks": total_clicks, "zero": zero,
            "click_rate": _rate(total_clicks, searches), "terms": terms}


def top_by(terms, key, cap=CAP):
    """A megadott kulcs szerinti top lista (0 erteku sorok kiesnek)."""
    rows = [t for t in (terms or []) if _i(t.get(key)) > 0]
    rows.sort(key=lambda t: (_i(t.get(key)), _i(t.get("n"))), reverse=True)
    return rows[:cap]


def devices(device_rows):
    """Eszkoz-megoszlas az ss_search extra mezojebol (0/1/2)."""
    out = {"asztali": 0, "mobil": 0, "tablet": 0}
    for row in device_rows or []:
        label = DEVICE_LABELS.get(str(row[0] or "0").strip())
        if label:
            out[label] += _i(row[1])
    out["total"] = out["asztali"] + out["mobil"] + out["tablet"]
    return out


def purchases(purchase_rows, cap=50):
    """Kereses utani vasarlasok (best-effort attribucio a widgetbol)."""
    rows = []
    value = 0
    for row in (purchase_rows or [])[:cap]:
        val = _i(row[1])
        value += val
        rows.append({"order": _q(row[0]), "value": val, "days": _i(row[2]),
                     "ts": str(row[3] or "")})
    return {"count": len(rows), "value": value, "rows": rows}


def _cell(value):
    text = str(value if value is not None else "").replace("\r", " ").replace("\n", " ")
    if ";" in text or '"' in text:
        text = '"%s"' % text.replace('"', '""')
    return text


def csv_text(terms):
    """UTF-8 BOM + pontosvesszos CSV (Excel-baratsag), CRLF sorvegekkel."""
    lines = [";".join(CSV_HEADER)]
    for t in terms or []:
        lines.append(";".join(_cell(x) for x in (
            t.get("q", ""), _i(t.get("n")), _f(t.get("avg_total")),
            _i(t.get("zero")), _i(t.get("clicks")), _f(t.get("ctr")))))
    return "\ufeff" + "\r\n".join(lines) + "\r\n"

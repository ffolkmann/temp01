"""S3 - SmartSearch kereso-statisztika osszefuzes + CSV (app/services/searchstats.py).

Fajlbol toltve (suite-konvencio): stdlib-only modul, nincs app-import.
"""

import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "searchstats.py"
_spec = importlib.util.spec_from_file_location("searchstats_s3_under_test", _P)
SS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SS)


def _rows():
    # (q, keresesek, atlagos talalat, nulla-talalatos)
    return [
        ("uleshuzat", 10, 24.0, 0),
        ("padloszonyeg", 6, 12.0, 1),
        ("nincs ilyen", 4, 0.0, 4),
        ("  ", 3, 1.0, 0),
    ]


def test_term_stats_osszefuzi_a_kattintasokat():
    st = SS.term_stats(_rows(), [("uleshuzat", 5), ("padloszonyeg", 3), ("", 9)])
    assert st["searches"] == 20          # az ures kifejezes kiesik
    assert st["clicks"] == 8
    assert st["zero"] == 5
    assert st["click_rate"] == 40.0
    first = st["terms"][0]
    assert first["q"] == "uleshuzat" and first["clicks"] == 5 and first["ctr"] == 50.0


def test_term_stats_ures_bemenet():
    st = SS.term_stats([], [])
    assert st == {"searches": 0, "clicks": 0, "zero": 0, "click_rate": 0.0, "terms": []}


def test_term_stats_szemet_ertekek_nem_dobnak():
    st = SS.term_stats([("x", "nem szam", None, "?")], [("x", None)])
    assert st["terms"][0]["n"] == 0 and st["terms"][0]["avg_total"] == 0.0
    assert st["click_rate"] == 0.0


def test_top_by_kiszuri_a_nullat_es_vag():
    terms = SS.term_stats(_rows(), [("uleshuzat", 5)])["terms"]
    assert [t["q"] for t in SS.top_by(terms, "zero")] == ["nincs ilyen", "padloszonyeg"]
    assert [t["q"] for t in SS.top_by(terms, "clicks")] == ["uleshuzat"]
    assert len(SS.top_by(terms, "n", cap=2)) == 2


def test_devices_megoszlas():
    d = SS.devices([("0", 12), ("1", 30), ("2", 3), ("9", 100), (None, 1)])
    assert d == {"asztali": 13, "mobil": 30, "tablet": 3, "total": 46}
    assert SS.devices([])["total"] == 0


def test_purchases_osszeg_es_sorok():
    p = SS.purchases([("W-1001", 45900, 2, "2026-08-04T10:00:00Z"),
                      ("W-1002", "nem szam", 0, "2026-08-03T09:00:00Z")])
    assert p["count"] == 2 and p["value"] == 45900
    assert p["rows"][0] == {"order": "W-1001", "value": 45900, "days": 2,
                            "ts": "2026-08-04T10:00:00Z"}
    assert SS.purchases(None) == {"count": 0, "value": 0, "rows": []}


def test_csv_bom_pontosvesszo_es_escape():
    terms = SS.term_stats([("felni; kerek", 3, 7.0, 0)], [])["terms"]
    csv = SS.csv_text(terms)
    assert csv.startswith("\ufeff")
    assert csv.endswith("\r\n")
    head, row = csv[1:].split("\r\n")[0], csv[1:].split("\r\n")[1]
    assert head.count(";") == 5
    assert row.startswith('"felni; kerek";3;7.0;0;0;0.0')


def test_csv_ures_lista_csak_fejlec():
    csv = SS.csv_text([])
    assert csv[1:].strip().count(";") == 5

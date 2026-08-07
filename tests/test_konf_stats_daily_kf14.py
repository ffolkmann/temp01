"""kf/14: a tolcser NAPI bontasa (konfstats.daily) — file-load import (kf/9 minta).

A modul stdlib-only, ezert az app-csomag betoltese nelkul teszteljuk: a suite
mas tesztjei fake `app.services`-t hagyhatnak a sys.modules-ben.
"""
import datetime
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konfstats.py"
_spec = importlib.util.spec_from_file_location("konfstats_daily_under_test", _P)
ks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ks)


def test_ures_bemenet():
    assert ks.daily([]) == []
    assert ks.daily(None, None) == []


def test_napi_osszerakas_es_sorrend():
    rows = [("2026-08-02", "kf_step", 2),
            ("2026-08-01", "kf_step", 5),
            ("2026-08-01", "kf_start", 4),
            ("2026-08-01", "kf_done", 3)]
    out = ks.daily(rows)
    assert [r["d"] for r in out] == ["2026-08-01", "2026-08-02"]   # novekvo datum
    assert out[0] == {"d": "2026-08-01", "shown": 5, "start": 4, "done": 3, "lead": 0}


def test_shown_sosem_kisebb_az_inditasnal():
    """A kf/11a tanulsaga napi szinten is: aki elkezdte, az latta az elso kerdest."""
    out = ks.daily([("2026-08-01", "kf_start", 7)])
    assert out[0]["shown"] == 7 and out[0]["start"] == 7


def test_lead_a_ket_forras_maximuma():
    # a leads tabla tobbet tud (kozos vegpont)
    out = ks.daily([("2026-08-01", "kf_lead", 1)], [("2026-08-01", 3)])
    assert out[0]["lead"] == 3
    # a beacon tud tobbet (sajat webhookos partner)
    out = ks.daily([("2026-08-01", "kf_lead", 4)], [("2026-08-01", 1)])
    assert out[0]["lead"] == 4


def test_csak_a_leads_tablabol_van_adat():
    assert ks.daily([], [("2026-08-05", 2)]) == [
        {"d": "2026-08-05", "shown": 0, "start": 0, "done": 0, "lead": 2}]


def test_date_objektum_es_ismeretlen_esemeny():
    d = datetime.date(2026, 8, 3)
    out = ks.daily([(d, "kf_click", 9), (d, "kf_step", 1)])
    assert len(out) == 1
    assert out[0]["d"] == "2026-08-03" and out[0]["shown"] == 1   # a kf_click nem lepcso


def test_szemet_sor_nem_dol_el_rajta():
    out = ks.daily([("", "kf_step", 1), None, ("2026-08-01", "kf_step", 2)])
    assert out == [{"d": "2026-08-01", "shown": 2, "start": 0, "done": 0, "lead": 0}]


def test_hosszu_idoszak_vagasa():
    rows = [("2026-%02d-%02d" % (m, dd), "kf_step", 1)
            for m in (1, 2, 3, 4) for dd in range(1, 29)]
    out = ks.daily(rows)
    assert len(out) <= 92 and out[-1]["d"] == "2026-04-28"   # a legfrissebbek maradnak


def test_sql_szovegek_epek():
    for sql in (ks.SQL_DAILY, ks.SQL_LEADS_DAILY):
        assert ":cid" in sql and ":days" in sql and "GROUP BY" in sql
    assert "events" in ks.SQL_DAILY and "leads" in ks.SQL_LEADS_DAILY

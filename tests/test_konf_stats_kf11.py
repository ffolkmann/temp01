"""kf/11: a konfigurator-tolcser tiszta fuggvenyei — file-load import."""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konfstats.py"
_spec = importlib.util.spec_from_file_location("konfstats_under_test", _P)
ks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ks)


QS = [
    {"id": "lapszam", "title": "Havi lapszam?"},
    {"id": "szin", "title": "Szines vagy fekete-feher?"},
    {"id": "mfp", "title": "Kell szkenner?"},
]


def _funnel(step=0, start=0, done=0, click=(0, 0), lead=0):
    return [
        ("kf_step", step * 3, step),
        ("kf_start", start, start),
        ("kf_done", done, done),
        ("kf_click", click[0], click[1]),
        ("kf_lead", lead, lead),
    ]


# --------------------------------------------------------------------------- #
# clamp_days / pct
# --------------------------------------------------------------------------- #
def test_clamp_days():
    assert ks.clamp_days(7) == 7
    assert ks.clamp_days("30") == 30
    assert ks.clamp_days(0) == 1
    assert ks.clamp_days(9999) == ks.MAX_DAYS
    assert ks.clamp_days("szemet") == ks.DEFAULT_DAYS
    assert ks.clamp_days(None) == ks.DEFAULT_DAYS


def test_pct():
    assert ks.pct(1, 2) == 50.0
    assert ks.pct(1, 3) == 33.3
    assert ks.pct(5, 0) is None      # nulla nevezo -> a UI '-' jelet ir
    assert ks.pct(0, 10) == 0.0


# --------------------------------------------------------------------------- #
# funnel
# --------------------------------------------------------------------------- #
def test_shape_alap_szamok():
    out = ks.shape(_funnel(start=40, done=25, click=(60, 20), lead=6),
                   step_rows=[("lapszam", "0", 100), ("szin", "1", 70), ("mfp", "2", 30)],
                   questions=QS, days=30)
    assert out["funnel"]["shown"] == 100      # az elso kerdest 100 session latta
    assert out["funnel"]["start"] == 40
    assert out["funnel"]["done"] == 25
    assert out["funnel"]["click"] == 20 and out["funnel"]["click_n"] == 60
    assert out["rates"]["start"] == 40.0      # 40/100 kezdte el
    assert out["rates"]["done"] == 62.5       # 25/40 fejezte be
    assert out["rates"]["lead"] == 24.0       # 6/25 kert ajanlatot


def test_shape_lead_a_ket_forras_nagyobbika():
    out = ks.shape(_funnel(start=10, done=10, lead=3), leads_n=5, questions=QS)
    assert out["funnel"]["lead"] == 5         # a leads tabla tobbet tud
    assert out["leads_stored"] == 5 and out["lead_events"] == 3
    out2 = ks.shape(_funnel(start=10, done=10, lead=7), leads_n=0, questions=QS)
    assert out2["funnel"]["lead"] == 7        # sajat webhook: csak esemeny van


def test_shape_ures_adat_nem_szall_el():
    out = ks.shape([], questions=QS)
    assert out["funnel"]["shown"] == 0 and out["rates"]["done"] is None
    assert out["has_step_data"] is False
    assert out["worst_step"] is None
    assert len(out["steps"]) == 3


def test_shape_regi_widget_nincs_kf_step():
    """kf_step nelkul a megjelenes az inditasok szamara esik vissza."""
    out = ks.shape(_funnel(start=13, done=10), questions=QS)
    assert out["funnel"]["shown"] == 13
    assert out["has_step_data"] is False
    assert out["rates"]["start"] == 100.0


# --------------------------------------------------------------------------- #
# kerdesenkenti kieses
# --------------------------------------------------------------------------- #
def test_steps_kieses_a_kovetkezo_lepcsohoz_kepest():
    out = ks.shape(_funnel(start=100, done=30),
                   step_rows=[("lapszam", "0", 100), ("szin", "1", 90), ("mfp", "2", 40)],
                   questions=QS)
    s = out["steps"]
    assert [x["reach"] for x in s] == [100, 90, 40]
    assert [x["drop"] for x in s] == [10, 50, 10]      # az utolso a befejezeshez kepest
    assert s[1]["drop_pct"] == 55.6
    assert out["worst_step"]["id"] == "szin"          # itt lepnek ki a legtobben


def test_steps_a_ruleset_sorrendjet_koveti_id_szerint():
    """A meres sorrendje mas is lehet, mint a kerdesek mai sorrendje."""
    out = ks.shape(_funnel(done=5),
                   step_rows=[("mfp", "2", 40), ("lapszam", "0", 100), ("szin", "1", 90)],
                   questions=QS)
    assert [x["id"] for x in out["steps"]] == ["lapszam", "szin", "mfp"]
    assert [x["reach"] for x in out["steps"]] == [100, 90, 40]


def test_steps_index_alapu_tartalek_ha_nincs_q():
    """Regi esemenyek q nelkul: a lepes-index alapjan parositunk."""
    out = ks.shape(_funnel(done=1),
                   step_rows=[("", "0", 50), ("", "1", 20)],
                   questions=QS)
    assert [x["reach"] for x in out["steps"]] == [50, 20, 0]


def test_steps_ismetelt_bejaras_nem_duplaz():
    """Ugyanaz a kerdes tobb sorban (pl. q + index) -> a nagyobb szam szamit."""
    out = ks.shape(_funnel(done=1), step_rows=[("lapszam", "0", 30), ("lapszam", "0", 55)],
                   questions=QS)
    assert out["steps"][0]["reach"] == 55


# --------------------------------------------------------------------------- #
# top kattintasok / sor-alakok
# --------------------------------------------------------------------------- #
def test_top_kattintasok():
    out = ks.shape(_funnel(), top_rows=[("MX431adn", 9, 7), ("B225", 4, 4), (None, 3, 3)],
                   questions=QS)
    assert [t["sku"] for t in out["top"]] == ["MX431adn", "B225"]   # ures sku kiesik
    assert out["top"][0]["n"] == 9 and out["top"][0]["s"] == 7


def test_sor_alakok_dict_es_tuple():
    out = ks.shape([{"kind": "kf_start", "c": 5, "s": 5}], questions=QS)
    assert out["funnel"]["start"] == 5


# --------------------------------------------------------------------------- #
# SQL-szovegek: parameterezes es idoablak
# --------------------------------------------------------------------------- #
def test_sql_parameterek():
    for sql in (ks.SQL_FUNNEL, ks.SQL_STEPS, ks.SQL_TOP, ks.SQL_LEADS):
        assert ":cid" in sql and ":days" in sql
        assert "make_interval" in sql
        assert "%" not in sql          # nincs benne string-formazas maradek


def test_sql_nem_tartalmaz_beegetett_tenantot():
    for sql in (ks.SQL_FUNNEL, ks.SQL_STEPS, ks.SQL_TOP, ks.SQL_LEADS):
        assert "copygo" not in sql

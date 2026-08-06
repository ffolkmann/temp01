"""S6/5 tesztek: AI-mezok a kereso-configban + AI-valasz statisztika.

Mindket modul stdlib-only, ezert egyszeru fajl-betoltessel megy (nincs app-fake).
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CF = _load("searchcfg_s6ai", "app/services/searchcfg.py")
ST = _load("searchstats_s6ai", "app/services/searchstats.py")


# --------------------------------------------------------------------------- #
# searchcfg: AI-mezok
# --------------------------------------------------------------------------- #
def test_peldakerdesek_max_negy_es_tisztitva():
    text = "  melyik uleshuzat illik?  \n\nmilyen felni jo telre?\n" + "x" * 200 + "\nnegyedik\notodik"
    out = CF.parse_examples(text)
    assert out[0] == "melyik uleshuzat illik?"      # trim + osszevont whitespace
    assert len(out) == 4                            # max 4
    assert len(out[2]) == 80                        # hosszra vagva
    assert CF.parse_examples("") == [] and CF.parse_examples(None) == []


def test_napi_plafon_ertelmezese():
    assert CF.parse_cap("") == CF.DEFAULT_DAILY_CAP      # ures -> alapertelmezes
    assert CF.parse_cap(None) == CF.DEFAULT_DAILY_CAP
    assert CF.parse_cap("szemet") == CF.DEFAULT_DAILY_CAP
    assert CF.parse_cap("0") == 0                        # 0 = teljesen ki
    assert CF.parse_cap("50") == 50
    assert CF.parse_cap(" 1 000 ") == 1000               # szokozos beiras
    assert CF.parse_cap("-5") == 0                       # negativ nem letezik
    assert CF.parse_cap("999999") == 5000                # felso hatar


def test_urlap_es_config_oda_vissza():
    form = {
        "enabled": "on", "synonyms": "", "oneway": "", "popular_terms": "",
        "popular_skus": "", "merch": "",
        "ai_answer": "on", "ai_daily_cap": "120",
        "ai_examples": "melyik uleshuzat illik a Model 3-hoz?\nmilyen felni jo?",
    }
    cfg = CF.form_to_config(form)
    assert cfg["ai_answer"] is True and cfg["ai_daily_cap"] == 120
    assert cfg["ai_examples"] == ["melyik uleshuzat illik a Model 3-hoz?", "milyen felni jo?"]
    back = CF.config_to_form(cfg)
    assert back["ai_answer"] is True and back["ai_daily_cap"] == 120
    assert back["ai_examples"].split("\n") == cfg["ai_examples"]


def test_ai_kikapcsolva_alapbol():
    cfg = CF.form_to_config({"enabled": "on"})
    assert cfg["ai_answer"] is False
    assert cfg["ai_examples"] == []
    assert cfg["ai_daily_cap"] == CF.DEFAULT_DAILY_CAP


def test_a_peldak_torolhetok_a_mentessel():
    """Az urlap MOST eloallitja az ai_* kulcsokat, tehat az uritesuk is atmegy."""
    old = {"ai_examples": ["regi kerdes"], "ai_answer": True, "shoprenter": {"categories": [1]}}
    new = CF.form_to_config({"enabled": "on", "ai_answer": "on", "ai_examples": ""})
    merged = CF.merge_preserving(old, new)
    assert merged["ai_examples"] == []                    # a torles ervenyesul
    assert merged["shoprenter"] == {"categories": [1]}    # az urlapon kivuli kulcs marad


# --------------------------------------------------------------------------- #
# searchstats.answers
# --------------------------------------------------------------------------- #
def test_ai_statisztika_osszefuzes():
    out = ST.answers(
        answer_rows=[("1", "0", 6), ("1", "1", 4), ("0", "0", 5)],   # 10 sikeres (4 cache), 5 sikertelen
        click_total=3,
        hint_rows=[("1", 7), ("2", 2), ("0", 9)],                    # a 0-s forras nem szamit
        word_rows=[("q", 12), ("s", 28)],
    )
    assert out["asked"] == 15 and out["answered"] == 10
    assert out["answer_rate"] == 66.7
    assert out["cached"] == 4 and out["cache_rate"] == 40.0
    assert out["clicks"] == 3 and out["click_rate"] == 30.0
    assert out["hint_zero"] == 7 and out["hint_tip"] == 2 and out["hints"] == 9
    assert out["sentence"] == 12 and out["keyword"] == 28 and out["sentence_rate"] == 30.0
    assert out["active"] is True


def test_ai_statisztika_ures_es_nullaval_oszt():
    out = ST.answers([], 0, [], [])
    assert out["asked"] == 0 and out["answered"] == 0
    assert out["answer_rate"] == 0.0 and out["click_rate"] == 0.0
    assert out["sentence_rate"] == 0.0
    assert out["active"] is False


def test_ai_statisztika_csak_tippbol_is_aktiv():
    """Ha meg egyetlen AI-hivas sem volt, de a tippre kattintottak, mar van mit mutatni."""
    out = ST.answers([], 0, [("2", 1)], [("s", 4)])
    assert out["active"] is True and out["hints"] == 1 and out["asked"] == 0


def test_ai_statisztika_hibas_sorokat_tur():
    out = ST.answers([(None, None, "x"), ("1", "1", 2)], "3", [(None, 5)], [("", 1)])
    assert out["asked"] == 2 and out["answered"] == 2 and out["cached"] == 2
    assert out["clicks"] == 3 and out["hints"] == 0 and out["keyword"] == 1

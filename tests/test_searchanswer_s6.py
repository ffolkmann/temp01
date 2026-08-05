"""S6 tesztek: AI-valasz tiszta magja (app/services/searchanswer.py).

Fajl-betoltos import (stdlib-only modul, nincs app-import).
"""

import importlib.util
import json
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "searchanswer.py"
_spec = importlib.util.spec_from_file_location("searchanswer_s6_under_test", _P)
SA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SA)


# --------------------------------------------------------------------------- #
# trigger
# --------------------------------------------------------------------------- #
def test_kerdes_felismeres_pozitiv():
    for q in ("melyik uleshuzat illik a Model Y-hoz",
              "b\u00edrja a t\u00e9li hideget?",
              "mit aj\u00e1nlasz Highlandhez",
              "milyen felni j\u00f3 r\u00e1",
              "aj\u00e1nlj valamit aj\u00e1nd\u00e9kba",
              "melyik a jobb a kett\u0151 k\u00f6z\u00fcl"):
        assert SA.is_question(q) is True, q


def test_kerdes_felismeres_negativ():
    # a valodi naplobol: marka- es tipusszam-toredekek, rovid kifejezesek
    for q in ("uleshuzat", "matt karbon dekor", "thinkkpad", "hp 924", "bq-4102",
              "lenovo thinkpad", "", "   ", None):
        assert SA.is_question(q) is False, q


def test_needs_answer_haromfele_kapu():
    assert SA.needs_answer("uleshuzat", 120) is False          # sima kereses, van talalat
    assert SA.needs_answer("uleshuzat", 0) is True             # nulla talalat -> segitunk
    assert SA.needs_answer("melyik j\u00f3 a Model Y-hoz", 50) is True   # kerdes
    assert SA.needs_answer("uleshuzat", 120, force=True) is True        # demo-kapcsolo
    assert SA.needs_answer("", 0, force=True) is False                  # ures sosem
    assert SA.needs_answer("uleshuzat", "szemet") is True              # rossz total = 0


def test_norm_q_cache_kulcs():
    assert SA.norm_q("  Melyik \u00dcL\u00c9SHUZAT  illik? ") == "melyik uleshuzat illik"
    assert SA.norm_q("MELYIK uleshuzat illik") == SA.norm_q("melyik \u00fcl\u00e9shuzat illik")
    assert SA.norm_q(None) == ""


# --------------------------------------------------------------------------- #
# jeloltek
# --------------------------------------------------------------------------- #
def _jeloltek():
    return SA.clean_candidates([
        {"i": "1", "n": "Model Y \u00fcl\u00e9shuzat", "a": 1, "b": "TESERY", "c": "Bels\u0151", "x": "\u00f6ko b\u0151r"},
        {"i": "2", "n": "Nincs k\u00e9szlet", "a": 0},
        {"i": "", "n": "nincs id"},
        {"n": "nincs i"},
        "nem dict",
        {"i": "3", "n": "  sok    sz\u00f3k\u00f6z  ", "a": True},
    ])


def test_clean_candidates_higienia():
    c = _jeloltek()
    assert [x["i"] for x in c] == ["1", "3"]          # keszlethiany es szemet kiesik
    assert c[1]["n"] == "sok sz\u00f3k\u00f6z"                 # szokoz-tomorites
    assert c[0]["b"] == "TESERY" and c[0]["x"] == "\u00f6ko b\u0151r"


def test_clean_candidates_cap_es_ures():
    sok = [{"i": str(i), "n": "T%d" % i, "a": 1} for i in range(30)]
    assert len(SA.clean_candidates(sok)) == SA.MAX_CANDIDATES
    assert SA.clean_candidates(None) == [] and SA.clean_candidates("szemet") == []


def test_prompt_tartalmazza_a_pideket_es_nincs_benne_ar():
    p = SA.build_user_prompt("melyik j\u00f3?", _jeloltek())
    assert "[1]" in p and "[3]" in p and "TESERY" in p
    assert "Ft" not in p and "HUF" not in p


# --------------------------------------------------------------------------- #
# valasz-feldolgozas
# --------------------------------------------------------------------------- #
def test_parse_reply_kodblokkbol_es_szemetbol():
    raw = '```json\n{"a":"sz\u00f6veg","pids":["1","2"]}\n```'
    assert SA.parse_reply(raw) == ("sz\u00f6veg", ["1", "2"])
    for szemet in ("", None, "Szia! Ezt aj\u00e1nlom.", "{nem json}", "[1,2]"):
        assert SA.parse_reply(szemet) == ("", [])


def test_strip_prices_csak_az_aras_mondatot_dobja():
    t = SA.strip_prices("Ez j\u00f3 v\u00e1laszt\u00e1s. \u00c1ra 45 900 Ft. Tart\u00f3s anyagb\u00f3l k\u00e9sz\u00fcl.")
    assert t == "Ez j\u00f3 v\u00e1laszt\u00e1s. Tart\u00f3s anyagb\u00f3l k\u00e9sz\u00fcl."
    assert SA.strip_prices("Mind a 3 db raktáron, 12 900 Ft-t\u00f3l.") == ""


def test_finalize_feherlista_dedup_es_vagas():
    c = _jeloltek()
    raw = json.dumps({"a": "A TESERY huzat illik a Model Y-hoz. \u00c1ra 45 900 Ft.",
                      "pids": ["1", "999", "3", "1"]}, ensure_ascii=False)
    out = SA.finalize(raw, c)
    assert out["pids"] == ["1", "3"]                       # hallucinalt kiesik, dedup
    assert "Ft" not in out["answer"] and "45" not in out["answer"]


def test_finalize_nincs_sav_esetei():
    c = _jeloltek()
    assert SA.finalize('{"a":"j\u00f3 ez","pids":["999"]}', c) is None      # csak hallucinalt pid
    assert SA.finalize('{"a":"j\u00f3 ez","pids":[]}', c) is None           # nincs termek
    assert SA.finalize("Szia!", c) is None                                  # nem JSON
    assert SA.finalize('{"a":"Ez 45 900 Ft.","pids":["1"]}', c) is None     # csak aras mondat
    assert SA.finalize('{"a":"r\u00f6vid","pids":["1"]}', c) is None        # tul rovid szoveg
    assert SA.finalize('{"a":"Ez teljesen rendben van igy.","pids":["1"]}', []) is None


def test_finalize_max_harom_termek():
    c = SA.clean_candidates([{"i": str(i), "n": "T%d" % i, "a": 1} for i in range(6)])
    out = SA.finalize(json.dumps({"a": "Mind a hat j\u00f3 v\u00e1laszt\u00e1s ide.",
                                  "pids": ["0", "1", "2", "3", "4"]}), c)
    assert len(out["pids"]) == SA.MAX_PICKS

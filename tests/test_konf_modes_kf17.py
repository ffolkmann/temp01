"""kf/17: egyszeru/halado mod — ruleset-sema + tolcser-bontas tesztjei.

File-load import (kf/9 minta): a suite mas tesztjei fake `app.services`-t
hagyhatnak a sys.modules-ben.
"""
import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kc = _load("konfcfg_kf17", "app/services/konfcfg.py")
ks = _load("konfstats_kf17", "app/services/konfstats.py")


def _q(qid, mode=None, title=None):
    q = {"id": qid, "title": title or ("K\u00e9rd\u00e9s " + qid),
         "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
    if mode is not None:
        q["mode"] = mode
    return q


def _cfg(questions, modes=None, **kw):
    c = {"enabled": True, "index_base": "https://codexpress.cloud/cx-search/x",
         "questions": questions}
    if modes is not None:
        c["modes"] = modes
    c.update(kw)
    return c


# --------------------------------------------------------------------------- #
# kerdes-szintu mode
# --------------------------------------------------------------------------- #
def test_kerdes_mode_alapja_both():
    n = kc.normalize_ruleset(_cfg([_q("a")]))
    assert n["questions"][0]["mode"] == "both"


def test_kerdes_mode_ertekek():
    n = kc.normalize_ruleset(_cfg([_q("a", "advanced"), _q("b", "basic"),
                                   _q("c", "both"), _q("d", " ADVANCED ")]))
    assert [q["mode"] for q in n["questions"]] == ["advanced", "basic", "both", "advanced"]


def test_ismeretlen_mode_bothra_esik():
    """Szemet-ertek NEM tuntetheti el a kerdest a widgetbol."""
    for bad in ("halado", "", None, 5, [], "expert"):
        n = kc.normalize_ruleset(_cfg([_q("a", bad)]))
        assert n["questions"][0]["mode"] == "both", bad


def test_regi_ruleset_valtozatlan():
    """VISSZAFELE KOMPATIBILITAS: mode nelkuli configbol nem lesz mod-valaszto."""
    n = kc.normalize_ruleset(_cfg([_q("a"), _q("b")]))
    assert n["modes"]["enabled"] is False
    assert n["modes"]["force"] == ""
    assert all(q["mode"] == "both" for q in n["questions"])


# --------------------------------------------------------------------------- #
# modes blokk
# --------------------------------------------------------------------------- #
def test_modes_bekapcsol_ha_van_valtozat():
    n = kc.normalize_ruleset(_cfg([_q("a"), _q("b", "advanced")],
                                  modes={"enabled": True}))
    assert n["modes"]["enabled"] is True


def test_modes_FAIL_SAFE_valtozat_nelkul_nem_kapcsol_be():
    """Ha minden kerdes 'both', a ket ut UGYANAZ - ertelmetlen kepernyo lenne."""
    n = kc.normalize_ruleset(_cfg([_q("a"), _q("b")], modes={"enabled": True}))
    assert n["modes"]["enabled"] is False


def test_modes_ures_kerdeslistaval_sem_kapcsol_be():
    n = kc.normalize_ruleset(_cfg([], modes={"enabled": True}))
    assert n["modes"]["enabled"] is False


def test_force_kikapcsolja_a_valasztot():
    """Admin-kapcsolo: ha kenyszeritett a mod, nincs valaszto-kepernyo."""
    for f in ("basic", "advanced"):
        n = kc.normalize_ruleset(_cfg([_q("a"), _q("b", "advanced")],
                                      modes={"enabled": True, "force": f}))
        assert n["modes"]["force"] == f
        assert n["modes"]["enabled"] is False


def test_force_szemetre_ures():
    for bad in ("mindegy", "BASIC ", "", None, 7):
        n = kc.normalize_ruleset(_cfg([_q("a", "advanced")],
                                      modes={"enabled": True, "force": bad}))
        assert n["modes"]["force"] in ("", "basic"), bad
    # a kisbetusites/trim viszont mukodik
    n2 = kc.normalize_ruleset(_cfg([_q("a", "advanced")], modes={"force": " Advanced "}))
    assert n2["modes"]["force"] == "advanced"


def test_modes_alapertelmezett_feliratok():
    n = kc.normalize_ruleset(_cfg([_q("a", "advanced")], modes={"enabled": True}))
    m = n["modes"]
    assert m["basic_label"] and m["adv_label"] and m["switch_label"]
    assert m["title"] == "" and m["basic_sub"] == ""


def test_modes_sajat_feliratok_es_hossz_korlat():
    n = kc.normalize_ruleset(_cfg([_q("a", "advanced")], modes={
        "enabled": True, "title": "Hogyan v\u00e1lasszunk?",
        "basic_label": "Gyorsan", "basic_sub": "3 k\u00e9rd\u00e9s",
        "adv_label": "R\u00e9szletesen", "adv_sub": "8 k\u00e9rd\u00e9s",
        "switch_label": "Pontos\u00edtom", "ismeretlen": "kuka"}))
    m = n["modes"]
    assert m["basic_label"] == "Gyorsan" and m["adv_sub"] == "8 k\u00e9rd\u00e9s"
    assert m["title"] == "Hogyan v\u00e1lasszunk?" and m["switch_label"] == "Pontos\u00edtom"
    assert "ismeretlen" not in m           # ismeretlen kulcs kiesik
    long_n = kc.normalize_ruleset(_cfg([_q("a", "advanced")],
                                       modes={"enabled": True, "basic_label": "x" * 300}))
    assert len(long_n["modes"]["basic_label"]) == 60


def test_modes_szemet_tipusra_sem_dol_el():
    for bad in ("nem-dict", 5, [], None):
        n = kc.normalize_ruleset(_cfg([_q("a", "advanced")], modes=bad))
        assert n["modes"]["enabled"] is False and n["modes"]["force"] == ""


def test_modes_kulcsok_szerzodese():
    """A widget ezekre a kulcsokra szamit - mindig mind ott van."""
    kell = {"enabled", "force", "title", "basic_label", "basic_sub",
            "adv_label", "adv_sub", "switch_label"}
    for cfg in ({}, _cfg([]), _cfg([_q("a", "advanced")], modes={"enabled": True})):
        assert kell == set(kc.normalize_ruleset(cfg)["modes"])


# --------------------------------------------------------------------------- #
# a tolcser mod szerinti bontasa
# --------------------------------------------------------------------------- #
def _mrows(*triples):
    return list(triples)


def test_modes_bontas_ket_uttal():
    rows = _mrows(("basic", "kf_step", 100), ("basic", "kf_start", 90),
                  ("basic", "kf_done", 70), ("basic", "kf_lead", 7),
                  ("advanced", "kf_step", 40), ("advanced", "kf_start", 38),
                  ("advanced", "kf_done", 20), ("advanced", "kf_lead", 4))
    out = ks.modes(rows)
    assert [r["mode"] for r in out] == ["basic", "advanced"]
    b, a = out
    assert b["shown"] == 100 and b["done"] == 70 and b["done_pct"] == 77.8
    assert a["done_pct"] == 52.6 and a["lead_pct"] == 20.0
    assert b["label"] and a["label"]


def test_modes_bontas_ures_ha_nincs_mod():
    """Mod-valaszto nelkuli tenantnal a bontas SEMMIT nem mond -> ne mutassuk."""
    assert ks.modes([("", "kf_step", 10), ("", "kf_done", 5)]) == []
    assert ks.modes([]) == []
    assert ks.modes(None) == []


def test_modes_bontas_ismeretlen_modot_eldob():
    out = ks.modes([("expert", "kf_step", 9), ("basic", "kf_step", 3)])
    assert [r["mode"] for r in out] == ["basic"]


def test_modes_bontas_ismeretlen_kindet_eldob():
    out = ks.modes([("basic", "kf_valami", 99), ("basic", "kf_start", 4)])
    assert out[0]["start"] == 4 and out[0]["shown"] == 4


def test_modes_bontas_shown_legalabb_a_start():
    """Aki elkezdte, definicio szerint latta is (a kf/11a elve modonkent is)."""
    out = ks.modes([("basic", "kf_start", 12)])
    assert out[0]["shown"] == 12


def test_modes_bontas_nulla_nevezore_nem_esik_el():
    out = ks.modes([("basic", "kf_lead", 0), ("basic", "kf_done", 0)])
    assert out[0]["done_pct"] is None and out[0]["lead_pct"] is None


def test_modes_bontas_sorrend_fix():
    """Mindig egyszeru -> halado -> (mod nelkuli), fuggetlenul a sor-sorrendtol."""
    out = ks.modes([("", "kf_step", 1), ("advanced", "kf_step", 2), ("basic", "kf_step", 3)])
    assert [r["mode"] for r in out] == ["basic", "advanced", ""]


# --------------------------------------------------------------------------- #
# shape(): a mod-valaszto a tolcser UJ TETEJE
# --------------------------------------------------------------------------- #
def test_shape_mod_valaszto_a_teteje():
    """Aki a valasztonal lepett ki, sosem latott kerdest - eddig lathatatlan volt."""
    r = ks.shape([("kf_mode", 200, 200), ("kf_start", 50, 50), ("kf_done", 30, 30)],
                 step_rows=[("q1", "0", 60)], questions=[{"id": "q1", "title": "T"}])
    assert r["funnel"]["shown"] == 200        # nem 60 es nem 50
    assert r["mode_shown"] == 200
    assert r["rates"]["start"] == 25.0


def test_shape_mod_nelkul_valtozatlan():
    """REGRESSZIO: kf_mode adat nelkul minden szam ugyanaz, mint kf/17 elott."""
    r = ks.shape([("kf_start", 50, 50), ("kf_done", 30, 30)],
                 step_rows=[("q1", "0", 60)], questions=[{"id": "q1", "title": "T"}])
    assert r["funnel"]["shown"] == 60 and r["mode_shown"] == 0
    assert r["modes"] == []
    assert r["rates"]["start"] == 83.3


def test_shape_modes_atadva():
    r = ks.shape([("kf_start", 5, 5)],
                 mode_rows=[("basic", "kf_start", 3), ("advanced", "kf_start", 2)])
    assert [x["mode"] for x in r["modes"]] == ["basic", "advanced"]


def test_shape_mode_rows_opcionalis():
    """A hivo (config.py) regi alakja sem torhet el."""
    r = ks.shape([("kf_start", 1, 1)])
    assert r["modes"] == [] and r["mode_shown"] == 0


def test_kf_mode_a_kinds_kozott():
    assert "kf_mode" in ks.KINDS
    assert "kf_mode" in ks.SQL_FUNNEL
    assert "kf_mode" not in ks.SQL_MODES     # a bontas a kerdes-uti esemenyeket nezi


def test_sql_modes_alakja():
    q = ks.SQL_MODES
    assert ":cid" in q and ":days" in q and "meta->>'mode'" in q
    assert "count(DISTINCT session_id)" in q and "GROUP BY 1, 2" in q

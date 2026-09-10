"""m98: linkvalidate egysegtesztek.

A modul stdlib-only es PURE -> kozvetlen fajl-betoltes (a suite mas tesztjei
fake `app.services` csomagot hagynak a sys.modules-ben, app-import itt utkozne).
"""

import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "linkvalidate.py"
_spec = importlib.util.spec_from_file_location("lv_m98_test", _P)
lv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lv)

U12 = "https://kellegyszerszam.hu/termek/mtx-palack-emelo-12t"
U2 = "https://kellegyszerszam.hu/termek/mtx-palack-emelo-2t"
FAKE = "https://kellegyszerszam.hu/termek/DENZEL-1200W-15L-epitesi-szaraz-nedves-porszivo"
CTX = {U12: "MTX palack emelo 12T", U2: "MTX palack emelo 2T"}


def test_fabrikalt_link_torlodik_szoveg_marad():
    reply = "Ezt ajanlom: [DENZEL 1200W 15L epitesi porszivo](%s) - 45 990 Ft." % FAKE
    out, info = lv.apply_fixes(reply, CTX, {FAKE})
    assert info["removed"] == 1
    assert FAKE not in out
    assert "DENZEL 1200W 15L epitesi porszivo" in out
    assert "](" not in out


def test_letezo_link_erintetlen():
    reply = "Van keszleten: [MTX palack emelo 12T](%s)." % U12
    out, info = lv.apply_fixes(reply, CTX, set())
    assert out == reply
    assert info == {"removed": 0, "retargeted": 0, "num": 0}


def test_kereso_zarolink_erintetlen():
    su = "https://kellegyszerszam.hu/termek-kereses?k=aso"
    reply = "Nezd meg: [Tovabbi talalatok a webaruhazban](%s)" % su
    out, info = lv.apply_fixes(reply, CTX, {su})
    assert out == reply
    assert info["removed"] == 0


def test_mutato_anchor_erintetlen():
    reply = "A [termekoldalt](%s) itt talalod." % FAKE
    out, info = lv.apply_fixes(reply, CTX, {FAKE})
    assert out == reply
    assert info["removed"] == 0


def test_retarget_pontos_nevegyezesnel():
    reply = "Ajanlom: [MTX palack emelo 2T](%s)." % U12
    out, info = lv.apply_fixes(reply, CTX, set())
    assert info["retargeted"] == 1
    assert U2 in out and U12 not in out


def test_irasmod_elteres_nem_valt_urlt():
    ctx = {U12: "Import 550 x 1100 mm Sittes zsak normal"}
    reply = "Ez az: [Import 550x1100 mm sitteszsak](%s)." % U12
    out, info = lv.apply_fixes(reply, ctx, set())
    assert out == reply
    assert info["retargeted"] == 0


def test_lookup_candidates_csak_termek_alaku_ismeretlen_url():
    reply = (
        "Az [ASZF letoltes](https://kellegyszerszam.hu/shop_help.php?tab=terms) itt, "
        "a termek pedig [DENZEL 1200W 15L epitesi porszivo](%s), "
        "es [MTX palack emelo 12T](%s)." % (FAKE, U12)
    )
    cand = lv.lookup_candidates(reply, set(CTX))
    assert cand == [FAKE]


def test_ures_kontextus_fail_safe():
    reply = "[Barmi termek nev](%s)" % FAKE
    assert lv.lookup_candidates(reply, set()) == []


def test_zaro_slash_es_fragment_egybeesik():
    reply = "[MTX palack emelo 12T](%s/#tab)" % U12
    out, info = lv.apply_fixes(reply, CTX, set())
    assert out == reply
    assert info == {"removed": 0, "retargeted": 0, "num": 0}


def test_html_entitas_a_nevben_nem_okoz_cserét():
    ctx = {U12: "YATO Lancfuresz lancvezeto 15&quot; 0,325"}
    reply = 'Ez az: [YATO Lancfuresz lancvezeto 15" 0,325](%s).' % U12
    out, info = lv.apply_fixes(reply, ctx, set())
    assert out == reply
    assert info["retargeted"] == 0


# ---------------------------------------------------------------- m98/1
def test_r1_platform_kapu():
    assert lv.r1_enabled("unas") and lv.r1_enabled(" Unas ")
    for p in ("shoprenter", "webdoc", "woocommerce", "sellvio", "kontur", "", None):
        assert not lv.r1_enabled(p)


def test_koveto_parameter_lekerul_mas_query_marad():
    u = "https://nagyonallatshop.hu/termek/oke-duo-krok-20kg/?gad_source=1&gad_campaignid=23&gclid=Cj0K"
    assert lv.url_key(u) == "https://nagyonallatshop.hu/termek/oke-duo-krok-20kg"
    s = "https://s.hu/index.php?route=product/product&product_id=5&utm_source=g"
    assert lv.url_key(s) == "https://s.hu/index.php?route=product/product&product_id=5"


def test_koveto_parameteres_ctx_link_nem_lookup_jelolt():
    reply = "[MTX palack emelo 12T](%s?gad_source=1&gclid=x)" % U12
    assert lv.lookup_candidates(reply, set(CTX)) == []
    out, info = lv.apply_fixes(reply, CTX, set())
    assert out == reply and info["removed"] == 0


def test_unas_es_woo_kereso_link_erintetlen():
    su = "https://www.kellegyszerszam.hu/shop_search.php?search=aut%C3%B3+emel%C5%91"
    sw = "https://nagyonallatshop.hu/?post_type=product&s=kutyaeledel"
    reply = "[MTX palack emelo talalatok](%s) es [Kutyaeledel ajanlatok 20kg](%s)" % (su, sw)
    assert lv.lookup_candidates(reply, set(CTX)) == []
    out, info = lv.apply_fixes(reply, CTX, {su, sw})
    assert out == reply and info["removed"] == 0


def test_szabalyzat_anchor_erintetlen():
    w = "https://copygo.hu/withdrawal"
    for a in ("Elállási nyilatkozat kitöltése", "Adatvédelmi szabályzat", "Jótállás bejelentése"):
        reply = "[%s](%s)" % (a, w)
        out, info = lv.apply_fixes(reply, CTX, {w})
        assert out == reply and info["removed"] == 0


S12 = "https://kellegyszerszam.hu/termek/stels-12t"
S2 = "https://kellegyszerszam.hu/termek/stels-2t"
SCTX = {S12: "STELS 12T 230-465mm hidraulikus palack emelő",
        S2: "STELS 2T tartomány 181-345 mm hidraulikus palack emelő"}


def test_r2b_szamtoken_elteres_csere():
    reply = "Ajánlom: [STELS 2T 181-345mm hidraulikus palack emelő](%s) - 9 990 Ft" % S12
    out, info = lv.apply_fixes(reply, SCTX, set())
    assert info == {"removed": 0, "retargeted": 0, "num": 1}
    assert S2 in out and S12 not in out


def test_r2b_stimmelo_szamtoken_erintetlen():
    reply = "[STELS 12T hidraulikus palack emelő](%s)" % S12
    out, info = lv.apply_fixes(reply, SCTX, set())
    assert out == reply and info["num"] == 0


def test_r2b_betus_elteres_nincs_csere():
    a = "https://kellegyszerszam.hu/termek/yato-lancvezeto-15"
    b = "https://kellegyszerszam.hu/termek/yato-lancvezeto-lemez-feszito"
    ctx = {a: "YATO Láncfűrész láncvezető 15&quot; 0,325&quot;", b: "YATO Láncvezető lemez feszítő"}
    reply = "[YATO vezetőlemez](%s)" % a
    out, info = lv.apply_fixes(reply, ctx, set())
    assert out == reply and info["num"] == 0


def test_r2b_kod_elotag_nem_illeszkedik():
    a = "https://notebookstore.hu/asus-vivobook-15-bq1105-p1"
    b = "https://notebookstore.hu/asus-vivobook-15-bq1105w-p2"
    ctx = {a: "Asus Vivobook 15 Notebook (X1504VA-BQ1105) - 15.6 FHD",
           b: "Asus VivoBook 15 Notebook (X1504VA-BQ1105W)"}
    reply = "[Asus Vivobook 15 (X1504VA-BQ1105)](%s)" % a
    out, info = lv.apply_fixes(reply, ctx, set())
    assert out == reply and info == {"removed": 0, "retargeted": 0, "num": 0}


def test_r2b_tobbertelmu_nincs_csere():
    l_ = "https://kellegyszerszam.hu/termek/festa-12-38"
    a1 = "https://kellegyszerszam.hu/termek/festa-14-38-a"
    a2 = "https://kellegyszerszam.hu/termek/festa-14-38-b"
    ctx = {l_: "FESTA 1/2-3/8 dugókulcs átalakító adapter",
           a1: "FESTA 1/4-3/8 dugókulcs adapter", a2: "FESTA 1/4-3/8 adapter króm"}
    reply = "[FESTA 1/4-3/8 adapter](%s)" % l_
    out, info = lv.apply_fixes(reply, ctx, set())
    assert out == reply and info["num"] == 0


def test_r2b_szamsorrend_szamit():
    l_ = "https://kellegyszerszam.hu/termek/festa-12-38"
    r_ = "https://kellegyszerszam.hu/termek/festa-38-14"
    ctx = {l_: "FESTA 1/2-3/8 dugókulcs átalakító adapter", r_: "FESTA 3/8-1/4 dugókulcs adapter"}
    reply = "[FESTA 1/4-3/8 adapter](%s)" % l_
    out, info = lv.apply_fixes(reply, ctx, set())
    assert out == reply and info["num"] == 0

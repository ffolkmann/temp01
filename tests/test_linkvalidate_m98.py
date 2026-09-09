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
    assert info == {"removed": 0, "retargeted": 0}


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
    assert info == {"removed": 0, "retargeted": 0}


def test_html_entitas_a_nevben_nem_okoz_cserét():
    ctx = {U12: "YATO Lancfuresz lancvezeto 15&quot; 0,325"}
    reply = 'Ez az: [YATO Lancfuresz lancvezeto 15" 0,325](%s).' % U12
    out, info = lv.apply_fixes(reply, ctx, set())
    assert out == reply
    assert info["retargeted"] == 0

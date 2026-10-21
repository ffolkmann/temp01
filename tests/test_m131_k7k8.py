"""m131 (K7 + K8): greetguard prior_db + bemutatkozas-levagas; speechguard beszedmod-orseg.

Stdlib-only modulok, fajl-betoltessel (minta: tests/test_m129_k5_parse.py).
"""

import importlib.util
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gg = _load("greetguard_m131", "app/services/greetguard.py")
sg = _load("speechguard_m131", "app/services/speechguard.py")

_H = [{"role": "user", "content": "elozo kerdes"}, {"role": "assistant", "content": "elozo valasz"}]
_E: list = []


# ---------------------------------------------------------------- K7: prior_db kapu

def test_k7_prior_db_nyitja_a_kaput():
    r = "Szia! 🙂 Ha gumiütközőt keresel, itt van néhány jó találat a webáruházból: ..."
    assert gg.strip_regreet(r, "Gumiutkozo", _E) == r                 # m102/1: ures history -> marad
    out = gg.strip_regreet(r, "Gumiutkozo", _E, prior_db=True)        # m131: DB-elozmeny -> levagas
    assert not out.startswith("Szia")
    assert "gumiütközőt keresel" in out


def test_k7_prior_db_de_latogato_koszont_marad():
    r = "Szia! 😊 Ponty Peti vagyok, a Fishingoutlet.hu online asszisztense. Miben segíthetek?"
    assert gg.strip_regreet(r, "Szia!", _E, prior_db=True) == r


def test_k7_bemutatkozas_levagva_koszones_utan():
    r = ("Szia! 😊 Én Ponty Peti vagyok, a Fishingoutlet.hu asszisztense, de örülök, hogy írtál! 🎣  "
         "A **Shimano Aero X7** botot most nem látom a webáruházban elérhető termékek között.")
    out = gg.strip_regreet(r, "vagy hozzá hasonlot mit tudnál ?", _E, prior_db=True)
    assert "Ponty Peti" not in out and "Szia" not in out
    assert out.lstrip("🎣 ").startswith("A **Shimano Aero X7**")


def test_k7_bemutatkozas_koszones_nelkul_is():
    r = "Sanyi vagyok, a Kellegyszerszam Webáruház online asszisztense. A csavarbehajtó raktáron van."
    out = gg.strip_regreet(r, "van raktaron?", _H)
    assert out == "A csavarbehajtó raktáron van."


def test_k7_identitas_kerdesre_a_bemutatkozas_marad():
    r = "Szia! Én a Fishingoutlet.hu webáruház chat-asszisztense vagyok, Ponty Peti – nem ismerek senkit."
    out = gg.strip_regreet(r, "ki vagy te, robot?", _H)
    assert "Ponty Peti" in out
    r2 = "Nem egészen: az ügyfélszolgálatunk 8–16 között van. Én a CopyGo Segéd vagyok, a webáruház chat-asszisztense."
    assert gg.strip_regreet(r2, "VAN ITT ÉLŐ ÜGYFÉLSZOLGÁLATOS??", _H) == r2


def test_k7_rovid_maradek_valtozatlan():
    r = "Szia! Sanyi vagyok, a bolt asszisztense. Igen."
    assert gg.strip_regreet(r, "Hez", _H) == r


def test_k7_nem_bemutatkozas_mondat_marad():
    r = "Biztos vagyok benne, hogy ez a termék jó választás. Raktáron van."
    assert gg.strip_regreet(r, "jo lesz ez?", _H) == r
    r2 = "Abban viszont igazi profi vagyok, hogy botot ajánljak. Nézd meg ezt."
    assert gg.strip_regreet(r2, "ronaldo vagy messi", _H) == r2


def test_k7_hibas_bemenet_fail_safe():
    assert gg.strip_regreet(None, None, None, prior_db=True) == ""
    assert gg.strip_regreet("Szia! Ok.", "x", object(), prior_db=True) == "Szia! Ok."


# ---------------------------------------------------------------- K8: speechguard

def test_k8_talalataim_torles_ha_van_hely_a_mondatban():
    r = "Sajnos most nem látok a webáruházban olyan lézernyomtatót a találataim között, amivel pontos árat tudnék mondani."
    out, n = sg.rewrite(r)
    assert n == 1
    assert out == "Sajnos most nem látok a webáruházban olyan lézernyomtatót, amivel pontos árat tudnék mondani."


def test_k8_talalataim_csere_kinalatra_ha_nincs_hely():
    r = "Sajnos a jelenlegi találataim között nincs ilyen paraméterű, raktáron lévő pergető bot – mindkettő 5 g felett indul."
    out, n = sg.rewrite(r)
    assert n == 1 and out.startswith("Sajnos a kínálatban nincs ilyen paraméterű")


def test_k8_mondatkezdo_nagybetu():
    r = "A jelenlegi találataim között nincs ilyen. Nézd meg a keresőben."
    out, n = sg.rewrite(r)
    assert n == 1 and out.startswith("A kínálatban nincs ilyen.")


def test_k8_rendelkezesemre_allo_alapjan_torles():
    r = "Ezt nem tudom biztosan megmondani a rendelkezésemre álló információk alapján, ezért nem tudom megerősíteni."
    out, n = sg.rewrite(r)
    assert n == 1 and out == "Ezt nem tudom biztosan megmondani, ezért nem tudom megerősíteni."


def test_k8_rendelkezesemre_allo_termekek_kozott():
    r = "Szia! 😊 A **Whiplash** kifejezésre most nem találok pontos egyezést a rendelkezésemre álló termékek között. Ha egy konkrét zsinórra gondolsz, írd meg."
    out, n = sg.rewrite(r)
    assert n == 1 and "nem találok pontos egyezést a kínálatban." in out


def test_k8_keresesem_alapjan_es_kapott_adatok():
    r = "A webáruházban most nem látok ilyen néven terméket a keresésem alapján, ezért a garanciaidőt sem tudom megmondani."
    out, n = sg.rewrite(r)
    assert n == 1 and "a keresésem" not in out and "nem látok ilyen néven terméket, ezért" in out
    r2 = "A konkrét forintösszeg nincs feltüntetve a kapott adatok között. A pontos felárat a [termék oldalán](https://x.y/a) látod."
    out2, n2 = sg.rewrite(r2)
    assert n2 == 1 and out2.startswith("A konkrét forintösszeg nincs feltüntetve.") and "[termék oldalán](https://x.y/a)" in out2


def test_k8_listaelem_es_tobb_fordulat():
    r = "- **Frontline spray** – ilyen terméket nem látok a jelenlegi találataim között.\n- **Whiskas** – erről sincs adatom a rendelkezésemre álló adatok között."
    out, n = sg.rewrite(r)
    assert n == 2
    assert "találataim" not in out and "rendelkezésemre" not in out
    assert "nem látok a kínálatban." in out and "sincs adatom." in out


def test_k8_nem_nyul_a_jogos_mondatokhoz():
    for r in (
        "A találatok között van három bot is. A webáruház keresője alapján ez a legjobb.",
        "Írd meg kérdésed kontextusát (pl. melyik megoldásunkról van szó).",
        "A webáruházban most nem látok ilyet, de a keresőben érdemes megnézni.",
        "A rendelkezésedre álló adatok alapján döntsd el.",
    ):
        out, n = sg.rewrite(r)
        assert n == 0 and out == r


def test_k8_link_szoveg_erintetlen():
    r = "Nem látom a találataim között, nézd meg itt: [a találataim között](https://x.y/kereses?keyword=a+talalataim+kozott)."
    out, n = sg.rewrite(r)
    assert n == 1
    assert "[a találataim között](https://x.y/kereses?keyword=a+talalataim+kozott)" in out


def test_k8_behuzott_lista_erintetlen():
    r = "Lista:\n- egy\n  - alpont  (két szóköz)\nNem látom a találataim között."
    out, n = sg.rewrite(r)
    assert n == 1 and "\n  - alpont  (két szóköz)\n" in out and out.endswith("Nem látom a kínálatban.")


def test_k8_ajanlataim_kozott_m131b():
    # elo E2E lelet (d21h, fishingoutlet): "nem latok a webaruhazban az ajanlataim kozott"
    r = "Szia! 🎣 Kis szákot most nem látok a webáruházban az ajánlataim között, de ez nem jelenti azt, hogy nincs."
    out, n = sg.rewrite(r)
    assert n == 1 and "ajánlataim" not in out and "nem látok a webáruházban, de" in out


def test_k8_fail_safe():
    assert sg.rewrite(None) == ("", 0)
    assert sg.rewrite("") == ("", 0)


# ---------------------------------------------------------------- chat.py bekotes

def test_chat_py_bekotes():
    src = open(os.path.join(_ROOT, "app/api/chat.py"), encoding="utf-8").read()
    i = src.index("_prior131")
    assert src.index("la_state = await get_session_state") > i   # a keres elejen, minden ag elott
    j = src.index("_srg102(parsed.reply, message, req.history, prior_db=_prior131)")
    assert j > i
    k = src.index("from app.services.speechguard import rewrite as _sg131")
    assert k > j
    assert src.index("m89: ZARO-LINK KAPU") > k                   # a zaro-link kapuk elott fut

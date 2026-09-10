"""m102/2: bot-nev a statikus promptban (G3) + beszedmod: a sajat mukodes ne keruljon a valaszba (G4).
Fajlbol toltve, fake app.* modulokkal (a test_prompt_parts_m68 mintajara)."""

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]

_app_snapshot = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
for _k in list(_app_snapshot):
    del sys.modules[_k]


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    m.__path__ = []
    sys.modules[name] = m
    return m


for _name in ("app", "app.core", "app.services", "app.models"):
    _mod(_name)
_mod("app.models.db_models", Coupon=type("Coupon", (), {}), Tenant=type("Tenant", (), {}))
_mod("app.services.current_product", CurrentProduct=type("CurrentProduct", (), {}))
_mod("app.services.handoff_offer", prompt_block=lambda: "")
_FAKT = "\n\n# TENYEK FAKE"
_mod("app.services.factuality", factuality_block=lambda: _FAKT)
_mod("app.services.live_product", LivePriceStock=type("LivePriceStock", (), {}))
spec = importlib.util.spec_from_file_location("prompt_m102n2_under_test", ROOT / "app" / "services" / "prompt.py")
_prompt = importlib.util.module_from_spec(spec)
sys.modules["prompt_m102n2_under_test"] = _prompt
spec.loader.exec_module(_prompt)
for _k in [x for x in list(sys.modules) if x == "app" or x.startswith("app.")]:
    del sys.modules[_k]
sys.modules.update(_app_snapshot)

_fs = importlib.util.spec_from_file_location("factuality_m102n2", ROOT / "app" / "services" / "factuality.py")
_fact = importlib.util.module_from_spec(_fs)
_fs.loader.exec_module(_fact)


def _tenant(**kw):
    base = dict(system_prompt="Te vagy a bolt asszisztense.", platform="unas",
                public_url="https://bolt.hu", elallas_url="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _ctx():
    return _prompt.PromptContext(page_is_product=False, page_product_name="", page_url="", page_url_norm="")


def test_nev_blokk_szemelynevvel():
    b = _prompt._name_block(_tenant(bot_name="Sanyi"))
    assert "# A NEVED" in b and '"Sanyi"' in b and "SOHA ne mondd, hogy nincs neved" in b


def test_nev_blokk_a_statikus_reszben_es_tenantonkent_allando():
    t = _tenant(bot_name="Ponty Peti")
    s1, d1 = _prompt.build_system_prompt_parts(t, [], None, [], _ctx())
    s2, d2 = _prompt.build_system_prompt_parts(t, [], None, [], _ctx(), operator_online=True)
    assert s1 == s2 == "Te vagy a bolt asszisztense." + _FAKT + _prompt._name_block(t)
    assert "# A NEVED" not in d1


def test_nincs_nev_blokk_url_vagy_ures_nevnel():
    for nm in (None, "", "   ", "https://smartzilla.hu/", "cegalkusz.hu", "www.bolt.hu", "x" * 60):
        assert _prompt._name_block(_tenant(bot_name=nm)) == "", nm
    assert _prompt._name_block(types.SimpleNamespace()) == ""


def test_asszisztens_tipusu_nev_is_bekerul():
    assert '"Copygo asszisztens"' in _prompt._name_block(_tenant(bot_name="Copygo asszisztens"))


def test_factuality_nem_irja_elo_a_sajat_keresest():
    b = _fact.factuality_block()
    assert "keresesedben" not in b
    assert "a webaruhazban most nem latsz ilyet" in b
    assert "BESZEDMOD" in b and "a talalataim kozott" in b
    assert "NEM bizonyitek" in b and "adatbazisodra" in b  # m33 regi szabalyok maradnak
    assert not (set(b) & set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ"))


def test_m63_keszlet_mondat_nem_talalatokrol_beszel():
    s = _prompt._M63_STOCK_FIRST
    assert "tal\u00e1latok k\u00f6z\u00f6tt most nincs ilyen" not in s
    assert "a web\u00e1ruh\u00e1zban most nem l\u00e1tsz rakt\u00e1ron l\u00e9v\u0151 ilyen term\u00e9ket" in s

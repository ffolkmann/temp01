"""m89/1: a bolti-keresos (m25 / shop_hits) ag kontextus-felulirasa.

Kulon fajl, hogy a parhuzamos szalak test_linkgate_m89.py-ja erintetlen maradjon.
Fajl-betoltos import: a suite mas tesztjei fake app.services-t hagynak a
sys.modules-ben (kf/13 tanulsag).
"""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "linkgate.py"
_SPEC = importlib.util.spec_from_file_location("linkgate_m89n1", _P)
lg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lg)


def test_ures_kontextus_alapbol_blokkol():
    """A m62 ag viselkedese VALTOZATLAN: nincs talalat -> nincs link."""
    ok, why = lg.should_offer_link("Macskaalmot keresek", [], False)
    assert ok is False
    assert "kontextus" in why


def test_bolti_talalat_feluluirja_a_kontextus_kaput():
    """m89/1: a bolt sajat keresoje talalt -> a link kimehet ures Qdrant-pool mellett is."""
    ok, why = lg.should_offer_link("Macskaalmot keresek", [], False, has_products=True)
    assert ok is True
    assert why == "ok"


def test_kerdes_oldali_hard_stopok_a_bolti_agon_is_elnek():
    """A felulira CSAK a kontextus-kaput nyitja ki, a szandek-kapukat NEM."""
    assert lg.should_offer_link("Milyen fizetesi modok vannak?", None, True,
                                has_products=True)[0] is False
    assert lg.should_offer_link("Szia", None, False, has_products=True)[0] is False
    assert lg.should_offer_link("A rendelesem utan erdeklodom", None, False,
                                has_products=True)[0] is False
    assert lg.should_offer_link("Nyitvatartasi ido uzletben mettol meddig van?", None,
                                False, has_products=True)[0] is False


def test_has_products_false_blokkol_akkor_is_ha_van_hit():
    """Explicit False -> blokk, meg ha a hits-ben van is termek (fail-safe irany)."""
    hits = [{"payload": {"type": "product", "name": "x"}}]
    ok, _ = lg.should_offer_link("Macskaalmot keresek", hits, False, has_products=False)
    assert ok is False


def test_none_eseten_a_regi_ut_fut():
    """has_products=None -> a hits-bol dolgozik (visszafele kompatibilis)."""
    hits = [{"payload": {"type": "product", "name": "x"}}]
    assert lg.should_offer_link("Macskaalmot keresek", hits, False)[0] is True
    assert lg.should_offer_link("Macskaalmot keresek", hits, False, None)[0] is True

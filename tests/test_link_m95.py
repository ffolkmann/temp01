"""m95: zaro kereso-link — info-/ugymenet-stopok + term-levezethetoseg.

File-load import (a suite mas tesztjei fake app.services-t hagynak a
sys.modules-ben, ld. kf13 tanulsag) — mindket modul stdlib-only.
"""
import importlib.util
import pathlib

_BASE = pathlib.Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, str(_BASE / fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lg = _load("lg_m95", "linkgate.py")
lt = _load("lt_m95", "linkterm.py")


def test_inforeq_cuts_measured_cases():
    # a valodi korpuszbol mert esetek (d26d_m95sweep) — mind ugymeneti
    cases = [
        u"Szia! Magyar Áfás számlát tudtok adni Fossibot erőműről?",
        u"Szeretnék használati utasítást,működési leírást kérni a jelgenerátorhoz.",
        u"Szia! Hol van helyileg a ceg?",
        u"Ha ma rendelem ,mikor kapom meg a terméket)",
        u"Hogyan tudom rendelni márba kosárban van",
        u"Csak MPL?",
        u"es mikor erkezik meg?",
        u"Ha ma megrendelem holnap feladják?",
        u"Azt szeretném kérdezni, hogy céges számlát tudok-e kérni?",
        u"gls csomopőntra teheto vagy automaqttaba  a damil fej",
    ]
    hits = [{"payload": {"type": "product", "name": "X"}}]
    for q in cases:
        assert lg.non_product_intent(q), q
        ok, _why = lg.should_offer_link(q, hits, False)
        assert ok is False, q


def test_product_questions_keep_link():
    hits = [{"payload": {"type": "product", "name": u"INGCO ütvefúró"}}]
    keep = [
        u"Előketartót keresek",
        u"Macskaalmot keresek",
        u"Windows 11-es laptopot keresek",
        u"szeretnék rendelni egy fúrót",
        u"pontybölcsőt szeretnék venni, de személyesen akarom megvenni",
        u"GA605WI",
        u"12x200 vagy 12x220 mm -es",
    ]
    for q in keep:
        assert not lg.non_product_intent(q), q
        ok, _why = lg.should_offer_link(q, hits, False)
        assert ok is True, q


def test_linkterm_context_rejects_pool_noise():
    names = [u"FNIRSI forrasztópáka X1", u"AiXun forrasztópáka T3A",
             u"FNIRSI forrasztópáka mini", u"FNIRSI forrasztópáka pro"]
    msg = u"Szeretnék használati utasítást kérni a jelgenerátorhoz."
    # context nelkul (regi viselkedes): a nev-alapu term nyer
    assert "forraszt" in lt._fold(lt.link_search_term(msg, names))
    # contexttel: a pool-zaj kiesik
    t = lt.link_search_term(msg, names, context=msg)
    assert "forraszt" not in lt._fold(t)


def test_linkterm_context_keeps_history_term():
    names = [u"INGCO szeg 3,5 mm", u"INGCO szeg 2,8 mm", u"INGCO szeg készlet"]
    msg = u"3.5mm szeretnek"
    ctx = msg + u" milyen szeget ajanlasz szegbelovohoz"
    t = lt.link_search_term(msg, names, [u"INGCO"], context=ctx)
    assert "szeg" in lt._fold(t)


def test_linkterm_empty_topic_gives_empty_term():
    # udvarias frazis: nincs kerdes-alapu topic -> ures term (a hivo nem linkel)
    assert lt.link_search_term(u"Köszönöm!", [u"AnyCubic gyanta"],
                               context=u"Köszönöm!") == ""


def test_linkterm_backward_compat_three_args():
    # context nelkul bitre a regi viselkedes
    assert lt.link_search_term(u"sátrat keresek", [u"Delphin sátor zöld",
                               u"Delphin sátor kék"]) != ""

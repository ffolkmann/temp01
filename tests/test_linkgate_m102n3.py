"""m102/3: identitas-/meta-kerdes alatt nincs zaro kereso-link (linkgate.meta_topic).

Fajl-betoltos import (spec_from_file_location), mert a suite mas tesztjei fake
app.services-t hagynak a sys.modules-ben.
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "linkgate.py"
_spec = importlib.util.spec_from_file_location("linkgate_m102n3", _p)
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)


# --- a botnak szolo kerdes: VAGNI (valodi korpusz + E2E esetek) -------------
def test_meta_valodi_kerdesek():
    for m in ("Miért nem Zolinak hívnak?", "Te vagy az Sanyi?", "Mesterseges inteligencia vagy?",
              "jó béna robot vagy", "hülye neved van",
              "Így hogyan akarsz segíteni a vásárlásban? Te vagy az eladó, te még nem tudod mi található",
              "Hogy hívnak?", "Mi a neved?", "Szia Sanyi! Te vagy Sanyi?", "Te vagy Ponty Peti?",
              "Szia, ki vagy?", "ki vagy te?", "Robot vagy?", "Élő ember vagy?", "Te egy robot vagy?",
              "Kivel beszélek?", "buta vagy", "AI vagy?", "valódi ember vagy te?", "Gép vagy vagy ember?"):
        assert lg.meta_topic(m), m


# --- termek-kerdes: NEM szabad meta-kerdesnek venni (csapdak) ---------------
def test_meta_termek_kerdes_marad():
    for m in ("FIELDMANN HOLLY fém balkon szett FDZN 5300 milyen színű? Fekete vagy acélszürke?",
              "robot vagy kézi fűnyírót ajánlasz?", "Robotporszívó vagy kézi?", "Kézi vagy robot porszívót?",
              "buta vagy okostelefon kell a papának?", "ki vagy bekapcsolható a világítás?",
              "gey mackós alaku férfi ember vagyok zöld terméket keresek",
              "ha te vagy a helyemben melyiket vennéd?",
              "Hogy hívják azt a szerszámot, amivel csempét vágnak?",
              "Mesterséges intelligenciával működő robotporszívó van?", "A gép vagy a kábel hibás?",
              "ember vagy állat eledel?", "Bosch fúró", "Melyik jobb, a piros vagy a kék?",
              "Delphin sátrat keresek", "akciós notebook"):
        assert not lg.meta_topic(m), m


# --- a meta-kerdes tartalmas szonak szamit, tehat a regi kapu atengedte ----
def test_regi_kapu_atengedte_ezert_kell_az_uj():
    prod = [{"payload": {"type": "product", "name": "Bosch fúró", "url": "https://x.hu/termek/b-1"}}]
    for m in ("Hogy hívnak?", "Te vagy az Sanyi?", "jó béna robot vagy"):
        ok, _ = lg.should_offer_link(m, prod, False)
        assert ok and lg.meta_topic(m) and not lg.shop_topic(m), m


def test_meta_hibatur():
    assert lg.meta_topic(None) is False
    assert lg.meta_topic("") is False

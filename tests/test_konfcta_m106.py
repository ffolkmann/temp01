"""m106: CX Konfigurator-felajanlas a chatben (konfcta.detect / cta_cfg / same_page).

Fajl-betoltos import (spec_from_file_location), mert a suite mas tesztjei fake
app.services-t hagynak a sys.modules-ben. Az esetek a d21a copygo-korpuszbol
(30 nap) es a kontroll-kerdesekbol jonnek.
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konfcta.py"
_spec = importlib.util.spec_from_file_location("konfcta_m106", _p)
kc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kc)

URL = "https://copygo.hu/nyomtato-konfigurator?source=chatbot"


def test_valasztas_bizonytalansag_felajanl():
    for m in ("nyomtatót keresek",
              "Milyen nyomtatót vegyek otthonra? Főleg dokumentumot nyomtatnék, havonta 50 oldalt.",
              "Nem tudom eldönteni, lézer vagy tintasugaras nyomtató legyen",
              "Epson wifis nyomtatót keresnék olcsót!", "melyik a legolcsóbb lézer nyomtató?",
              "hp nyomtató közül melyik a legjobb a4 nyomtatásra", "Multifunkciós nyomtatót szeretnék venni",
              "Ajánlanál egy nyomtatót irodába?", "színes nyomtató kellene otthonra",
              "Melyik jobb: Epson L3270 vagy Canon G3470 nyomtató?", "max 100e ft-os nyomtató kellene"):
        assert kc.detect(m), m


def test_kifejezett_rakerdezes():
    for m in ("van nyomtató konfigurátorotok?", "miért nem ajánlod a nyomtató konfigurátort?",
              "hol a nyomtató-választó?"):
        assert kc.detect(m), m


def test_kellek_szerviz_konkret_termek_nem():
    for m in ("Milyen toner kell a HP LaserJet M234sdn nyomtatómhoz? Van raktáron?",
              "Szeretnék érdrklődni , hogy a Polpos mp80 nyugta nyomtató jelenleg elérhető",
              "HP Laser Jet Pro MFP28a nyomtatóhoz szeretnék utángyártott tonert vásárolni",
              "Elromlott a nyomtatóm, javítjátok?", "nem nyomtat a nyomtatóm",
              "milyen patron kell az Epson XP-2100 nyomtatóba", "Mennyi a garancia a nyomtatókra?",
              "Hogyan telepítsem a nyomtató drivert?", "milyen papírt ajánlasz a nyomtatóhoz",
              "Epson L3270 nyomtatót keresek", "HP LaserJet M234sdn nyomtató kellene",
              "Mennyi a szállítási díj?", "Hol tart a rendelésem?", "otthonra kellene egy laptop", ""):
        assert not kc.detect(m), m


def test_konkret_termekre_visszautal_nem():
    # d21a korpusz: a bot altal mutatott termekrol kerdez
    assert not kc.detect("ez tud színesben nyomtatni?", ["hp nyomtató közül melyik a legjobb a4 nyomtatásra"])
    assert not kc.detect("az első nyomtató otthonra is jó?", ["nyomtatót keresek"])
    assert not kc.detect("ennek mennyi a havi oldalkapacitása?", ["nyomtatót keresek"])
    assert not kc.detect("szeretnék színesben nyomtatni")


def test_kovetkezo_kor_igeny_leiras():
    assert kc.detect("otthonra, színes kellene, havi 100 oldal", ["nyomtatót keresek"])
    assert not kc.detect("otthonra, színes kellene", ["milyen toner kell a nyomtatómhoz"])
    assert not kc.detect("otthonra, színes kellene", [])
    # csak az utolso ket korabbi uzenet szamit
    assert not kc.detect("havi 100 oldal", ["nyomtatót keresek", "köszi", "és a szállítás?"])


def test_cta_cfg():
    c = kc.cta_cfg({"chat_cta": {"enabled": True, "url": URL}})
    assert c["url"] == URL and c["label"] == kc.DEFAULT_LABEL
    assert kc.cta_cfg({"chat_cta": {"enabled": True, "url": URL, "label": "  Indítás  "}})["label"] == "Indítás"
    assert kc.cta_cfg({"chat_cta": {"enabled": False, "url": URL}}) is None
    assert kc.cta_cfg({"chat_cta": {"enabled": True, "url": "javascript:alert(1)"}}) is None
    assert kc.cta_cfg({"questions": []}) is None
    assert kc.cta_cfg(None) is None


def test_same_page():
    assert kc.same_page("https://www.copygo.hu/nyomtato-konfigurator/?source=homepage_banner", URL)
    assert not kc.same_page("https://copygo.hu/", URL)
    assert not kc.same_page("", URL)


def test_sajat_fonevek():
    assert not kc.detect("robotporszívót keresek")
    assert kc.detect("robotporszívót keresek", nouns=["robotporszivo\\w*"])
    assert not kc.detect("robotporszívót keresek", nouns=["(hibas"])  # hibas regex -> alap szotar

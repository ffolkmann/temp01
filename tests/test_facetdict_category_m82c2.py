"""m82c/2: KATEGORIA-SZANDEK a kerdesbol (facetdict.detect_category).

A facets-szures kapuja eddig a TALALATOK top-kategoriaja volt ("hova estek a
talalatok"), helyesen viszont "mit kerdezett". Elo eset: a "legolcsobb gamer
ASZTALI szamitogep" poolja notebook-dominans -> a kapu notebookra allt be, es
a 6 gamer asztali gep sosem jutott be.

Fajl-betoltes (stdlib-only modul), mint a m82b/m82c-nel. Minden minta ekezet
NELKUL: a _fold() amugy is ekezettelenit, az ekezetes utat az eles sweep
(tools/m82c2_catsweep.py) es az onboarding meri.
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fd = _load("facetdict_m82c2_under_test", "app/services/facetdict.py")

CAT_NB = "Laptop, Notebook > UJ Notebook"
CAT_PC = "Asztali PC, AiO, Konzol > Asztali szamitogep"
CAT_MON = "Monitor, Projektor, TV > Monitor"
CAT_MONSZ = "Kiegeszitok > Monitorszuro"
CAT_TONER = "Nyomtato > Tintapatron, toner"
CAT_TASKA = "Kiegeszitok > Notebook taska, hatizsak"
CAT_EGYEB = "Hasznalt > Egyeb"

CATALOG = [CAT_NB, CAT_PC, CAT_MON, CAT_MONSZ, CAT_TONER, CAT_TASKA, CAT_EGYEB]

# a terkepben CSAK a notebook es az asztali kategoria letezik (mint elesben a
# 85 crawl-olt kategoria: a Qdrant 100 kategoriajanak reszhalmaza)
FMAP = {
    "client_id": "t",
    "categories": {
        "uj-notebook": {
            "url": "/laptop-notebook/uj-notebook-c100",
            "facets": {
                "felhasznalas-jellege": {
                    "otthoni": 410, "uzleti": 644, "gamer": 157,
                    "grafikus": 59, "atalakithato": 54,
                },
                "memoria-meret": {"8gb": 98, "16gb": 579, "32gb": 211},
            },
        },
        "asztali-szamitogep": {
            "url": "/asztali-pc-aio-konzol/asztali-szamitogep-c110",
            "facets": {
                "felhasznalas-jellege": {"irodai-otthoni": 234, "gamer": 6},
                "memoria-meret": {"16gb": 300, "32gb": 40},
            },
        },
    },
}
NB = [CAT_NB] * 5


def test_kategoria_szandek_a_kerdesbol_m82c2():
    assert _fd.detect_category("Melyik a legolcsobb gamer asztali szamitogep?", CATALOG) == CAT_PC
    assert _fd.detect_category("legolcsobb 4K monitor", CATALOG) == CAT_MON
    assert _fd.detect_category("legolcsobb notebook taska", CATALOG) == CAT_TASKA


def test_ragozott_kategorianev_is_talalat_m82c2():
    assert _fd.detect_category("asztali szamitogepet keresek olcson", CATALOG) == CAT_PC
    assert _fd.detect_category("olcso monitort keresek", CATALOG) == CAT_MON


def test_nem_csuszik_at_masik_kategoriaba_m82c2():
    # 'monitorszuro' nem 'monitor': 5+ karakter ratoldva mar nem ragozas
    assert _fd.detect_category("legolcsobb monitorszuro", CATALOG) == CAT_MONSZ


def test_nincs_kategorianev_a_kerdesben_m82c2():
    for q in (
        "legolcsobb gamer laptop",
        "Melyik a legolcsobb 17 colos laptop?",
        "mennyibe kerul a szallitas?",
        "van ra 3 ev garancia?",
    ):
        assert _fd.detect_category(q, CATALOG) == "", q


def test_toltelek_kategorianev_kimarad_m82c2():
    assert _fd.detect_category("egyeb kerdesem lenne", CATALOG) == ""


def test_tobbertelmu_kategoria_kimarad_m82c2():
    amb = ["A > Tablet", "B > Tablet"]
    assert _fd.detect_category("legolcsobb tablet", amb) == ""


def test_cimke_a_kerdes_kategoriajanak_szotarabol_m82c2():
    q = "Melyik a legolcsobb gamer asztali szamitogep?"
    # a kontextus notebook, a kerdes viszont asztali gepet mond -> a kerdes nyer
    assert _fd.detect_facet_tags(q, NB, FMAP, category=CAT_PC) == ["felhasznalas-jellege:gamer"]
    assert _fd.category_value(NB, FMAP, category=CAT_PC) == CAT_PC
    assert _fd.build_facet_conditions(["felhasznalas-jellege:gamer"], CAT_PC) == [
        {"key": "facets", "match": {"value": "felhasznalas-jellege:gamer"}},
        {"key": "category", "match": {"value": CAT_PC}},
    ]


def test_override_nelkul_a_talalatok_dontenek_m82c2():
    # regresszio: kategoria-szandek nelkul valtozatlan a m82c/1 viselkedes
    q = "Melyik a legolcsobb gamer laptop?"
    assert _fd.detect_facet_tags(q, NB, FMAP) == ["felhasznalas-jellege:gamer"]
    assert _fd.category_value(NB, FMAP) == CAT_NB


def test_terkepben_nem_letezo_kategoria_nem_ad_cimket_m82c2():
    # a Qdrant tobb kategoriat ismer, mint a crawl-olt terkep -> fail-safe
    assert _fd.detect_facet_tags("legolcsobb 16gb monitor", NB, FMAP, category=CAT_MON) == []
    assert _fd.category_value(NB, FMAP, category=CAT_MON) == ""


def test_facet_tag_url_a_kerdes_kategoriajara_m82c2():
    url = _fd.facet_tag_url(
        "https://pelda.hu", NB, ["felhasznalas-jellege:gamer"], FMAP, category=CAT_PC
    )
    assert url == (
        "https://pelda.hu/asztali-pc-aio-konzol/asztali-szamitogep-c110/felhasznalas-jellege:gamer"
    )

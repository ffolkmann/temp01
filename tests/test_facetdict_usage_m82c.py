"""m82c - a felhasznalas-jelleg a GENERIKUS szotarbol jon (nem kezi listabol),
es a facets-szures kategoria-kapuval megy.

Fajl-betoltes (stdlib-only modulok), mint a m82b-nel -- igy a fake-app-os
tesztek nem tudjak eltorni a collectiont.
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fd = _load("facetdict_m82c_under_test", "app/services/facetdict.py")
_px = _load("paramextract_m82c_under_test", "app/services/paramextract.py")

CAT_NB = "Laptop, Notebook > UJ Notebook"
CAT_PC = "Asztali PC, AiO, Konzol > Asztali szamitogep"

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
                "marka": {"asus": 131, "lenovo": 477},
            },
        },
        "asztali-szamitogep": {
            "url": "/asztali-pc-aio-konzol/asztali-szamitogep-c110",
            "facets": {
                "felhasznalas-jellege": {"irodai-otthoni": 234, "gamer": 6},
                "marka": {"hp": 60},
            },
        },
    },
}
NB = [CAT_NB] * 5
PC = [CAT_PC] * 5


def test_usage_a_generikus_szotarbol_jon_m82c():
    assert _fd.detect_facet_tags("Melyik a legolcsobb uzleti notebook?", NB, FMAP) == [
        "felhasznalas-jellege:uzleti"
    ]
    assert _fd.detect_facet_tags("legolcsobb gamer laptop", NB, FMAP) == [
        "felhasznalas-jellege:gamer"
    ]
    assert _fd.detect_facet_tags("legolcsobb laptop", NB, FMAP) == []


def test_ugyanaz_az_ertek_masik_kategoriaban_is_el_m82c():
    # a 'gamer' a notebook ES az asztali kategoriaban is letezik -> a
    # felismeres mindkettoben mukodik, a SZURES viszont kategoria-feltetelt kap
    assert _fd.detect_facet_tags("legolcsobb gamer szamitogep", PC, FMAP) == [
        "felhasznalas-jellege:gamer"
    ]


def test_category_value_m82c():
    assert _fd.category_value(NB, FMAP) == CAT_NB
    assert _fd.category_value(PC, FMAP) == CAT_PC
    assert _fd.category_value(["Ismeretlen > Kategoria"], FMAP) == ""
    assert _fd.category_value([], FMAP) == ""
    assert _fd.category_value(NB, None) == ""


def test_facets_feltetel_kategoria_kapuval_m82c():
    must = _fd.build_facet_conditions(["felhasznalas-jellege:gamer"], CAT_NB)
    assert must == [
        {"key": "facets", "match": {"value": "felhasznalas-jellege:gamer"}},
        {"key": "category", "match": {"value": CAT_NB}},
    ]
    # fail-safe ujraproba: kategoria nelkul a regi alak
    assert _fd.build_facet_conditions(["felhasznalas-jellege:gamer"]) == [
        {"key": "facets", "match": {"value": "felhasznalas-jellege:gamer"}}
    ]
    # ures cimkelista -> kategoria-feltetel sincs
    assert _fd.build_facet_conditions([], CAT_NB) == []
    assert _fd.build_facet_conditions(None, CAT_NB) == []


def test_usage_zaro_link_m82c():
    url = _fd.facet_tag_url("https://x.hu/", NB, ["felhasznalas-jellege:uzleti"], FMAP)
    assert url == "https://x.hu/laptop-notebook/uj-notebook-c100/felhasznalas-jellege:uzleti"


def test_paramextract_mar_nem_ad_usage_kulcsot_m82c():
    assert _px.detect_constraints("Melyik a legolcsobb uzleti notebook?") == {}
    assert "usage" not in _px.detect_constraints("legolcsobb gamer laptop")
    # a marka-ag es a meret-ag valtozatlan
    assert _px.detect_constraints("legolcsobb asus gamer laptop") == {"brand": "asus"}
    assert _px.detect_constraints("legolcsobb 17,3 colos laptop") == {"kijelzo_meret_gte": 17.3}

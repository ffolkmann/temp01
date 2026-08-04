"""m82b - generikus facet-felismero (facetdict) egysegtesztek.

A modul stdlib-only, ezert kozvetlen fajl-betoltes (nincs app-import ->
a fake-app-os tesztek nem tudjak eltorni a collectiont).
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "facetdict_m82b_under_test", ROOT / "app" / "services" / "facetdict.py"
)
_fd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fd)

FMAP = {
    "client_id": "t",
    "categories": {
        "uj-notebook": {
            "url": "/laptop-notebook/uj-notebook-c100",
            "facets": {
                "memoria-meret": {"8gb": 98, "16gb": 579, "32gb": 211},
                "operacios-rendszer": {
                    "windows-11-home": 157,
                    "windows-11-professional": 371,
                    "nincs-kulon-megvasarolhato": 421,
                },
                "erintokepernyo": {"nem": 848, "10-point-multi-touch": 95},
                "extrak": {"webkamera": 942, "nfc": 23},
                "kijelzo-meret": {"156": 206, "173": 14},
                "marka": {"asus": 131, "lenovo": 477},
                "grafikus-vezerlo-gyarto": {"intel": 499, "nvidia": 210},
            },
        },
        "notebook-taska-hatizsak": {
            "url": "/kiegeszitok/notebook-taska-hatizsak-c114",
            "facets": {
                "anyag": {"nylon": 40, "bor": 12, "poliuretan": 60},
                "szin": {"fekete": 41, "kek": 20, "szurke": 30},
                "marka": {"targus": 50, "dicota": 60},
            },
        },
    },
}

NB = ["Laptop, notebook > Uj notebook"] * 5
BAG = ["Kiegeszitok > Notebook taska, hatizsak"] * 5


def test_memoria_ertek_szokozzel_is_illeszkedik():
    assert _fd.detect_facet_tags("legolcsobb 16 GB RAM-os laptop", NB, FMAP) == [
        "memoria-meret:16gb"
    ]


def test_ekezetes_kerdes_es_tobb_szavas_ertek():
    tags = _fd.detect_facet_tags(
        "legolcsóbb Windows 11 Professional notebook", NB, FMAP
    )
    assert tags == ["operacios-rendszer:windows-11-professional"]


def test_bool_ertek_nem_szur():
    # az 'erintokepernyo: nem' ertek MINDEN magyar kerdesbe beleillene
    assert _fd.detect_facet_tags("nem szeretnek dragat", NB, FMAP) == []


def test_kategoria_kapu():
    # a memoria-meret a taska-kategoriaban nem letezik -> nincs szures
    assert _fd.detect_facet_tags("16 GB", BAG, FMAP) == []
    # es forditva: az anyag csak a taska-kategoriaban van
    assert _fd.detect_facet_tags("nylon taska", BAG, FMAP) == ["anyag:nylon"]
    assert _fd.detect_facet_tags("nylon taska", NB, FMAP) == []


def test_nincs_kategoria_vagy_terkep():
    assert _fd.detect_facet_tags("16 GB", [], FMAP) == []
    assert _fd.detect_facet_tags("16 GB", NB, None) == []
    assert _fd.detect_facet_tags("", NB, FMAP) == []


def test_sajat_aggal_kezelt_attributum_kimarad():
    # marka (m80 brand) es kijelzo-meret (m81 p_kijelzo) nem jon vissza
    tags = _fd.detect_facet_tags("asus 17 colos 16 GB-os laptop", NB, FMAP)
    assert tags == ["memoria-meret:16gb"]


def test_nem_szelektiv_ertek_kimarad():
    # extrak:webkamera 942/942 -> nem szuro
    assert _fd.detect_facet_tags("webkameras laptop", NB, FMAP) == []
    # de az nfc (23) igen
    assert _fd.detect_facet_tags("nfc-s laptop", NB, FMAP) == ["extrak:nfc"]


def test_szohatar_nem_enged_reszszot():
    # 'intel' ne illeszkedjen az 'intelligens'-be
    assert _fd.detect_facet_tags("intelligens megoldast keresek", NB, FMAP) == []
    assert _fd.detect_facet_tags("intel processzoros gep", NB, FMAP) == [
        "grafikus-vezerlo-gyarto:intel"
    ]


def test_max_attributum_korlat():
    msg = "nfc-s intel 16 GB Windows 11 Home tipusu gep"
    tags = _fd.detect_facet_tags(msg, NB, FMAP)
    assert 1 <= len(tags) <= 3
    assert len({t.split(":")[0] for t in tags}) == len(tags)  # attributumonkent 1


PRINTER = {
    "client_id": "t",
    "categories": {
        "nyomtato": {
            "url": "/nyomtato/nyomtato-c113",
            "facets": {
                "funkcionalitas": {"multifunkcios-nyomtato": 114, "nyomtato": 49},
                "nyomtatasi-technologia": {"tintasugaras": 90, "lezer": 65},
            },
        }
    },
}
PRN = ["Nyomtato > Nyomtato"] * 5


def test_kategoria_fonev_nem_szuro():
    # a 'nyomtato' a kerdesben terméknev, nem funkcionalitas:nyomtato szuro
    tags = _fd.detect_facet_tags("legolcsobb tintasugaras nyomtato", PRN, PRINTER)
    assert tags == ["nyomtatasi-technologia:tintasugaras"]


def test_facet_tag_url():
    url = _fd.facet_tag_url(
        "https://notebookstore.hu/", NB, ["memoria-meret:16gb"], FMAP
    )
    assert url == "https://notebookstore.hu/laptop-notebook/uj-notebook-c100/memoria-meret:16gb"
    # nem letezo ertek -> None
    assert _fd.facet_tag_url("https://x.hu", NB, ["memoria-meret:999gb"], FMAP) is None
    # nincs cimke / terkep / base -> None
    assert _fd.facet_tag_url("https://x.hu", NB, [], FMAP) is None
    assert _fd.facet_tag_url("", NB, ["memoria-meret:16gb"], FMAP) is None
    assert _fd.facet_tag_url("https://x.hu", [], ["memoria-meret:16gb"], FMAP) is None


def test_build_facet_conditions():
    assert _fd.build_facet_conditions(["memoria-meret:16gb"]) == [
        {"key": "facets", "match": {"value": "memoria-meret:16gb"}}
    ]
    assert _fd.build_facet_conditions([]) == []
    assert _fd.build_facet_conditions(None) == []

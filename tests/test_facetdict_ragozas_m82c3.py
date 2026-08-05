"""m82c/3: ragozas-tures + koznyelvi szinonimak a facets-szotarban.

A recall-res eddig: a crawl-olt ertek SLUG-alakja pontos illeszkedest kivant,
igy a magyar ragozott alak ("ujjlenyomat-olvasoVAL") es a koznyelvi szinonima
("4K" vs 3840x2160) kimaradt.

A tures SZANDEKOSAN aszimmetrikus: csak a HOSSZU ertekek zaro-hatara lazul,
mert rovid ertekeknel a toldalek mas szot csinalna --
  intel (5) + "ligens" -> "intelligens"  (496 termek szurese egy KB-kerdesre)
  pla   (3) + "zma"    -> "plazma"
Fajl-betoltes (stdlib-only modul), minden minta ekezet nelkul.
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fd = _load("facetdict_m82c3_under_test", "app/services/facetdict.py")

CAT_NB = "Laptop, Notebook > UJ Notebook"
CAT_MON = "Monitor, Projektor, TV > Monitor"
CAT_NYO = "Nyomtato > Nyomtato"
CAT_FIL = "Nyomtato > 3D nyomtato filament"

# A darabszamok ugy vannak beallitva, hogy a szelektivitas-kapu (>=80% a
# kategoria-median) egyik tesztelt erteket se ejtse ki.
FMAP = {
    "client_id": "t",
    "categories": {
        "uj-notebook": {
            "url": "/laptop-notebook/uj-notebook-c100",
            "facets": {
                "extrak": {"ujjlenyomat-olvaso": 425, "nfc": 23, "erintoceruza": 11},
                "grafikus-vezerlo-gyarto": {"intel": 496, "nvidia": 209},
                "memoria-meret": {"32gb": 211, "8gb": 98},
                "erintokepernyo": {"10-point-multi-touch": 95, "nem": 845},
            },
        },
        "monitor": {
            "url": "/monitor-projektor-tv/monitor-c123",
            "facets": {
                "felbontas": {"3840x2160": 45, "1920x1080": 119, "2560x1440": 84},
                "panel-tipus": {"ips": 100, "va": 31},
            },
        },
        "nyomtato": {
            "url": "/nyomtato/nyomtato-c113",
            "facets": {
                "nyomtatasi-technologia": {"lezer": 65, "tintasugaras": 89},
                "szinkeszlet": {"fekete": 61, "szines": 101},
                "papirmeret": {"a4": 138, "a3": 15},
            },
        },
        "3d-nyomtato-filament": {
            "url": "/nyomtato/3d-nyomtato-filament-c162",
            "facets": {"anyag": {"pla": 64, "abs": 38, "petg": 8}},
        },
    },
}


def _tags(q, cat):
    return _fd.detect_facet_tags(q, [cat] * 3, FMAP, category=cat)


# --- ragozas-tures HOSSZU ertekeken -----------------------------------------

def test_ragozott_hosszu_ertek_illeszkedik_m82c3():
    assert "extrak:ujjlenyomat-olvaso" in _tags("ujjlenyomat-olvasos laptop", CAT_NB)
    assert "extrak:ujjlenyomat-olvaso" in _tags(
        "van olyan laptop ujjlenyomat-olvasoval?", CAT_NB)
    assert "extrak:erintoceruza" in _tags("erintoceruzaval hasznalhato gep", CAT_NB)
    assert "nyomtatasi-technologia:tintasugaras" in _tags("tintasugarasat keresek", CAT_NYO)


def test_tul_hosszu_ratoldas_mar_nem_ragozas_m82c3():
    # 4+ karakter ratoldva mar mas szo -> nem illeszkedhet
    assert _tags("erintoceruzatarto allvany", CAT_NB) == []


# --- a rovid ertekek NEM kapnak turest (ez a legfontosabb kapu) --------------

def test_rovid_ertek_nem_kap_toldalek_turest_m82c3():
    # intel (5 kar) + 'ligens' -> az "intelligens" NEM szurhet 496 termekre
    assert _tags("melyik a legjobb intelligens megoldas?", CAT_NB) == []
    assert _tags("intelligens keresot szeretnek", CAT_NB) == []
    # pla (3 kar) + 'zma' -> a "plazma" nem filament
    assert _tags("van plazma tevetek?", CAT_FIL) == []


def test_rovid_ertek_pontos_alakja_tovabbra_is_talalat_m82c3():
    assert "grafikus-vezerlo-gyarto:intel" in _tags("intel processzoros gep", CAT_NB)
    assert "anyag:pla" in _tags("pla filament", CAT_FIL)
    assert "extrak:nfc" in _tags("nfc-s laptop", CAT_NB)
    assert "panel-tipus:ips" in _tags("ips paneles monitor", CAT_MON)


# --- koznyelvi szinonimak ---------------------------------------------------

def test_felbontas_szinonimak_m82c3():
    assert "felbontas:3840x2160" in _tags("legolcsobb 4K monitor", CAT_MON)
    assert "felbontas:3840x2160" in _tags("UHD monitort keresek", CAT_MON)
    assert "felbontas:2560x1440" in _tags("2K felbontasu monitor", CAT_MON)
    assert "felbontas:1920x1080" in _tags("full hd monitor", CAT_MON)
    assert "felbontas:1920x1080" in _tags("fullhd monitor", CAT_MON)


def test_erintokepernyo_es_lezer_szinonima_m82c3():
    assert "erintokepernyo:10-point-multi-touch" in _tags("erintokepernyos laptop", CAT_NB)
    assert "erintokepernyo:10-point-multi-touch" in _tags("touchscreen laptop", CAT_NB)
    assert "nyomtatasi-technologia:lezer" in _tags("legolcsobb lezernyomtato", CAT_NYO)


def test_szinonima_csak_a_sajat_kategoriajaban_m82c3():
    # a monitor-kategoriaban nincs nyomtatasi-technologia -> a szinonima sem hat
    assert _tags("legolcsobb lezernyomtato", CAT_MON) == []


# --- marketing-frazis csapda ------------------------------------------------

def test_fekete_pentek_nem_szinszuro_m82c3():
    assert _tags("fekete pentek akcio?", CAT_NYO) == []
    assert _tags("black friday ajanlatok", CAT_NYO) == []
    # de a valodi szin-szandek atmegy
    assert "szinkeszlet:fekete" in _tags("fekete tonerrel nyomtato", CAT_NYO)


# --- regresszio: a m82b/m82c hygiena valtozatlan ----------------------------

def test_higienia_valtozatlan_m82c3():
    assert _tags("mennyibe kerul a szallitas?", CAT_NB) == []
    assert _tags("van ra 3 ev garancia?", CAT_NB) == []
    assert _tags("melyik a legolcsobb laptop?", CAT_NB) == []
    # kategoria-fonev: a 'nyomtato' nem a funkcionalitas-szuro
    assert "nyomtatasi-technologia:tintasugaras" in _tags(
        "legolcsobb tintasugaras nyomtato", CAT_NYO)
    # tisztan szamos ertek tovabbra is a p_<attr> range-age
    assert _tags("legolcsobb 17 colos laptop", CAT_NB) == []

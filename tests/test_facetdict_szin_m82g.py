"""m82g: a kezi _COLORS lista kivezetese a generikus szotarba + TEMA-KAPU.

A `szin` kikerult a facetdict._SKIP_ATTRS-bol, a paramextract kezi _COLORS
listaja es a bag-gate pedig megszunt a kerdes-oldalon. Nyereseg (tools/m82g_map.py,
85-kategorias crawl-terkep): a 3D filament 103 crawl-olt szinere eddig SEMMI nem
szurt, mert a bag-gate oda sosem ert el.

A sima kivezetes viszont MERHETOEN rossz: tools/m82g_sweep.py szerint recall
0/11 -> 11/11, de FP-scan 0/2210 -> 18/2210, mert a magyar szin-szavak allando
szokapcsolatokban is elnek ("zold energia", "zold ut", "szurke zona", "piros
lampa", "sarga csekk", "arany garanciacsomag"). A _VALUE_TRAPS bovitese itt
whack-a-mole lenne = a kezi lista visszahozasa.

Ezert ATTRIBUTUM-OSZTALY szintu a szabaly (_TOPIC_REQ_ATTRS): a koznyelvi
erteku attributum csak akkor szur, ha a kerdes a KAPU-KATEGORIAROL szol -- azaz
tartalmazza a kategoria-slug legalabb egy >= _TOPIC_MIN karakteres tokenjet.
Meres a patch utan: recall 11/11, FP-scan 1/2210 (az az egy eroltetett kapuval).

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


_fd = _load("facetdict_m82g_under_test", "app/services/facetdict.py")

FMAP = {
    "categories": {
        "3d-nyomtato-filament": {
            "url": "/3d-nyomtato-filament-c200",
            "facets": {
                "anyag": {"pla": 120, "petg": 60, "abs": 40},
                "atmero": {"175mm": 300, "285mm": 80},
                "szin": {
                    "fekete": 41, "feher": 28, "szurke": 24, "kek": 23, "piros": 22,
                    "sarga": 17, "vilagos-zold": 16, "zold": 9, "arany": 3,
                    "tengereszkek": 9,
                },
            },
        },
        "notebook-taska-hatizsak": {
            "url": "/notebook-taska-hatizsak-c100",
            "facets": {
                "szin": {"fekete": 41, "szurke": 33, "kek": 14, "barna": 5},
                "marka": {"lenovo": 55, "dell": 19},
                "maximalis-notebook-meret": {"173": 20, "156": 40},
            },
        },
        "kulso-dvd-iro": {
            "url": "/kulso-dvd-iro-c300",
            "facets": {
                "szin": {"fekete": 4, "ezust": 2, "feher": 2},
                "marka": {"asus": 5},
            },
        },
        "uj-notebook": {
            "url": "/uj-notebook-c100",
            "facets": {
                "memoria-meret": {"16gb": 200, "32gb": 50},
                "operacios-rendszer": {"windows-11-professional": 300},
            },
        },
    }
}

FIL = "3d nyomtato filament"
TAS = "notebook taska hatizsak"
DVD = "kulso dvd iro"
NB = "uj notebook"


def _tags(q, cat):
    return _fd.detect_facet_tags(q, [], FMAP, category=cat)


def test_szin_mar_nem_skip_es_van_tema_kapu():
    """A kivezetes ES a hozza tartozo kapu egyutt dokumentalva."""
    assert "szin" not in _fd._SKIP_ATTRS
    assert _fd._TOPIC_REQ_ATTRS == frozenset({"szin"})
    assert _fd._TOPIC_MIN == 4


def test_temajel_mellett_szur():
    """A fo nyeremeny: a filamentre eddig SEMMILYEN szinszures nem volt."""
    assert "szin:fekete" in _tags("van fekete filamentetek?", FIL)
    assert "szin:tengereszkek" in _tags("tengereszkek filament", FIL)
    assert "szin:vilagos-zold" in _tags("vilagos zold filament ara?", FIL)
    assert "szin:piros" in _tags("piros PLA filamentet keresek", FIL)


def test_taska_paritas_a_regi_bag_gate_tel():
    """REGRESSZIO: amit a kezi _COLORS + bag-gate tudott, azt tudni kell tovabbra is."""
    assert "szin:fekete" in _tags("fekete notebook taskat keresek", TAS)
    assert "szin:szurke" in _tags("van szurke hatizsakotok?", TAS)
    assert "szin:barna" in _tags("barna taskatok van?", TAS)
    # osszetett szo: a "taska" (5 betu) ala a _CAT_COMPOUND_MIN=6 elotag-engedmeny
    # nem fer be -- ezert lazitja a _topic_hit reszszora az illesztest
    assert "szin:kek" in _tags("kek laptoptaska", TAS)
    assert "szin:ezust" in _tags("ezust kulso dvd irot keresek", DVD)


def test_koznyelvi_szokapcsolat_nem_szur():
    """A 18 meresi FP magja: szin-szo termek-tema nelkul."""
    for q, cat in (
        ("zold energiaval mukodik a bolt?", FIL),
        ("zold utat kaptam a rendelesre?", FIL),
        ("sarga csekket kaptam", TAS),
        ("arany garanciacsomagot vettem", TAS),
        ("kek szamlat kertem", DVD),
        ("a szurke zonaban van a szallitasi hatarido", TAS),
        ("feher pontok vannak a kijelzon", TAS),
    ):
        assert not [t for t in _tags(q, cat) if t.startswith("szin:")], q


def test_fekete_pentek_valtozatlan():
    """m82c/3 _VALUE_TRAPS: a kapu ELOTT is, UTAN is tiszta."""
    assert not [t for t in _tags("fekete pentek akcio?", FIL) if t.startswith("szin:")]
    assert not [t for t in _tags("black friday ajanlatok?", TAS) if t.startswith("szin:")]


def test_topic_hit_egyseg():
    """A kapu magja: >= _TOPIC_MIN karakteres slug-token reszszokent."""
    assert _fd._topic_hit("3d-nyomtato-filament", "van fekete filamentetek?") is True
    assert _fd._topic_hit("notebook-taska-hatizsak", "kek laptoptaska") is True
    assert _fd._topic_hit("notebook-taska-hatizsak", "van szurke hatizsakotok?") is True
    assert _fd._topic_hit("3d-nyomtato-filament", "zold energiaval mukodik a bolt?") is False
    # a rovid tokenek ("3d", "dvd", "iro") nem adnak temajelet
    assert _fd._topic_hit("kulso-dvd-iro", "kek dvd") is False
    assert _fd._topic_hit("kulso-dvd-iro", "ezust kulso dvd irot keresek") is True


def test_tema_kapu_csak_a_koznyelvi_attributumra_vonatkozik():
    """TUDATOS HATAR: a szabaly NEM altalanosithato.

    A m82f eles esete ("Van 32 GB memoriaval laptopotok?") elbukna rajta, mert a
    kapu-kategoria az "UJ Notebook", a kerdesben viszont "laptop" all -- a
    memoria-meret cimkenek ezert NEM kell temajel.
    """
    assert _fd._topic_hit("uj-notebook", "van 32 gb memoriaval laptopotok?") is False
    assert "memoria-meret:32gb" in _tags("Van 32 GB memoriaval laptopotok?", NB)


def test_ismert_hatar_eroltetett_kapunal():
    """A meres 1/2210 maradek FP-je, tudatosan.

    A "nyomtato" token benne van a filament-slugban, ezert a "piros lampa villog a
    nyomtaton" kerdes ATENGED a temakapun -- de csak akkor, ha a kaput EROSZAKKAL
    a filamentre allitjuk. Elesben ez a kerdes a Nyomtato kategoriara all be, ahol
    egyaltalan nincs `szin` attributum.
    """
    assert _fd._topic_hit("3d-nyomtato-filament", "a piros lampa villog a nyomtaton") is True

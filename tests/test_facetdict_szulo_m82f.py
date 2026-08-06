"""m82f: SZULO-SZINTU kategoria-feloldas ("laptopotok" -> UJ Notebook).

Nyitott eset volt (m82d/2 3. pont): "Van 32 GB memoriaval laptopotok?" -> a
kerdesbol nem oldhato fel kategoria, mert a payload-level neve "UJ Notebook" es
a "laptop" szo nem illeszkedik ra; a kapu ezert a talalat-alapu fallbackre esett,
ami RAM-MODULOKAT adott (Memoria (Hasznalt)=14, Memoria bovites=9).

ADAT-LELET (tools/m82f_catdiag.py): a "Laptop, Notebook" szulo alatt PONTOSAN EGY
level van (UJ Notebook, 6416 termek) -- a m82d/2-ben zsakutcanak jelolt szulo-ut
tehat itt NEM fut holtversenybe. Innen a szabaly:

  1. a level-kor valtozatlan (m82e _head_match); ha van FEJ-alaku level-jelolt,
     a mai logika dont (holtverseny -> "");
  2. csak ha nincs level-jelolt, jonnek a SZULO-nevek -- es CSAK azoke a
     szuloke, amelyek alatt pontosan EGY level van;
  3. a szulo-nev koznyelvi szo, ezert szigorubb: csak FEJ-alakban jelolt
     (esetrag vagy tagmondat-veg). Csupasz to + masik szo = osszeteteli JELZO.

MERES (tools/m82f_sweep.py, 100 valodi payload-kategoria):
  fej-regresszio 0/333, negativ korpusz 0/15, osszeteteli csapdak 0/10,
  cel-korpusz 7/8 javul, jelzoi scan 105 eset lesz determinisztikus.

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


_fd = _load("facetdict_m82f_under_test", "app/services/facetdict.py")

NB = "Laptop, Notebook > UJ Notebook"          # EGY-levelu szulo: Laptop, Notebook
TASKA = "Kiegeszitok > Notebook taska, hatizsak"
HUTO = "Kiegeszitok > Notebook huto"
NYO1 = "Nyomtato > Nyomtato"                    # tobb-levelu szulo: Nyomtato
NYO2 = "Nyomtato > Etikett"
MON = "Monitor, Projektor, TV > Monitor"        # tobb-levelu szulo
PROJ = "Monitor, Projektor, TV > Projektor"
CATALOG = [NB, TASKA, HUTO, NYO1, NYO2, MON, PROJ, "Kiegeszitok > Videokartya"]


def test_szulo_nev_feloldja_a_kategoriat():
    """A kivalto eset: a level neve 'UJ Notebook', a kerdesben 'laptop' all."""
    assert _fd.detect_category("Van 32 GB memoriaval laptopotok?", CATALOG) == NB
    assert _fd.detect_category("Milyen laptopokat ajanlotok?", CATALOG) == NB
    assert _fd.detect_category("Keresek egy laptopot", CATALOG) == NB


def test_tagmondat_vegi_csupasz_to_is_fej():
    assert _fd.detect_category("Melyik a legolcsobb laptop?", CATALOG) == NB
    assert _fd.detect_category("Erdekelne egy notebook", CATALOG) == NB


def test_osszeteteli_jelzo_nem_fej():
    """'laptop taska' -> a fej a TASKA; a szulo-nev csupasz tovel jelzo."""
    assert _fd.detect_category("Van laptop taskatok?", CATALOG) == ""
    assert _fd.detect_category("Milyen laptop toltot ajanlotok?", CATALOG) == ""
    assert _fd.detect_category("Keresek egy laptop hutot", CATALOG) == ""


def test_level_mindig_eros_a_szulonel():
    """Ha van FEJ-alaku level-jelolt, az dont -- a szulo-kor el sem indul."""
    assert _fd.detect_category("Milyen notebook hutot ajanlotok?", CATALOG) == HUTO
    assert _fd.detect_category("Milyen notebook taskaitok vannak?", CATALOG) == TASKA
    assert _fd.detect_category("Melyik a legolcsobb nyomtato?", CATALOG) == NYO1


def test_tobb_levelu_szulo_kimarad():
    """A 'Monitor, Projektor, TV' szulo alatt 3 level van -> nem jelolt.

    (A 'monitor' szo amugy is illeszkedik a Monitor LEVELRE -- itt az szamit,
    hogy a 'tv' nem huzza be az egesz szulot.)
    """
    slp = _fd._single_leaf_parents(CATALOG)
    assert "Laptop, Notebook" in slp and slp["Laptop, Notebook"] == NB
    assert "Nyomtato" not in slp
    assert "Monitor, Projektor, TV" not in slp


def test_jelzoi_kepzo_a_szulon_sem_jelolt():
    """m82e szabalya a szulo-korben is all."""
    assert _fd.detect_category("Van laptopos taskatok?", CATALOG) == ""


def test_parent_head_match_alakok():
    rx = _fd._cat_rx("laptop")
    assert _fd._parent_head_match(rx, "van laptopotok?") is True      # esetrag
    assert _fd._parent_head_match(rx, "keresek egy laptopot") is True  # esetrag
    assert _fd._parent_head_match(rx, "a legolcsobb laptop?") is True  # tagmondat-veg
    assert _fd._parent_head_match(rx, "laptop taskatok") is False      # osszeteteli jelzo
    assert _fd._parent_head_match(rx, "laptopos taska") is False       # jelzoi kepzo


def test_egy_szintu_kategoria_nem_ad_szulot():
    """'>' nelkuli kategoria-ertek nem general szulo-jeloltet (nincs mibol)."""
    assert _fd._single_leaf_parents(["Tablet"]) == {}


FMAP = {
    "client_id": "t",
    "categories": {
        "uj-notebook": {"url": "/laptop-notebook/uj-notebook-c100", "facets": {}},
    },
}


def test_category_url_a_kategoria_oldalra_mutat():
    """m82f/2: cimke nelkul is legyen ertelmes zaro-link (a kategoria-oldal)."""
    assert _fd.category_url("https://bolt.hu", [], FMAP, category=NB) \
        == "https://bolt.hu/laptop-notebook/uj-notebook-c100"
    # a base_url zaro perjele nem duplikalodik
    assert _fd.category_url("https://bolt.hu/", [], FMAP, category=NB) \
        == "https://bolt.hu/laptop-notebook/uj-notebook-c100"


def test_category_url_fail_safe_none():
    assert _fd.category_url("https://bolt.hu", [], FMAP, category=TASKA) is None
    assert _fd.category_url("https://bolt.hu", [], FMAP, category="") is None
    assert _fd.category_url("", [], FMAP, category=NB) is None
    assert _fd.category_url("https://bolt.hu", [], None, category=NB) is None

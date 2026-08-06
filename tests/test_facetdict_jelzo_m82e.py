"""m82e: JELZOI (-s kepzos) kategoria-nev nem viszi el a kategoria-kaput.

Elo hiba (m82d/2 elomeres): "Van NVIDIA videokartyaS notebookotok?" -> a kapu a
Kiegeszitok > Videokartya kategoriara allt be, mert a melleknevi kepzo (-s)
belefert a _CAT_SUFFIX=4 toldalek-turesbe. A kerdes viszont a NOTEBOOKrol szol:
a magyarban a jelzo elol all es kepzot kap, a fej pedig esetragot
("notebookOTOK", "monitorT", "nyomtatoK").

Szabaly (_head_match): a jelzoi illeszkedes nem jelolt. Ha CSAK jelzoi jelolt
van, a detect_category "" -> marad a talalat-alapu fallback (mai, konzervativ
ut) -- NEM a jelzoi kategoria.

Kockazat-terkep (tools/m82e_catdiag.py, 100 valodi payload-kategoria, 111
kategoria-nev-resz): fej-alakban 0/333 valtozas, negativ korpuszon 0 valtozas,
jelzoi alakban 111/111 jelolt esik ki helyesen.

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


_fd = _load("facetdict_m82e_under_test", "app/services/facetdict.py")

CATALOG = [
    "Kiegeszitok > Videokartya",
    "Laptop, Notebook > UJ Notebook",
    "Monitor > Monitor",
    "Kiegeszitok > Webkamera",
    "Tablet > Tablet",
    "Kiegeszitok > Billentyuzet, eger",
    "Nyomtato > Nyomtato",
    "Szamitogep > Asztali szamitogep",
    "Halozat > Range Extender",
    "Halozat > Wi-Fi jelerosito, range extender",
]


def test_jelzoi_alak_nem_viszi_el_a_kaput():
    """A kivalto eles eset: a -s kepzos kategoria-nev jelzo, nem a kerdes targya."""
    assert _fd.detect_category("Van NVIDIA videokartyas notebookotok?", CATALOG) == ""


def test_fej_jelolt_nyer_a_jelzoi_felett():
    """Ha van fej-alaku jelolt is, AZ dont -- fuggetlenul a hosszatol."""
    assert _fd.detect_category("Van webkameras monitorotok?", CATALOG) == "Monitor > Monitor"
    assert _fd.detect_category("Keresek egy billentyuzetes tabletet", CATALOG) == "Tablet > Tablet"


def test_fej_alak_valtozatlan():
    """REGRESSZIO: a m82c/2 es m82c/4 nyeremenyei nem serulnek."""
    assert _fd.detect_category("Melyik a legolcsobb lezernyomtato?", CATALOG) \
        == "Nyomtato > Nyomtato"
    assert _fd.detect_category("Milyen 4K monitorokat ajanlotok?", CATALOG) == "Monitor > Monitor"
    assert _fd.detect_category("Melyik a legolcsobb gamer asztali szamitogep?", CATALOG) \
        == "Szamitogep > Asztali szamitogep"
    assert _fd.detect_category("Milyen egereket arultok?", CATALOG) \
        == "Kiegeszitok > Billentyuzet, eger"
    assert _fd.detect_category("Van webkameratok?", CATALOG) == "Kiegeszitok > Webkamera"


def test_holtverseny_valtozatlan():
    """Ket kulonbozo kategoria egyforma erosen -> "" (m82c/2 szabaly)."""
    assert _fd.detect_category("Kell egy range extender", CATALOG) == ""


def test_head_match_toldalek_osztalyozas():
    """A kepzo/esetrag hatara -- ez a szabaly magja."""
    rx = _fd._cat_rx("videokartya")
    assert _fd._head_match(rx, "van videokartyatok?") is True     # birtokos = FEJ
    assert _fd._head_match(rx, "keresek videokartyat") is True    # targyeset = FEJ
    assert _fd._head_match(rx, "videokartyak arai") is True       # tobbes = FEJ
    assert _fd._head_match(rx, "videokartyas notebook") is False  # kepzo = JELZO
    assert _fd._head_match(rx, "videokartyasat kerem") is False   # kepzo + esetrag = JELZO


def test_eleg_egy_fej_alaku_elofordulas():
    """Ha a szo tobbszor szerepel, EGY fej-alak is jelolte teszi (fail-safe irany)."""
    rx = _fd._cat_rx("videokartya")
    assert _fd._head_match(rx, "videokartyas gep helyett kulon videokartyat keresek") is True


def test_eszkozhatarozo_tudatosan_fej_marad():
    """HATAR: a -val/-vel (es a tobbi esetrag) NEM kepzo -- a m82e scope-ja csak a -s.

    Ha ez kesobb gondot okoz ("videokartyaval notebook"), kulon meres kell hozza.
    """
    rx = _fd._cat_rx("videokartya")
    assert _fd._head_match(rx, "mit tudsz a videokartyaval?") is True


def test_konstansok_dokumentalva():
    assert _fd._CAT_SUFFIX == 4
    assert _fd._CAT_ADJ.match("s") and _fd._CAT_ADJ.match("os") and _fd._CAT_ADJ.match("es")
    assert not _fd._CAT_ADJ.match("ok")   # tobbes
    assert not _fd._CAT_ADJ.match("t")    # targyeset
    assert not _fd._CAT_ADJ.match("otok")  # birtokos tobbes

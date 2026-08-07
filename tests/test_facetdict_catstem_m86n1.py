"""m86/1: SZIMMETRIKUS kategoria-illesztes -- a kategoria-nev tobbes jele elhagyhato.

A m86 kor nyitott #1-e, konkret bizonyitekkal: "Csavarhuzo keszlet" -> a kapu a
generikus `Csavar`-ra (436 db) allt be, holott a `Csavarhuzok` kategoria ott van
a katalogusban (rang 42, 190 db). Ok: a _cat_rx toldalek-turese EGYIRANYU volt --
a KERDES kaphatott plusz ragot, a KATEGORIANEV nem, ezert a rovidebb, generikus
nev nyerte a "leghosszabb resz" versenyt.

A szabaly ket korlatja MERT dontes (tools/m86n1_sweep.py, 2766 valodi kerdes 8
tenanton + fej-regresszio + negativ korpusz):

  (1) ADDITIV alternacio, nem csere. A CSERE-s valtozat 4 REGRESSZIOT okozott a
      notebookstore-on (m82e videokartyas notebookotok, m82g szurke
      hatizsakotok, es 2 tovabbi), mert a rovidebb to megeszi a 4 karakteres
      rag-keretet. Additiv formaban a mai illeszkedes valtozatlan: a teljes alak
      all elol az alternacioban.
  (2) _CAT_STEM_MIN = 6. Az 5-os kuszob a "kellek" -> "kelle" tovet engedne, ami
      a "kellene"/"kellenek" szavakra illeszkedik: 11 hamis feloldas a valodi
      korpuszon. A 6 TUDATOS hatar -- ezert itt teszt rogziti.

Meres a szabalyra (a6): kellegyszerszam 77 -> 84, nagyonallatshop 28 -> 34,
notebookstore 79 -> 83 feloldott kerdes; ELVESZETT feloldas 0 mindenhol,
fej-regresszio 0 vesztes, negativ korpusz 0 elteres.

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


_fd = _load("facetdict_m86n1_under_test", "app/services/facetdict.py")

# valodi cat_tags katalogus-reszletek (kellegyszerszam / nagyonallatshop)
KELL = ["Csavar", "Csavarhuzok", "Furoszarak", "Kellek", "Sarokcsiszolok", "Anya"]
ALLAT = ["Eledel", "Macska eledelek", "Kutya eledelek", "Kutya", "Nyakorvek"]
# valodi `category` payload-ertekek (notebookstore, m82-es sav)
NBS = [
    "Laptop, Notebook > UJ Notebook",
    "Kiegeszitok > Notebook taska, hatizsak",
    "Kiegeszitok > Videokartya",
    "Kiegeszitok > Dokkolok",
    "Nyomtato > Nyomtato",
]


def test_cat_stem_egyseg():
    """A tovezes maga: kotohangzos alak elonyben, rovid tonel nincs levagas."""
    assert _fd._cat_stem(["Csavarhuzok"]) == "Csavarhuz"
    assert _fd._cat_stem(["Macska", "eledelek"]) == "eledel"
    assert _fd._cat_stem(["Nyakorvek"]) == "Nyakorv"
    # nem tobbes szam (nem -k vegu) -> nincs to
    assert _fd._cat_stem(["Csavar"]) == ""
    assert _fd._cat_stem(["Anya"]) == ""
    # TUDATOS HATAR: rovid to -> nincs levagas (kulonben "kelle" ~ "kellene")
    assert _fd._cat_stem(["Kellek"]) == ""
    assert _fd._CAT_STEM_MIN == 6


def test_a_tobbes_szamu_kategorianev_nyer():
    """A kivalto eset: a specifikus, tobbes szamu nev veri a generikus rovidet."""
    assert _fd.detect_category("Csavarhuzo keszlet", KELL) == "Csavarhuzok"
    assert _fd.detect_category('"Y" Triwing Tri Wing csavarhuzo, 3 elu!', KELL) == "Csavarhuzok"
    assert _fd.detect_category("Melyik a legolcsobb sarokcsiszolo?", KELL) == "Sarokcsiszolok"
    assert _fd.detect_category("Van macskaeledeletek?", ALLAT) == "Macska eledelek"
    assert _fd.detect_category("mi a legjobb kutyaeledel?", ALLAT) == "Kutya eledelek"


def test_a_mai_feloldas_valtozatlan():
    """ADDITIV: amit ma feloldott, azt tovabbra is, ugyanarra."""
    assert _fd.detect_category("Csavarokat keresek", KELL) == "Csavar"
    assert _fd.detect_category("Milyen anyagbol van?", KELL) == "Anya"   # ismert hatar
    assert _fd.detect_category("Van kutyatok?", ALLAT) == "Kutya"
    assert _fd.detect_category("Melyik a legolcsobb lezernyomtato?", NBS) == "Nyomtato > Nyomtato"


def test_m82_sav_regresszio():
    """A m82-es sav magja: a CSERE-s valtozat ezeket ELVESZTETTE."""
    # m82e: a jelzoi (-s kepzos) nev nem viszi el a kaput, a fej igen
    assert _fd.detect_category("Van NVIDIA videokartyas notebookotok?", NBS) \
        == "Laptop, Notebook > UJ Notebook"
    # m82g: a szinszures kapu-kategoriaja
    assert _fd.detect_category("Milyen szurke hatizsakotok van?", NBS) \
        == "Kiegeszitok > Notebook taska, hatizsak"
    assert _fd.detect_category("Es hatizsakban mi a legolcsobb 17 colos gephez?", NBS) \
        == "Kiegeszitok > Notebook taska, hatizsak"
    # m82f: szulo-szintu feloldas egy-levelu szulonel
    assert _fd.detect_category("Van 32 GB memoriaval laptopotok?", NBS) \
        == "Laptop, Notebook > UJ Notebook"
    # osszetett szo: a fej a taska, nem a notebook
    assert _fd.detect_category("Melyik a legolcsobb notebooktaska?", NBS) \
        == "Kiegeszitok > Notebook taska, hatizsak"


def test_rovid_to_nem_ad_hamis_feloldast():
    """TUDATOS HATAR (_CAT_STEM_MIN=6): a "kellek" tove nem illeszkedhet a "kellene"-re.

    Az 5-os kuszob a valodi korpuszon 11 ilyen hamis feloldast adott
    ("Olyan hosszu csipesz kellene...", "4 db kellen es afas szamlara...").
    """
    for q in ("Nem elliras, valoban olyan hosszu kellene..",
              "Olyan hosszu csipesz kellene ami 6mm es lyukba belefer",
              "milyen dokumentumok kellenek a hitelhez?"):
        assert _fd.detect_category(q, KELL) != "Kellek", q


def test_uj_feloldas_ott_is_ahol_eddig_semmi_nem_volt():
    """A tobbes szamu kategorianevek eddig EGYALTALAN nem voltak elerhetok."""
    assert _fd.detect_category("dokkolot keresnek a notimhoz", NBS) == "Kiegeszitok > Dokkolok"
    assert _fd.detect_category("Nyakorvre bileta vasarolhato?", ALLAT) == "Nyakorvek"
    assert _fd.detect_category("Sds max furoszarat keresek", KELL) == "Furoszarak"

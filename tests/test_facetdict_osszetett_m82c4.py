"""m82c/4: osszetett szavas kategoria-felismeres.

A magyar a kategoria-fonevet gyakran a szo VEGERE teszi ("lezerNYOMTATO"),
a kezdo hatar viszont szigoru volt, ezert a kapu nem allt be es a talalat-
alapu fallbackre esett vissza. Elo eset (2026-08-05): a "Melyik a legolcsobb
lezernyomtato?" kerdesre a valasz veletlenul jo lett (a szemantikus kereses
megtalalta a lezeres gepeket), de a facets-szuro EGYALTALAN NEM futott le.

A lazitas azert biztonsagos, mert a detect_category a LEGHOSSZABB illeszkedo
reszt valasztja, es holtversenynel nem dont -- igy a "cimkenyomtato" a
Cimkenyomtato kategoriara megy, nem a Nyomtatora.
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fd = _load("facetdict_m82c4_under_test", "app/services/facetdict.py")
detect_category = _fd.detect_category

# valodi alaku payload-kategoriak
CATALOG = [
    "Nyomtató > Nyomtató",
    "Nyomtató > Címkéző gép, címkenyomtató",
    "Nyomtató > 3D nyomtatók",
    "Monitor, Projektor, TV > Monitor",
    "Kiegészítők > Monitorszűrő",
    "Kiegészítők > Notebook táska, hátizsák",
    "Kiegészítők > Egér",
    "Asztali PC, AiO, Konzol > Asztali számítógép",
    "Laptop, Notebook > ÚJ Notebook",
]


# --- a javitas lenyege ------------------------------------------------------

def test_osszetett_szo_vegen_allo_kategoria_m82c4():
    assert detect_category("Melyik a legolcsobb lezernyomtato?", CATALOG) == "Nyomtató > Nyomtató"
    assert detect_category("notebooktaskat keresek", CATALOG) == "Kiegészítők > Notebook táska, hátizsák"


def test_kulon_irt_alak_tovabbra_is_mukodik_m82c4():
    assert detect_category("Melyik a legolcsobb lezeres nyomtato?", CATALOG) == "Nyomtató > Nyomtató"
    assert detect_category("Melyik a legolcsobb tintasugaras nyomtato?", CATALOG) == "Nyomtató > Nyomtató"
    assert detect_category("legolcsobb 4K monitor", CATALOG) == "Monitor, Projektor, TV > Monitor"


# --- a leghosszabb nyer: nincs atcsuszas szukebb kategoriabol -----------------

def test_leghosszabb_resz_nyer_nem_csuszik_at_m82c4():
    # a 'cimkenyomtato' NEM a Nyomtato (bar a 'nyomtato' is illeszkedne benne)
    got = detect_category("Melyik a legolcsobb cimkenyomtato?", CATALOG)
    assert got == "Nyomtató > Címkéző gép, címkenyomtató"
    # a 'monitorszuro' NEM a Monitor
    assert detect_category("monitorszurot keresek", CATALOG) == "Kiegészítők > Monitorszűrő"


# --- kapuk: mikor NEM engedunk elotagot -------------------------------------

def test_rovid_kategorianev_ele_nincs_elotag_m82c4():
    # 'eger' 4 karakter (< _CAT_COMPOUND_MIN=6) -> a 'vezetekeger' nem talalat
    assert detect_category("vezetekeger kellene", CATALOG) == ""
    # de a sajat szavakent igen
    assert detect_category("eger kellene", CATALOG) == "Kiegészítők > Egér"


def test_tul_hosszu_elotag_mar_nem_osszetett_szo_m82c4():
    # 15 karakteres elotag > _CAT_PREFIX_MAX=12 -> nem illeszkedhet
    assert detect_category("valamilyenextranyomtato erdekel", CATALOG) == ""


def test_nem_letezo_kategoriara_nincs_talalat_m82c4():
    """m82f ELOTT: a boltban nincs 'laptop' nevu LEVEL (az 'UJ Notebook'),
    ezert ez "" volt. m82f UTAN a szulo-ut ("Laptop, Notebook") oldja fel --
    az osszetett alak (gamerLAPTOP) is, a m82c/4 elotag-szabalya szerint.
    Valoban nem letezo kategoria-nevre tovabbra is "" jar.
    """
    nb = next(c for c in CATALOG if c.startswith("Laptop") and "Notebook" in c)
    assert detect_category("Melyik a legolcsobb gamerlaptop?", CATALOG) == nb
    assert detect_category("Melyik a legolcsobb gamer laptop?", CATALOG) == nb
    assert detect_category("Melyik a legolcsobb kavefozotok?", CATALOG) == ""


def test_ures_bemenet_fail_safe_m82c4():
    assert detect_category("", CATALOG) == ""
    assert detect_category("legolcsobb nyomtato", []) == ""
    assert detect_category("mennyibe kerul a szallitas?", CATALOG) == ""

"""m79a: link_search_term egyseg-tesztek (fajl-betoltes, app-import nelkul)."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "linkterm.py"
_spec = importlib.util.spec_from_file_location("linkterm_m79", _p)
lt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lt)

Q_BAG = "melyik a legolcs\u00f3bb olyan laptop t\u00e1ska amibe belef\u00e9r egy 17\"-os laptop?"

NAMES = [
    "HP Prelude 17.3 Top Load Notebookt\u00e1ska (34Y64AA) - Maximum 17.3\" m\u00e9ret\u0171 notebookokhoz, sz\u00fcrke sz\u00ednben",
    "Lenovo ThinkPad Professional Topload Gen 2 Notebookt\u00e1ska (4X41M69795) - Maximum 16.0\" m\u00e9ret\u0171 notebookokhoz",
    "HP Everyday 16 Notebookt\u00e1ska (A08KHUT) - Maximum 16\" m\u00e9ret\u0171 notebookokhoz - Sz\u00fcrke sz\u00ednben",
    "Canyon Casual Notebookt\u00e1ska (CNE-CB5B2) - Fekete sz\u00ednben - Maximum 15.6\" m\u00e9ret\u0171 notebookokhoz",
]


def test_name_term_dominant_token():
    assert lt.link_search_term(Q_BAG, NAMES) == "Notebookt\u00e1ska"


def test_name_term_skips_numbers_and_skus():
    names = ["34Y64AA 17.3", "GX40V10007 15.6"]
    assert lt.link_search_term(Q_BAG, names) == "laptop t\u00e1ska"


def test_no_dominant_token_falls_back_to_topic():
    names = ["Alma Egyedi", "Korte Masmilyen", "Szilva Harmadik", "Barack Negyedik"]
    assert lt.link_search_term(Q_BAG, names) == "laptop t\u00e1ska"


def test_topic_fallback_strips_fillers_and_superlative():
    assert lt.link_search_term(Q_BAG, []) == "laptop t\u00e1ska"


def test_empty_inputs():
    assert lt.link_search_term("", []) == ""


def test_notebook_names_pick_notebook():
    names = [
        "HP 250R G10 Notebook (B9YP1ET) - 15.6\" FullHD, Intel Core 5-120U",
        "Lenovo V15 G4 Notebook (82YU00YWHV) - 15.6\" FullHD, AMD Ryzen 3",
        "Dell Pro 14 Notebook - Intel Core Ultra",
    ]
    assert lt.link_search_term("melyik a legolcs\u00f3bb \u00fczleti notebook?", names) == "Notebook"


def test_brand_tokens_excluded_and_longest_wins():
    names = [
        "Lenovo Legion Armoured Backpack II H\u00e1tizs\u00e1k (GX40V10007)",
        "Lenovo Legion 17 Gaming Backpack GB800 H\u00e1tizs\u00e1k (GX41U39300)",
        "Lenovo ThinkPad Professional Topload Notebookt\u00e1ska (4X41M69795)",
        "HP Prelude 17.3 Top Load Notebookt\u00e1ska (34Y64AA)",
    ]
    brands = ["Lenovo", "Lenovo", "Lenovo", "HP"]
    out = lt.link_search_term(Q_BAG, names, brands)
    assert out == "Notebookt\u00e1ska"


def test_notebook_nevek_zaj_tokenek_kizarva_m79b():
    # "Magyar billentyuzet" / "3 ev garancia" minden nevben szerepel -> zaj
    names = [
        "Lenovo V15 G4 Notebook - Magyar billenty\u0171zet - 3 \u00e9v garanci\u00e1val",
        "HP 250R G10 Notebook Magyar billenty\u0171zettel - 3 \u00e9v garanci\u00e1val",
        "Asus Vivobook Notebook Magyar billenty\u0171zet 3 \u00e9v garancia",
    ]
    t = lt.link_search_term("melyik a legolcs\u00f3bb \u00fczleti notebook?", names, [])
    assert t == "Notebook"

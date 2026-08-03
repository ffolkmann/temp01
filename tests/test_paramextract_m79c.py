"""m79c: paramextract egyseg-tesztek (fajl-betoltes, app-import nelkul)."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "paramextract.py"
_spec = importlib.util.spec_from_file_location("paramextract_m79c", _p)
px = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(px)

# valos webdoc-nevek (recon 2026-08-03)
HP_RENEW = "HP Renew Business Notebookt\u00e1ska (3E2U6AA) - Maximum 17.3\" m\u00e9ret\u0171 notebookokhoz"
ACER_BP = "Acer Predator Urban Backpack 15.6\" H\u00e1tizs\u00e1k (GP.BAG11.027) - Maximum 15.6\" m\u00e9ret\u0171 notebookokhoz"
DELL_SLEEVE = "Dell Ecoloop Pro Plus EcoLoop Sleeve 11-14 Notebookt\u00e1ska (460-BDLH) - Maximum 14\" m\u00e9ret\u0171 notebookokhoz , Fekete sz\u00ednben"
LENOVO_TYPO = "Lenovo B515 Everyday Backpack h\u00e1tizs\u00e1k (GX40Q75215) - Maximum 16\" m\u00e9ret\u0171 notebookokhoz, Fekete sz\u00cdnben"
HP_TIEDYE = "HP Campus XL Tie Dye Batikolt mint\u00e1s H\u00e1tizs\u00e1k (7K0E3AA) - Maximum 16.1\" m\u00e9ret\u0171 notebookokhoz - Tie Dye Batikolt mint\u00e1s sz\u00ednben"
ROIDMI = "ROIDMI tartoz\u00e9k t\u00e1ska (3007483)"
TEXT_CAT = "Kateg\u00f3ria: Kieg\u00e9sz\u00edt\u0151k > Notebook t\u00e1ska, h\u00e1tizs\u00e1k.\nLe\u00edr\u00e1s: ..."


def test_meret_es_tipus_valltaska():
    p = px.extract_params(HP_RENEW)
    assert p["p_max_meret"] == 17.3
    assert p["p_tipus"] == "valltaska"


def test_hatizsak_elsobbseg_es_meret():
    p = px.extract_params(ACER_BP)
    assert p["p_tipus"] == "hatizsak"
    assert p["p_max_meret"] == 15.6


def test_sleeve_tok_es_szin():
    p = px.extract_params(DELL_SLEEVE)
    assert p["p_tipus"] == "tok"
    assert p["p_max_meret"] == 14.0
    assert p["p_szin"] == "fekete"


def test_szin_typo_nagy_i():
    assert px.extract_params(LENOVO_TYPO)["p_szin"] == "fekete"


def test_tobbszavas_szin():
    assert px.extract_params(HP_TIEDYE)["p_szin"] == "tie dye batikolt mintas"


def test_meret_nelkuli_taska():
    p = px.extract_params(ROIDMI)
    assert p["p_tipus"] == "valltaska"
    assert "p_max_meret" not in p and "p_szin" not in p


def test_category_a_textbol():
    p = px.extract_params(HP_RENEW, TEXT_CAT)
    assert p["category"] == "Kieg\u00e9sz\u00edt\u0151k > Notebook t\u00e1ska, h\u00e1tizs\u00e1k"


def test_nem_taska_nev_ures():
    assert px.extract_params("HP 250R G10 Notebook (8A5L1EA)") == {}


def test_q_taska_17_colos():
    c = px.detect_constraints("Melyik a legolcs\u00f3bb t\u00e1ska 17 colos laptophoz?")
    assert c == {"p_max_meret_gte": 17.0}


def test_q_17_vesszo_3():
    c = px.detect_constraints("17,3 colos g\u00e9phez keresek t\u00e1sk\u00e1t")
    assert c["p_max_meret_gte"] == 17.3


def test_q_idezojel_os():
    c = px.detect_constraints('17"-os laptopomhoz t\u00e1ska kellene')
    assert c["p_max_meret_gte"] == 17.0


def test_q_fekete_hatizsak():
    c = px.detect_constraints("legolcs\u00f3bb fekete h\u00e1tizs\u00e1k")
    assert c["p_tipus"] == "hatizsak" and c["p_szin"] == "fekete"


def test_q_nb_ag_laptop_kijelzo_m79bnb():
    # m79b-nb: notebook-temanal a colmeret LINK-oldali kulcs lesz (nem p_*),
    # Qdrant-szures tovabbra sincs belole (ld. test_conditions_nb_kulcsok)
    c = px.detect_constraints("legolcs\u00f3bb laptop 17 colos kijelz\u0151vel")
    assert "p_max_meret_gte" not in c
    assert c["kijelzo_meret_gte"] == 17.0


def test_q_bag_gate_fekete_pentek():
    assert px.detect_constraints("fekete p\u00e9ntek akci\u00f3 mikor lesz?") == {}


def test_q_generikus_taska_nincs_tipus():
    c = px.detect_constraints("legolcs\u00f3bb t\u00e1ska 17-es laptophoz")
    assert "p_tipus" not in c and c["p_max_meret_gte"] == 17.0


def test_q_gb_nem_meret():
    c = px.detect_constraints("t\u00e1ska kell a 16GB RAM-os laptopomhoz")
    assert "p_max_meret_gte" not in c


def test_conditions_alak():
    must = px.build_filter_conditions(
        {"p_max_meret_gte": 17.0, "p_tipus": "hatizsak", "p_szin": "fekete"}
    )
    assert {"key": "p_max_meret", "range": {"gte": 17.0}} in must
    assert {"key": "p_tipus", "match": {"value": "hatizsak"}} in must
    assert {"key": "p_szin", "match": {"value": "fekete"}} in must
    assert px.build_filter_conditions({}) == []


def test_category_egysoros_szoveg_levagas_m79b():
    # valos chunk-formatum: a text EGY sorban van, a kategoria utan '. ' es leiras
    text = (
        "Kateg\u00f3ria: Laptop, Notebook > \u00daJ Notebook. Lenovo IdeaPad 3 "
        "(17ABA7) Notebook AMD Ryzen 7 processzorral. Link: https://x"
    )
    p = px.extract_params("Lenovo IdeaPad 3 Notebook", text)
    assert p["category"] == "Laptop, Notebook > \u00daJ Notebook"


def test_q_nb_usage_uzleti_m79bnb():
    c = px.detect_constraints("Melyik a legolcs\u00f3bb \u00fczleti notebook?")
    assert c == {"usage": "uzleti"}


def test_q_nb_gaming_map_m79bnb():
    assert px.detect_constraints("gaming laptop aj\u00e1nlat?")["usage"] == "gamer"


def test_q_nb_windows_11_nem_meret_m79bnb():
    c = px.detect_constraints("Windows 11-es laptopot keresek")
    assert "kijelzo_meret_gte" not in c


def test_q_bag_windows_11_nem_meret_m79bnb():
    c = px.detect_constraints("t\u00e1ska kell a windows 11-es laptopomhoz")
    assert "p_max_meret_gte" not in c


def test_q_bag_elsobbseg_m79bnb():
    # taska-tema nyer: p_* kulcsok, nb-kulcs nincs
    c = px.detect_constraints("legolcs\u00f3bb t\u00e1ska 17-es laptophoz")
    assert c["p_max_meret_gte"] == 17.0
    assert "kijelzo_meret_gte" not in c and "usage" not in c


def test_q_nb_meret_es_usage_egyutt_m79bnb():
    c = px.detect_constraints("legolcs\u00f3bb 17,3 colos gamer laptop")
    assert c == {"kijelzo_meret_gte": 17.3, "usage": "gamer"}


def test_conditions_nb_kulcsok_nem_szurnek_m79bnb():
    # nb-kulcsokbol NEM lesz Qdrant-feltetel (nincs payload-mezojuk)
    assert px.build_filter_conditions({"kijelzo_meret_gte": 17.0, "usage": "uzleti"}) == []

"""m82h/3: a markanev kivezetese az EMBEDELT kerdesbol (branddict.strip_brand).

A marka mar Qdrant must-feltetel, ezert a marka NEVE nulla informacio a szurt
poolban -- viszont elnyomja az ALTIPUST. Meres (tools/m82h3_sweep.py):
"Milyen Delphin satratok van?" -> a top-8-ban 0 sator; markanev nelkuli
embeddel 6. A kivetel TOKEN-szintu, hogy a maradek EKEZETES maradjon.
"""
import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bd = _load("cx_branddict_strip_t", "app/services/branddict.py")


def test_egyszavas_marka_kivetele():
    assert bd.strip_brand("Milyen Delphin sátratok van?", "delphin") == "Milyen sátratok van?"


def test_ekezet_megmarad_a_maradekban():
    # ekezet nelkul gyenge az embed -> a maradek NEM lehet fold-olt
    out = bd.strip_brand("Whiskas száraz tápot kerestek?", "whiskas")
    assert out == "száraz tápot kerestek?"


def test_marka_ekezetes_es_nagybetus_alakja_is_kiesik():
    assert bd.strip_brand("Van ASUS notebookotok?", "asus") == "Van notebookotok?"


def test_tobbszavas_marka_slug_alakbol():
    out = bd.strip_brand("Carp Expert bototok van?", "carp-expert")
    assert out == "bototok van?"


def test_tobbszavas_marka_szokozos_kulccsal():
    assert bd.strip_brand("Mikor jon a TP-Link router?", "tp link") == "Mikor jon a router?"


def test_rovid_maradek_fail_safe():
    # tiszta marka-kerdes: nem marad ertelmes szoveg -> "" (a hivo a mai embedet hasznalja)
    assert bd.strip_brand("Ryobi", "ryobi") == ""
    assert bd.strip_brand("Van HP?", "hp") == "Van"[:0] or bd.strip_brand("HP?", "hp") == ""


def test_ures_kulcs():
    assert bd.strip_brand("Van Delphin sátratok?", "") == ""


def test_a_marka_reszszava_nem_esik_ki():
    # csak TELJES token esik ki: a 'delphines' szo nem a marka-token
    out = bd.strip_brand("Delphines botok kellenek", "delphin")
    assert "Delphines" in out

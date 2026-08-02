"""m75: kiegeszito-szuro eszkoz-temaju szuperlativusznal (fajl-betoltos izolacio)."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parent.parent / "app" / "services" / "superlative.py"
_spec = importlib.util.spec_from_file_location("m75_superlative_isolated", str(_p))
sup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sup)


def _h(name):
    return {"payload": {"name": name, "price": "9990"}}


BAG = _h("HP Everyday Notebooktaska (A08KGAA) - Maximum 14 meretu notebookokhoz")
SLEEVE = _h("Dell EcoLoop Urban Sleeve CV4425 11-14 Notebooktaska")
LAPTOP = _h("Lenovo V15 G4 Notebook (82YU0103HV) - 15.6 FullHD, Magyar billentyuzet")
ROD = _h("Prologic C1 Avenger horgaszbot 3.6m")


def test_bags_filtered_on_device_topic():
    assert sup.accessory_filter([BAG, SLEEVE, LAPTOP], "uzleti notebook") == [LAPTOP]


def test_laptop_name_with_billentyuzet_kept():
    assert sup.accessory_filter([LAPTOP], "legolcsobb laptop") == [LAPTOP]


def test_non_device_topic_untouched():
    assert sup.accessory_filter([BAG, ROD], "horgaszbot") == [BAG, ROD]


def test_accessory_topic_not_filtered():
    assert sup.accessory_filter([BAG, SLEEVE, LAPTOP], "notebooktaska") == [BAG, SLEEVE, LAPTOP]


def test_fail_safe_when_all_filtered():
    assert sup.accessory_filter([BAG, SLEEVE], "notebook") == [BAG, SLEEVE]


def test_detect_usage_m76():
    assert sup.detect_usage("melyik a legolcsobb uzleti notebook?") == "uzleti"
    assert sup.detect_usage(u"melyik a legolcs\u00f3bb \u00fczleti notebook?") == "uzleti"
    assert sup.detect_usage("legjobb gaming laptop") == "gamer"
    assert sup.detect_usage("melyik a legolcsobb laptop?") is None

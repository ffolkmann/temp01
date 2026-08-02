"""m73: OOS_GUARD mod letezik es a keszlet-kenyszerites feltetelei epek.

Fajl-betoltos izolacio: a suite mas tesztjei fake `app` modulokat hagyhatnak a
sys.modules-ben (test_stats harness), ezert NEM az app csomagon at importalunk.
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parent.parent / "app" / "services" / "superlative.py"
_spec = importlib.util.spec_from_file_location("m73_superlative_isolated", str(_p))
sup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sup)


def test_oos_guard_note_exists():
    assert sup.OOS_GUARD == "oos_guard"
    assert sup.OOS_GUARD in sup.STOCK_NOTES
    assert "rakt" in sup.STOCK_NOTES[sup.OOS_GUARD].lower()
    assert "TILOS" in sup.STOCK_NOTES[sup.OOS_GUARD]


def test_detect_stock_filter_still_words_only():
    assert sup.detect_stock_filter("melyik a legolcsobb raktaron levo laptop?") is True
    assert sup.detect_stock_filter("melyik a legolcsobb uzleti notebook?") is False

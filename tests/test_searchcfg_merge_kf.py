"""A SmartSearch admin-mentes nem dobhatja el az urlapon kivuli kulcsokat.

Regresszio: 2026-08-06-on a search_config.shoprenter.categories eltunt egy
admin-mentessel, es a copygo index-build masnap hajnalban elhasalt.
"""
import importlib.util as _ilu
import pathlib as _pl

_P = _pl.Path(__file__).resolve().parents[1] / "app" / "services" / "searchcfg.py"
_spec = _ilu.spec_from_file_location("searchcfg_kf", _P)
searchcfg = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(searchcfg)


def test_platform_blokk_megmarad():
    old = {"enabled": True, "shoprenter": {"categories": [3408, 3420]}, "min_ratio": 0.5}
    new = {"enabled": False, "synonyms": []}
    out = searchcfg.merge_preserving(old, new)
    assert out["shoprenter"] == {"categories": [3408, 3420]}
    assert out["min_ratio"] == 0.5
    assert out["enabled"] is False        # az urlap ertekei nyernek
    assert out["synonyms"] == []


def test_ismeretlen_uj_kulcs_is_vedett():
    old = {"valami_uj_blokk": {"x": 1}}
    out = searchcfg.merge_preserving(old, {"enabled": True})
    assert out["valami_uj_blokk"] == {"x": 1}


def test_nincs_regi_config():
    out = searchcfg.merge_preserving(None, {"enabled": True})
    assert out == {"enabled": True}


def test_ures_regi_config():
    out = searchcfg.merge_preserving({}, {"enabled": True, "synonyms": []})
    assert out == {"enabled": True, "synonyms": []}

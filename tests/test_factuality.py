"""factuality (m33) — a minden tenantra érvényes tény-korlát blokk.

PURE modul, fájlból töltjük (a többi teszt `app.services` stubot rak a sys.modules-ba).
"""

import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "factuality.py"
_spec = importlib.util.spec_from_file_location("factuality_under_test", _P)
_f = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_f)


def test_van_fejlec_es_nem_ures():
    b = _f.factuality_block()
    assert b.startswith("\n\n# TENYEK ES ALTALANOSITAS\n")
    assert len(b) > 600


def test_engedi_a_sajat_prompt_es_a_tudasbazis_tenyeit():
    """kellegyszerszam/fishingoutlet: a feltetelek a promptjukban / tudasbazisukban vannak."""
    b = _f.factuality_block()
    assert "a fenti utasitasaid vagy a TUDASBAZIS" in b


def test_tiltja_a_marka_altalanositast():
    b = _f.factuality_block()
    assert "SOHA ne altalanosits a markara" in b
    assert "3 ev garancia jar" in b  # konkret ellenpelda a promptban


def test_tiltja_a_sugallo_kerdes_megerositeset():
    assert "NE erositsd meg, ha nincs ra adatod" in _f.factuality_block()


def test_tiltja_a_becsult_osszeget():
    b = _f.factuality_block()
    assert "SOHA ne irj le olyan osszeget, hataridot vagy szazalekot" in b
    assert 'se "kb."-t' in b


def test_tiltja_a_szervizfolyamat_kitalalasat():
    assert "szervizfolyamatot es javitasi vallalast soha ne" in _f.factuality_block()


def test_nincs_benne_ekezet_a_szabalyszovegben():
    """A tobbi kod-fuzott blokk is ekezet nelkuli; a '—' kotojel kivetel."""
    body = _f.factuality_block()
    tiltott = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")
    assert not (set(body) & tiltott), "ekezetes karakter a blokkban"


def test_idempotens():
    assert _f.factuality_block() == _f.factuality_block() == _f.BLOCK

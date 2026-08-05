"""m82d/2: 4 betus toldalek-tures + "pro" szinonima a facets-szotarban.

A m82d elomeres (tools/m82d_nonsuper.py) ket recall-rest talalt a nem-szuperlativusz
kerdeseknel:
  "Milyen lezernyomtatoITOK vannak?"   -> a birtokos tobbes 4 betu, a _SUF_MAX 3 volt
  "Windows 11 PRO-s gepet szeretnek"   -> a "pro" a slugbol nem vezetheto le

A tures TOVABBRA IS aszimmetrikus es hossz-fuggo: csak a >= _SUF_MIN (7) karakteres
ertekek zaro-hatara lazul, mert rovid ertekeknel a toldalek MAS SZOT csinal --
  intel (5) + "ligens" -> "intelligens"  (496 termek szurese egy KB-kerdesre)
  pla   (3) + "zma"    -> "plazma"
A 4 betu TUDATOS felso hatar: 5-6 betus toldaleknal a szo-utkozes kockazata gyorsan no,
ezert a "...itokat" (+6) alak SZANDEKOSAN nem illeszkedik.

Meres a valodi 85-kategorias terkepen (tools/m82d2_sweep.py):
  pozitiv 12/17 -> 16/17, negativ 26/26, kimerito FP-scan 0/2210 par.

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


_fd = _load("facetdict_m82d2_under_test", "app/services/facetdict.py")

CAT_NB = "Laptop, Notebook > UJ Notebook"
CAT_NYO = "Nyomtato > Nyomtato"

# A darabszamok ugy vannak beallitva, hogy a szelektivitas-kapu (>= 80% a kategoria-
# median) egyik tesztelt erteket se ejtse ki -- az `intel` is bent van, kulonben a
# _SUF_MIN vedelmet nem is merne a negativ eset.
FMAP = {
    "client_id": "t",
    "categories": {
        "uj-notebook": {
            "url": "/laptop-notebook/uj-notebook-c100",
            "facets": {
                "operacios-rendszer": {
                    "windows-11-professional": 300, "windows-11-home": 400, "mac-os-x": 20,
                },
                "grafikus-vezerlo-gyarto": {"intel": 496, "nvidia": 209},
                "extrak": {"ujjlenyomat-olvaso": 425, "nfc": 23},
            },
        },
        "nyomtato": {
            "url": "/nyomtato-c200",
            "facets": {
                "nyomtatasi-technologia": {"lezer": 65, "tintasugaras": 90, "led": 12},
                "szinkeszlet": {"fekete": 40, "szines": 50},
            },
        },
    },
}


def _tags(msg, cat):
    return _fd.detect_facet_tags(msg, [cat] * 5, FMAP, category=cat)


def test_negy_betus_toldalek_illeszkedik_hosszu_ertekre():
    """Targyeset tobbes (-okat) es birtokos tobbes (-itok) -- mindketto 4 betu."""
    assert "nyomtatasi-technologia:tintasugaras" in _tags(
        "milyen tintasugarasokat arultok?", CAT_NYO)
    # a "lezernyomtato" szinoniman keresztul (m82c/3), szinten +4 toldalekkal
    assert "nyomtatasi-technologia:lezer" in _tags(
        "milyen lezernyomtatoitok vannak?", CAT_NYO)


def test_hat_betus_toldalek_mar_nem_illeszkedik():
    """TUDATOS felso hatar: a _SUF_MAX 4, nem 6."""
    assert _tags("a lezernyomtatoitokat nezegetem", CAT_NYO) == []


def test_rovid_erteket_tovabbra_is_vedi_a_suf_min():
    """intel (5) + 'ligens' -> 'intelligens': a _SUF_MIN kapu valtozatlan."""
    assert _tags("melyik a legjobb intelligens megoldas?", CAT_NB) == []
    assert _tags("milyen intelligensebb megoldasokat ajanlotok?", CAT_NB) == []


def test_pro_szinonima_a_professionalra_illeszkedik():
    for msg in ("windows 11 pro-s gepet szeretnek", "windows 11 pro laptopot keresek"):
        tags = _tags(msg, CAT_NB)
        assert "operacios-rendszer:windows-11-professional" in tags, msg
        assert "operacios-rendszer:windows-11-home" not in tags, msg


def test_professional_teljes_alak_valtozatlan():
    """m82c/3 regresszio: a kanonikus alak eddig is mukodott."""
    assert "operacios-rendszer:windows-11-professional" in _tags(
        "windows 11 professional laptop", CAT_NB)


def test_professzionalis_szo_nem_ad_cimket():
    """A 'pro' szinonima csak a 'windows 11' elotaggal egyutt hat."""
    assert _tags("professzionalis tanacsot kerek", CAT_NB) == []
    assert _tags("profi gepet szeretnek", CAT_NB) == []


def test_suf_max_erteke_dokumentalva():
    """A hatar a kodban is legyen egyertelmu (a sweep erre hivatkozik)."""
    assert _fd._SUF_MIN == 7
    assert _fd._SUF_MAX == 4

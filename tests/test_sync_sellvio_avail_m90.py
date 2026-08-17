"""m90: Sellvio készlet-jel — `is_available_for_order` -> bool `available` payload.

Miért: a 3 Sellvio tenantnak (teslashop, plcomfort, mastercool — 11 422 pont) MA
semmilyen készlet-mezője nincs a payloadban, ezért a m60 (available-szűrt pool),
a m64 (available-boost) és a m73 (OOS-tiltás) Qdrant-ága néma. Az api/v2 /products
darabszámot nem ad, csak ezt a boolt (élesben ellenőrizve: 59 mező, plcomfort 77%
elérhető, mastercool 94%, teslashop 100% — dropship).

Két dolgot rögzít a teszt:
  (1) az `available` payload-mező helyes (hiányzó mező -> NINCS mező, m84-szabály),
  (2) az elérhetőség BENNE VAN a ps_hash-ben -> a váltás payload-only PS-frissítést
      vált ki (nincs újra-embedding), a content_hash viszont VÁLTOZATLAN marad.

A parity/m84-teszt mintájára fájl-betöltéssel (a suite más tesztjei fake app.sync-et
hagyhatnak a sys.modules-ben).
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])
for n in ("app", "app.sync"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


_load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
_load("app.sync.textutil", f"{ROOT}/app/sync/textutil.py")
models = _load("app.sync.models", f"{ROOT}/app/sync/models.py")
builders = _load("app.sync.builders", f"{ROOT}/app/sync/builders.py")

CID = "teslashop"


def _row(avail=None, **kw):
    r = {
        "id": "4711",
        "name": "Teszt termek",
        "code": "SKU-4711",
        "pretty_url": "https://teslashop.hu/termek/teszt-4711",
        "price": {"brutto_price": 12990, "discount": 0},
        "is_visible": True,
        "lead_text": "Rovid leiras.",
    }
    if avail is not None:
        r["is_available_for_order"] = avail
    r.update(kw)
    return r


def _one(row):
    ps = builders.build_sellvio([row], CID)
    assert len(ps) == 1
    return ps[0]


def _payload(row):
    return models.build_payload(CID, _one(row))


def test_elerheto_true():
    assert _payload(_row(True))["available"] is True


def test_nem_elerheto_false():
    assert _payload(_row(False))["available"] is False


def test_hianyzo_mezo_nem_ir_payloadot():
    """m84-szabály: nincs készlet-adat -> NEM írunk mezőt (a szűrő fail-safe marad)."""
    assert "available" not in _payload(_row())


def test_string_ertekek():
    """Defenzív: a bool("0") True lenne — a stringes forrás-értéket is helyesen olvassuk."""
    assert _payload(_row("0"))["available"] is False
    assert _payload(_row("false"))["available"] is False
    assert _payload(_row("1"))["available"] is True
    assert _payload(_row("true"))["available"] is True
    assert "available" not in _payload(_row(""))


def test_ps_hash_valtozik_az_elerhetoseggel():
    """Enélkül a nightly sync SOHA nem frissítené a meglévő pontok available mezőjét."""
    a = _one(_row(True)).ps_hash_str
    b = _one(_row(False)).ps_hash_str
    c = _one(_row()).ps_hash_str
    assert a != b
    assert a != c and b != c


def test_content_hash_es_text_valtozatlan():
    """Az elérhetőség NEM szemantikus mező -> nincs újra-embedding."""
    t, f = _one(_row(True)), _one(_row(False))
    assert t.content_hash == f.content_hash
    assert t.text == f.text
    assert "available" not in t.text


def test_akcios_ar_ag_erintetlen():
    """A ps_hash discount-szelete a helyén marad (m23), csak az avail-szelet új."""
    d = _one(_row(True, price={"brutto_price": 9990, "discount": "2000"}))
    n = _one(_row(True, price={"brutto_price": 9990, "discount": 0}))
    assert d.ps_hash_str != n.ps_hash_str
    assert "AKCIÓS ár" in d.text

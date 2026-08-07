"""m84: egyseges keszlet-jel — a sync payload `available` mezoje SR/Unas stockbol is.

Miert: a Qdrant `available_only` szuroje CSAK a bool `available`-re megy, a `stock`
string payload -> a m60/m64/m73 keszlet-agai nemak voltak minden Shoprenter/Unas
tenantnal (eles meres: kellegyszerszam kontextus 38% elerheto, 22% mind-kifuto).

A parity-teszt mintajara fajl-betoltessel (a models.py stdlib+app importokkal).
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

SP = models.SourceProduct


def test_derive_available_tabla():
    d = models.derive_available
    # platform-adta bool nyer, a stock nem irja felul
    assert d(True, "0") is True
    assert d(False, "5") is False
    # SR/Unas: szamszeru stockbol szarmaztatunk
    assert d(None, "3") is True
    assert d(None, "10") is True
    assert d(None, "0") is False
    assert d(None, "1,5") is True      # vesszos tizedes (Unas-formatum)
    assert d(None, " 2 ") is True      # szokozos
    assert d(None, "-1") is False
    # nincs keszlet-adat -> None: NEM irunk mezot (Sellvio)
    assert d(None, "") is None
    assert d(None, None) is None
    assert d(None, "keszleten") is None
    assert d(None, "n/a") is None


def test_build_payload_unas_stockbol_available():
    """Unas (stock string, available nincs) -> a payloadba bool available kerul."""
    p_in = SP(id_key="1", sku="S1", name="Furo", url="u", price="1000",
              stock_str="3", text="t", content_hash="h",
              filename="__unas_products__")
    pl = models.build_payload("kellegyszerszam", p_in)
    assert pl["available"] is True
    assert pl["stock"] == "3"          # a nyers stock is marad (m58)

    p_out = SP(id_key="2", sku="S2", name="Kalapacs", url="u", price="1000",
               stock_str="0", text="t", content_hash="h",
               filename="__unas_products__")
    assert models.build_payload("kellegyszerszam", p_out)["available"] is False


def test_build_payload_sellvio_nincs_keszlet_adat():
    """Sellvio: se available, se stock -> `available` kulcs NEM kerulhet a payloadba."""
    p_in = SP(id_key="3", sku="S3", name="Huzat", url="u", price="1000",
              text="t", content_hash="h", platform_id_field="sellvio_id",
              platform_id_value="3", filename="__sellvio_products__")
    pl = models.build_payload("teslashop", p_in)
    assert "available" not in pl
    assert "stock" not in pl


def test_build_payload_webdoc_valtozatlan():
    """Webdoc/Woo: a platform adja az available-t -> byte-valtozatlan viselkedes."""
    wd = builders.build_webdoc(
        [{"id": "1", "name": "Laptop", "price_gross": 100, "available": False}], "c")[0]
    pl = models.build_payload("notebookstore", wd)
    assert pl["available"] is False
    assert "stock" not in pl


def test_shoprenter_osszegzett_stock_dont():
    """SR: a stock a NEGY raktar osszege (sr_warehouse_note) -> a szarmaztatas
    tobbraktaras esetben is helyes: 0+6 -> raktaron."""
    st, _note = builders.sr_warehouse_note(
        {"stock1": "0", "stock2": "6", "stock3": "0", "stock4": "0"}, None)
    assert st == "6"
    assert models.derive_available(None, st) is True
    st0, _n0 = builders.sr_warehouse_note(
        {"stock1": "0", "stock2": "0", "stock3": "0", "stock4": "0"}, None)
    assert models.derive_available(None, st0) is False


def test_ps_payload_is_szarmaztat():
    """A 2 orankenti PriceStock-merge ugyanazt a jelet irja (kulonben elavulna)."""
    try:
        from app.sync.engine import _ps_payload
    except Exception:  # noqa: BLE001 — nehez fuggosegek nelkul is fusson a tobbi teszt
        import pytest
        pytest.skip("app.sync.engine nem importalhato ebben a kornyezetben")
    p_in = SP(id_key="1", sku="S1", name="Furo", url="u", price="1000",
              stock_str="7", text="t", content_hash="h", ps_hash_str="ph",
              filename="__unas_products__")
    pl = _ps_payload(p_in)
    assert pl["available"] is True and pl["stock"] == "7"
    p_out = SP(id_key="2", sku="S2", name="X", url="u", price="1", stock_str="0",
               text="t", content_hash="h", ps_hash_str="ph2",
               filename="__unas_products__")
    assert _ps_payload(p_out)["available"] is False

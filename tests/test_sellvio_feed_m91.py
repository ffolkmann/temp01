"""m91: Sellvio B2B feed — készlet-térkép elemzés, usable-kapu, builder-bekötés.

A `quantity` CSAK ott valódi, ahol a bolt vezet készletet ÉS a token raktár-szűrés
nélkül készült; dropship boltnál minden 0, miközben minden rendelhető. Ezért a
csupa-nulla feed NEM használható készletre — ezt a `usable` kapu védi, és ez a
teszt-készlet legfontosabb esete.
"""
import asyncio
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


feed = _load("sellvio_feed_m91", f"{ROOT}/app/services/sellvio_feed.py")
_load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
_load("app.sync.textutil", f"{ROOT}/app/sync/textutil.py")
models = _load("app.sync.models", f"{ROOT}/app/sync/models.py")
builders = _load("app.sync.builders", f"{ROOT}/app/sync/builders.py")

feed._RETRY_SLEEP = 0  # a teszt ne aludjon


def _fr(pid, sku, qty):
    return {"id": pid, "article_number": sku, "quantity": qty, "name": "x"}


# --------------------------------------------------------------------------- #
# feed-elemzés
# --------------------------------------------------------------------------- #
def test_borítek_valtozatok():
    rows = [_fr(1, "A-1", 3)]
    for body in (rows, {"products": rows}, {"data": rows}, {"data": {"items": rows}}):
        assert feed.parse_feed(body).count == 1, body


def test_qty_id_es_cikkszam_alapjan():
    sm = feed.parse_feed([_fr(11, "SKU-11", 4), _fr(12, "SKU-12", 0)])
    assert sm.qty(11) == 4 and sm.qty("11") == 4
    assert sm.qty(None, "SKU-11") == 4
    assert sm.qty(12) == 0
    assert sm.qty(999) is None and sm.qty(None, "NINCS") is None


def test_toleráns_ertekek():
    sm = feed.parse_feed([_fr(1, "A", "3"), _fr(2, "B", " 5 "), _fr(3, "C", "izé"), _fr(4, "D", -2)])
    assert sm.qty(1) == 3 and sm.qty(2) == 5
    assert sm.qty(3) is None      # nem szam -> nincs adat (nem 0!)
    assert sm.qty(4) == 0         # negativ keszlet -> 0


def test_usable_kapu_csupa_nulla():
    """A LEGFONTOSABB eset: dropship bolt / raktar-szurt token -> NEM hasznaljuk."""
    dropship = feed.parse_feed([_fr(i, f"S{i}", 0) for i in range(50)])
    assert dropship.count == 50 and dropship.nonzero == 0
    assert dropship.usable is False
    valodi = feed.parse_feed([_fr(1, "A", 0), _fr(2, "B", 7)])
    assert valodi.usable is True
    assert feed.parse_feed([]).usable is False
    assert feed.StockMap(error="boom").usable is False


def test_feed_url():
    assert feed.feed_url("https://bolt.hu/") == "https://bolt.hu/api/hu/products"
    assert feed.feed_url("https://bolt.hu", "en") == "https://bolt.hu/api/en/products"


# --------------------------------------------------------------------------- #
# lehúzás (fake klienssel — a hívó adja be, konfprobe-minta)
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, payload=None, boom=False):
        self._p, self._boom = payload, boom

    def raise_for_status(self):
        return None

    def json(self):
        if self._boom:
            raise ValueError("nem JSON (One moment, please...)")
        return self._p


class _Client:
    def __init__(self, *responses):
        self._r, self.calls = list(responses), 0

    async def get(self, url, params=None, headers=None):
        self.calls += 1
        self.last = (url, params, headers)
        return self._r[min(self.calls - 1, len(self._r) - 1)]


def test_fetch_ok():
    c = _Client(_Resp({"products": [_fr(1, "A", 2)]}))
    sm = asyncio.run(
        feed.fetch_stock_map(c, "https://bolt.hu/", "KULCS"))
    assert sm.count == 1 and sm.qty(1) == 2
    url, params, headers = c.last
    assert url == "https://bolt.hu/api/hu/products"
    assert params["api_key"] == "KULCS" and params["output_type"] == "json"
    assert "Mozilla" in headers["User-Agent"]      # bot-kapu miatt kotelezo


def test_fetch_botkapu_utan_retry_sikeres():
    c = _Client(_Resp(boom=True), _Resp([_fr(9, "Z", 1)]))
    sm = asyncio.run(
        feed.fetch_stock_map(c, "https://bolt.hu", "K"))
    assert c.calls == 2 and sm.qty(9) == 1


def test_fetch_hiba_nem_dob():
    c = _Client(_Resp(boom=True), _Resp(boom=True))
    sm = asyncio.run(
        feed.fetch_stock_map(c, "https://bolt.hu", "K"))
    assert sm.error and sm.usable is False


# --------------------------------------------------------------------------- #
# builder-bekötés
# --------------------------------------------------------------------------- #
CID = "mastercool"


def _row(pid="4711", sku="SKU-4711", avail=True):
    return {"id": pid, "name": "Teszt termek", "code": sku,
            "pretty_url": "https://bolt.hu/termek/4711",
            "price": {"brutto_price": 9990, "discount": 0},
            "is_visible": True, "is_available_for_order": avail}


def _payload(rows, stock_map=None):
    ps = builders.build_sellvio(rows, CID, "", stock_map=stock_map)
    return models.build_payload(CID, ps[0])


def test_stock_a_payloadba_kerul():
    sm = feed.parse_feed([_fr("4711", "SKU-4711", 6)])
    pl = _payload([_row()], sm)
    assert pl["stock"] == "6"
    assert pl["available"] is True


def test_kulcs_nelkul_nincs_stock():
    pl = _payload([_row()])
    assert "stock" not in pl
    assert pl["available"] is True


def test_a_stock_NEM_irja_felul_az_elerhetoseget():
    """Dropship-vedelem: 0 darab + rendelheto -> available MARAD True."""
    sm = feed.parse_feed([_fr("4711", "SKU-4711", 0), _fr("x", "y", 3)])
    pl = _payload([_row(avail=True)], sm)
    assert pl["stock"] == "0"
    assert pl["available"] is True


def test_ps_hash_koveti_a_keszletet_de_a_content_hash_nem():
    a = builders.build_sellvio([_row()], CID, "", stock_map=feed.parse_feed([_fr("4711", "S", 1)]))[0]
    b = builders.build_sellvio([_row()], CID, "", stock_map=feed.parse_feed([_fr("4711", "S", 9)]))[0]
    assert a.ps_hash_str != b.ps_hash_str      # keszlet-valtas -> payload-frissites
    assert a.content_hash == b.content_hash    # de NINCS ujra-embedding
    assert a.text == b.text


def test_kulcs_nelkuli_ps_hash_valtozatlan_marad():
    """Nincs churn azoknal a tenantoknal, ahol nincs B2B kulcs (m90-es alak)."""
    from app.sync.hashing import ps_hash
    p = builders.build_sellvio([_row()], CID)[0]
    assert p.ps_hash_str == ps_hash("9990", "1", "")

"""S4 tesztek: webdoc ingest-mapper (feed-url, prefixek, higienia) + Uj-badge.

Fajl-betoltos import (S1-minta) — nem az app-csomagon at, hogy a fake-app-os
tesztfajlok sys.modules-szennyezese ne torje.
"""
import asyncio
import importlib.util
import json
import pathlib

_BASE = pathlib.Path(__file__).resolve().parents[1] / "app" / "search"


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, _BASE / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ic = _load("ss_indexcore_wd_t", "indexcore.py")
wd = _load("ss_webdoc_t", "webdoc.py")


class _T:
    """Tenant-duck: csak azok a mezok, amiket a mapper olvas."""

    def __init__(self, api_base="https://shop.hu/export/tok.json",
                 public_url="", domain="shop.hu"):
        self.api_base = api_base
        self.public_url = public_url
        self.domain = domain


# --------------------------------------------------------------------------- #
# feed-url
# --------------------------------------------------------------------------- #
def test_feed_url_az_api_basebol():
    assert wd.feed_url(_T()) == "https://shop.hu/export/tok.json"


def test_feed_url_tcfg_felulirja():
    assert wd.feed_url(_T(), {"feed_url": "https://masik.hu/f.json"}) == "https://masik.hu/f.json"


def test_feed_url_hianyzik_vagy_rossz():
    for bad in ("", "   ", "ftp://shop.hu/f.json", "shop.hu/f.json"):
        try:
            wd.feed_url(_T(api_base=bad))
        except RuntimeError as e:
            assert "feed-url" in str(e)
        else:
            raise AssertionError("nem dobott: %r" % bad)


# --------------------------------------------------------------------------- #
# prefixek
# --------------------------------------------------------------------------- #
def test_prefixek_domainbol():
    assert wd.prefixes(_T()) == ("https://shop.hu/", "https://shop.hu/services/img-export/")


def test_prefixek_public_url_elsobbseget_elvez():
    up, ip = wd.prefixes(_T(public_url="https://www.shop.hu/"))
    assert up == "https://www.shop.hu/" and ip == "https://www.shop.hu/services/img-export/"


def test_prefixek_tcfg_felulirja():
    up, ip = wd.prefixes(_T(), {"url_prefix": "https://a.hu/", "img_prefix": "https://cdn.hu/i/"})
    assert (up, ip) == ("https://a.hu/", "https://cdn.hu/i/")


def test_prefixek_domain_nelkul_uresek():
    assert wd.prefixes(_T(domain="")) == ("", "")


# --------------------------------------------------------------------------- #
# higienia
# --------------------------------------------------------------------------- #
def test_clean_products_kiszuri_a_szemetet():
    payload = {"products": [{"id": 1, "name": "A"}, {"id": None}, {"id": "  "},
                            "nem dict", None, {"sku": "nincs id"}, {"id": "7"}]}
    assert wd.clean_products(payload) == [{"id": 1, "name": "A"}, {"id": "7"}]


def test_clean_products_nyers_lista_es_szemet():
    assert wd.clean_products([{"id": 3}]) == [{"id": 3}]
    for bad in ("szoveg", 42, None, {"products": "nem lista"}, {}):
        assert wd.clean_products(bad) == []


# --------------------------------------------------------------------------- #
# fetch (fake httpx-kliens) + index-lanc
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


class _Client:
    """httpx.AsyncClient helyettesito: rogziti a hivott url-t."""

    calls = []

    def __init__(self, payload):
        self._p = payload

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        _Client.calls.append(url)
        return _Resp(self._p)


def test_fetch_letolt_es_tisztit(monkeypatch):
    _Client.calls = []
    payload = {"products": [{"id": 1, "name": "A", "available": True}, {"id": None}]}
    monkeypatch.setattr(wd.httpx, "AsyncClient", _Client(payload), raising=False)
    products, up, ip = asyncio.run(wd.fetch(_T()))
    assert products == [{"id": 1, "name": "A", "available": True}]
    assert up == "https://shop.hu/" and ip == "https://shop.hu/services/img-export/"
    assert _Client.calls == ["https://shop.hu/export/tok.json"]


def test_uj_badge_first_seen_registryvel(tmp_path):
    """A webdoc feed nem ad created_day-t -> az indexcore registryje adja a 'd'-t."""
    p1 = {"id": 1, "name": "A", "available": True, "price_gross": 100,
          "url": "https://shop.hu/a", "image_url": "https://shop.hu/services/img-export/a.jpg"}
    res = ic.build_index("nbs", [p1], str(tmp_path), "https://shop.hu/",
                         "https://shop.hu/services/img-export/")
    assert res["count"] == 1 and res["new_ids"] == 0          # elso futas: minden "regi"
    rows = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["products"]
    assert rows[0]["d"] == 0 and rows[0]["u"] == "a" and rows[0]["m"] == "a.jpg"

    p2 = {"id": 2, "name": "B", "available": True, "price_gross": 200}
    res2 = ic.build_index("nbs", [p1, p2], str(tmp_path), "https://shop.hu/",
                          "https://shop.hu/services/img-export/")
    assert res2["new_ids"] == 1                                # a 2-es termek most jelent meg
    rows2 = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["products"]
    days = {r["i"]: r["d"] for r in rows2}
    assert days["1"] == 0 and days["2"] > 0
    assert (tmp_path / "first_seen.json").exists()

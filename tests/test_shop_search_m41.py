# m41: shoprenter link-extraction -- onlink/lapozo kiszurese + read-timeout 15s.
# Eles meres (2026-07-14): copygo 'fotonyomtato' talalati oldal 11.4s (a 10s timeout
# elvagta), es a 0-talalatos oldal ONLINKJE miatt a query-kaszkad megallt.
# A modult fajlbol toltjuk, MINDEN fuggoseget (httpx-et is!) ideiglenes fake-kel
# (save/restore), mert a suite mas tesztjei is fake-elhetik ezeket a sys.modules-ban.

import importlib.util
import pathlib
import sys
import types

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "shop_search.py"


def _mk(name, **attrs):
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


class _FakeTimeout:
    def __init__(self, timeout=None, *, connect=None, read=None, write=None, pool=None):
        self.connect = connect if connect is not None else timeout
        self.read = read if read is not None else timeout
        self.write = write if write is not None else timeout
        self.pool = pool if pool is not None else timeout


_FAKES = {
    "httpx": _mk("httpx", Timeout=_FakeTimeout, AsyncClient=object),
    "app": _mk("app"),
    "app.core": _mk("app.core"),
    "app.core.qdrant": _mk("app.core.qdrant", get_qdrant=lambda: None),
    "app.services": _mk("app.services"),
    # a normalizalast a current_product sajat tesztje fedi -- itt csak query-vagas
    "app.services.current_product": _mk(
        "app.services.current_product", normalize_url=lambda u: str(u).split("?")[0]
    ),
    "app.services.platform_api": _mk("app.services.platform_api", sellvio_token=None),
    "app.services.search_query": _mk(
        "app.services.search_query", search_queries=lambda p, q: [q]
    ),
}

_saved = {k: sys.modules.get(k) for k in _FAKES}
sys.modules.update(_FAKES)
try:
    _spec = importlib.util.spec_from_file_location("shop_search_m41_under_test", _P)
    _s = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_s)
finally:
    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

BASE = "https://copygo.hu"


def test_onlink_es_lapozo_kiszurve_termek_marad():
    html = (
        '<a href="https://copygo.hu/index.php?route=product/list&keyword=x">kereso</a>'
        '<a href="https://copygo.hu/index.php?route=product/list&keyword=x&page=2#content">2</a>'
        '<a href="https://copygo.hu/canon-selphy-cp1500-fotonyomtato-feher-134712?keyword=x">p1</a>'
        '<a href="https://copygo.hu/canon-zoemini-2-fotonyomtato-rozsaarany-135189?keyword=x">p2</a>'
    )
    out = _s._extract_links("shoprenter", html, BASE)
    assert out == [
        "https://copygo.hu/canon-selphy-cp1500-fotonyomtato-feher-134712",
        "https://copygo.hu/canon-zoemini-2-fotonyomtato-rozsaarany-135189",
    ]


def test_csak_onlink_eseten_ures_a_kaszkad_tovabblephet():
    html = '<a href="https://copygo.hu/index.php?route=product/list&keyword=nincs">kereso</a>'
    assert _s._extract_links("shoprenter", html, BASE) == []


def test_dedup_es_sorrend():
    html = (
        '<a href="https://copygo.hu/a-111?keyword=x">a</a>'
        '<a href="https://copygo.hu/b-222?keyword=x">b</a>'
        '<a href="https://copygo.hu/a-111?keyword=x">a2</a>'
    )
    assert _s._extract_links("shoprenter", html, BASE) == [
        "https://copygo.hu/a-111",
        "https://copygo.hu/b-222",
    ]


def test_timeout_15s_read_5s_connect():
    assert _s._TIMEOUT.read == 15.0
    assert _s._TIMEOUT.connect == 5.0

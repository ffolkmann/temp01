# -*- coding: utf-8 -*-
"""m112 — rendelés-státusz levél: Reply-To a bolt értesítési címére, feladó-név.

A modulokat FÁJLBÓL töltjük; a sys.modules-t csak context managerben piszkáljuk
(lásd tests/test_m101.py _fake_modules), a végén visszaállítjuk.
"""

import asyncio
import contextlib
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def _fake_modules(mods: dict):
    saved = {k: sys.modules.get(k) for k in mods}
    try:
        sys.modules.update(mods)
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _pkg(name):
    m = types.ModuleType(name)
    m.__path__ = []
    return m


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ mailer
class _Settings:
    mailgun_api_key = "key-test"
    mailgun_base_url = "https://api.eu.mailgun.net"
    mailgun_domain = "codexpress.hu"
    mailgun_from = "noreply@codexpress.hu"


def _load_mailer():
    st = types.ModuleType("app.core.settings")
    st.get_settings = lambda: _Settings()
    with _fake_modules({"app": _pkg("app"), "app.core": _pkg("app.core"), "app.core.settings": st}):
        return _load("app/core/mailer.py", "mailer_m112_under_test")


def test_format_from():
    m = _load_mailer()
    assert m.format_from("noreply@codexpress.hu", "NagyonÁllatShop asszisztens") == \
        '"NagyonÁllatShop asszisztens" <noreply@codexpress.hu>'
    assert m.format_from("CX <noreply@codexpress.hu>", "Bolt") == '"Bolt" <noreply@codexpress.hu>'
    assert m.format_from("noreply@codexpress.hu", "") == "noreply@codexpress.hu"
    # fejléc-törő karakterek kimaradnak
    assert m.format_from("noreply@codexpress.hu", 'Rossz"<x>\r\nBcc: a@b.hu') == \
        '"Rossz x Bcc: a@b.hu" <noreply@codexpress.hu>'


def _capture_send(m, **kw):
    sent = {}

    class _Resp:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, auth=None, data=None):
            sent["url"], sent["data"] = url, data
            return _Resp()

    old = m.httpx.AsyncClient
    m.httpx.AsyncClient = _Client
    try:
        ok = asyncio.run(m.send_email("vevo@example.com", "Tárgy", "szöveg", **kw))
    finally:
        m.httpx.AsyncClient = old
    return ok, sent


def test_send_email_reply_to_header():
    m = _load_mailer()
    ok, sent = _capture_send(m, reply_to="info@bolt.hu", from_name="Bolt")
    assert ok is True
    assert sent["data"]["h:Reply-To"] == "info@bolt.hu"
    assert sent["data"]["from"] == '"Bolt" <noreply@codexpress.hu>'


def test_send_email_without_reply_to_unchanged():
    m = _load_mailer()
    ok, sent = _capture_send(m)
    assert ok is True
    assert "h:Reply-To" not in sent["data"]
    assert sent["data"]["from"] == "noreply@codexpress.hu"


# ------------------------------------------------------------ order_status
def _load_order_status(calls):
    mailer = types.ModuleType("app.core.mailer")
    mailer.schedule_email = lambda *a, **k: calls.append((a, k))
    pa = types.ModuleType("app.services.platform_api")
    for fn in ("norm_email", "sellvio_token", "shoprenter_resource_id", "shoprenter_shop",
               "shoprenter_token", "unas_login", "xml_first_text", "xml_root"):
        setattr(pa, fn, lambda *a, **k: None)
    pa.UNAS_BASE = "https://api.unas.eu/shop"
    mods = {
        "app": _pkg("app"), "app.core": _pkg("app.core"), "app.services": _pkg("app.services"),
        "app.models": _pkg("app.models"), "app.core.mailer": mailer,
        "app.services.platform_api": pa,
    }
    with _fake_modules(mods):
        wd = _load("app/services/webdoc_status.py", "app.services.webdoc_status")
        with _fake_modules({"app.services.webdoc_status": wd}):
            return _load("app/services/order_status.py", "order_status_m112_under_test")


def test_reply_to_addrs_filters_own(monkeypatch):
    monkeypatch.delenv("CX_REPLY_TO_EXCLUDE", raising=False)
    os_ = _load_order_status([])
    f = os_._reply_to_addrs
    assert f("info@nagyonallatshop.hu, info@rmmedia.hu,folkmann.ferenc@gmail.com") == \
        ["info@nagyonallatshop.hu", "info@rmmedia.hu"]
    assert f("folkmann.ferenc@gmail.com,info@aliscaker.hu") == ["info@aliscaker.hu"]
    assert f("folkmann.ferenc@gmail.com") == []
    assert f("noreply@codexpress.hu; Info@Bolt.hu, info@bolt.hu") == ["info@bolt.hu"]
    assert f("") == [] and f(None) == [] and f("nem-email, @x") == []


def test_reply_to_env_override(monkeypatch):
    monkeypatch.setenv("CX_REPLY_TO_EXCLUDE", "masik@gmail.com")
    os_ = _load_order_status([])
    assert os_._reply_to_addrs("masik@gmail.com, folkmann.ferenc@gmail.com") == ["folkmann.ferenc@gmail.com"]


def _tenant(lead_email):
    return types.SimpleNamespace(client_id="nagyonallatshop", bot_name="NagyonÁllatShop asszisztens",
                                 lead_email=lead_email)


def _order():
    return types.SimpleNamespace(order_id="81164", order_email="vevo@example.com")


def test_status_email_has_reply_to_and_footer(monkeypatch):
    monkeypatch.delenv("CX_REPLY_TO_EXCLUDE", raising=False)
    calls = []
    os_ = _load_order_status(calls)
    os_._send_status_email(_tenant("info@nagyonallatshop.hu,info@rmmedia.hu,folkmann.ferenc@gmail.com"),
                           _order(), "Teljesítve")
    (args, kw), = calls
    to, subject, text = args
    assert to == "vevo@example.com" and subject == "Rendelésed állapota – #81164"
    assert kw["reply_to"] == "info@nagyonallatshop.hu, info@rmmedia.hu"
    assert kw["from_name"] == "NagyonÁllatShop asszisztens"
    assert "Teljesítve" in text and "írj nekünk: info@nagyonallatshop.hu" in text
    assert "folkmann" not in text


def test_status_email_no_shop_address(monkeypatch):
    monkeypatch.delenv("CX_REPLY_TO_EXCLUDE", raising=False)
    calls = []
    os_ = _load_order_status(calls)
    os_._send_status_email(_tenant("folkmann.ferenc@gmail.com"), _order(), "Teljesítve")
    (args, kw), = calls
    assert kw["reply_to"] == ""
    assert "ne válaszolj" in args[2]

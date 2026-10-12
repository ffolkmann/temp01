# -*- coding: utf-8 -*-
"""m113 — lead-értesítő: Reply-To = a látogató e-mail-címe (chat/widget + konfigurátor).

A modulokat FÁJLBÓL töltjük; a sys.modules-t csak context managerben piszkáljuk.
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


def _load_mailer():
    st = types.ModuleType("app.core.settings")
    st.get_settings = lambda: types.SimpleNamespace(
        mailgun_api_key="k", mailgun_base_url="https://x", mailgun_domain="codexpress.hu",
        mailgun_from="noreply@codexpress.hu")
    with _fake_modules({"app": _pkg("app"), "app.core": _pkg("app.core"), "app.core.settings": st}):
        return _load("app/core/mailer.py", "mailer_m113_under_test")


def test_safe_reply_to():
    f = _load_mailer().safe_reply_to
    assert f("vevo@example.com") == "vevo@example.com"
    assert f("  Vevo.Nev+x@Gmail.com ") == "Vevo.Nev+x@Gmail.com"
    for bad in ("", None, "nem-email", "a@b", "a@b.hu, c@d.hu", "a@b.hu\r\nBcc: x@y.hu",
                "<a@b.hu>", '"x"@b.hu', "a b@c.hu"):
        assert f(bad) == "", bad


def _load_leads(calls, real_reply):
    mailer = types.ModuleType("app.core.mailer")
    mailer.schedule_email = lambda *a, **k: calls.append((a, k))
    mailer.safe_reply_to = real_reply
    conv = types.ModuleType("app.services.conversations")

    async def _gt(*a, **k):
        return []
    conv.get_transcript = _gt
    conv.format_history = lambda h: ""
    conv.format_transcript = lambda t, b: ""
    dbm = types.ModuleType("app.models.db_models")

    class Lead:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Tenant:
        client_id = "client_id"
    dbm.Lead, dbm.Tenant = Lead, Tenant
    sch = types.ModuleType("app.models.schemas")
    sch.ChatRequest = object
    mods = {"app": _pkg("app"), "app.core": _pkg("app.core"), "app.services": _pkg("app.services"),
            "app.models": _pkg("app.models"), "app.core.mailer": mailer,
            "app.services.conversations": conv, "app.models.db_models": dbm, "app.models.schemas": sch}
    with _fake_modules(mods):
        mod = _load("app/services/leads.py", "leads_m113_under_test")
    mod.select = lambda *a, **k: types.SimpleNamespace(where=lambda *a, **k: None)
    return mod


class _Session:
    def __init__(self, tenant):
        self.tenant = tenant

    def add(self, obj):
        self.added = obj

    async def commit(self):
        return None

    async def execute(self, q):
        t = self.tenant
        return types.SimpleNamespace(scalar_one_or_none=lambda: t)


def _req(email, source="chat"):
    return types.SimpleNamespace(client_id="nagyonallatshop", session_id="s1", name="Teszt Elek",
                                 email=email, phone="", message="kerdes", source=source, history=None)


def _run(email):
    calls = []
    leads = _load_leads(calls, _load_mailer().safe_reply_to)
    tenant = types.SimpleNamespace(lead_email="info@bolt.hu", bot_name="Bot")
    asyncio.run(leads.store_lead(_Session(tenant), _req(email)))
    (args, kw), = calls
    return args, kw


def test_lead_email_reply_to_visitor():
    args, kw = _run("vevo@example.com")
    assert args[0] == "info@bolt.hu"
    assert kw["reply_to"] == "vevo@example.com"
    assert "kozvetlenul az erdeklodonek" in args[2]


def test_lead_without_email_no_reply_to():
    args, kw = _run("")
    assert kw["reply_to"] == ""
    assert "kozvetlenul az erdeklodonek" not in args[2]


def test_konf_lead_uses_reply_to():
    src = (ROOT / "app" / "api" / "konf.py").read_text(encoding="utf-8")
    assert 'reply_to=safe_reply_to(p.get("email"))' in src

# -*- coding: utf-8 -*-
"""m118: elo segitsegkeres (handoff) ertesito - ekezetes szoveg + formazott HTML."""
import asyncio
import importlib.util
import os
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone

_D = os.path.join(os.path.dirname(__file__), "..", "app")
_spec = importlib.util.spec_from_file_location("leadmail_m118", os.path.join(_D, "services", "leadmail.py"))
lm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lm)

WHEN = datetime(2026, 10, 14, 11, 4, 7, tzinfo=timezone.utc)
A = ("Emberrel azonnal is beszélhetsz: **most is hívható** a "
     "[+36 70 587 8680](tel:+36705878680) számon, vagy [webshop](https://notebookstore.hu/)")


def _build(**kw):
    base = dict(client_id="notebookstore", page="https://notebookstore.hu/", when=WHEN,
                turns=[("Üdvözlöm! Emberrel beszélek? <b>", "Természetesen! 📨 Továbbítottam."),
                       ("+36300000000", A)],
                bot_name="NotebookStore asszisztens", transcript="x")
    base.update(kw)
    return lm.build_handoff_email(**base)


def test_subject_and_local_time():
    s, t, h = _build()
    assert s == "Élő segítségkérés – notebookstore chatbot"
    assert "Időpont: 2026. 10. 14. 13:04" in t
    assert "2026. 10. 14. 13:04" in h


def test_text_accents_no_markdown():
    _, t, _ = _build()
    assert "Egy látogató élő segítséget" in t
    assert "TELJES BESZÉLGETÉS" in t
    assert "Látogató: Üdvözlöm! Emberrel beszélek?" in t
    assert "NotebookStore asszisztens: Természetesen!" in t
    assert "**" not in t and "](" not in t
    assert "külön lead-értesítőt" in t


def test_html_bubbles_escape_links():
    _, _, h = _build()
    assert "Teljes beszélgetés" in h
    assert h.count("background:#eef2ff") == 2 and h.count("background:#f3f4f6") == 2
    assert "&lt;b&gt;" in h and "<b>" not in h
    assert "<strong>most is hívható</strong>" in h
    assert '<a href="https://notebookstore.hu/"' in h
    assert '<a href="tel:+36705878680"' in h  # tel:/mailto: is kattinthato


def test_page_non_http_not_linked():
    _, _, h = _build(page='javascript:alert(1)"')
    assert "javascript:" in h and '<a href="javascript' not in h


def test_transcript_fallback_when_no_turns():
    s, t, h = _build(turns=[], transcript="Latogato: hello\nBot: szia")
    assert "Latogato: hello" in t
    assert "Latogato: hello<br>Bot: szia" in h


@contextmanager
def _fake_modules():
    saved = {k: sys.modules.get(k) for k in
             ("app", "app.core", "app.core.mailer", "app.services", "app.services.intent",
              "app.services.leadmail")}
    sent = []
    try:
        for name in ("app", "app.core", "app.services"):
            m = types.ModuleType(name)
            m.__path__ = []
            sys.modules[name] = m
        mailer = types.ModuleType("app.core.mailer")
        mailer.schedule_email = lambda *a, **k: sent.append((a, k))
        sys.modules["app.core.mailer"] = mailer
        intent = types.ModuleType("app.services.intent")
        intent.HandoffIntent = object
        sys.modules["app.services.intent"] = intent
        sys.modules["app.services.leadmail"] = lm
        yield sent
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _load_handoff():
    sp = importlib.util.spec_from_file_location("handoff_m118", os.path.join(_D, "services", "handoff.py"))
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


class _T:
    def __init__(self, q, a):
        self.question, self.answer = q, a


class _I:
    to = "bolt@example.hu"
    page = "https://notebookstore.hu/"
    transcript = ""


def test_send_handoff_email_html():
    with _fake_modules() as sent:
        ho = _load_handoff()
        asyncio.run(ho.send_handoff_email("notebookstore", _I(), transcript="Latogato: x",
                                          turns=[_T("Emberrel beszélek?", "Természetesen!")],
                                          bot_name="NB"))
    (a, k), = sent
    assert a[0] == "bolt@example.hu" and a[1].startswith("Élő segítségkérés")
    assert "Teljes beszélgetés" in k["html"]


def test_send_handoff_email_fallback_plain():
    with _fake_modules() as sent:
        broken = types.ModuleType("app.services.leadmail")  # nincs build_handoff_email -> ImportError
        sys.modules["app.services.leadmail"] = broken
        ho = _load_handoff()
        asyncio.run(ho.send_handoff_email("notebookstore", _I(), transcript="Latogato: x"))
    (a, k), = sent
    assert a[1] == "Elo segitsegkeres - notebookstore chatbot"
    assert k["html"] == ""

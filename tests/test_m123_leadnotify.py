# -*- coding: utf-8 -*-
"""m123 — lead-ertesito: beszelgetesenkent egy level, csendes idoszak utan.

A modulokat FAJLBOL toltjuk (stdlib-only reszek); a sys.modules-t csak context managerben piszkaljuk.
"""

import asyncio
import datetime as dt
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LN = _load("app/services/leadnotify.py", "leadnotify_m123_under_test")
LM = _load("app/services/leadmail.py", "leadmail_m123_under_test")

T0 = dt.datetime(2026, 10, 19, 8, 13, 0, tzinfo=dt.timezone.utc)


def _m(s):
    return T0 + dt.timedelta(seconds=s)


def _row(**kw):
    r = {"pending": False, "last_notified": None, "last_lead_at": T0, "first_pending_at": None,
         "last_msg": None}
    r.update(kw)
    return r


# --- decide -------------------------------------------------------------------------------

def test_new_only_after_quiet():
    r = _row(pending=True, first_pending_at=T0, last_lead_at=T0, last_msg=_m(60))
    assert LN.decide(r, _m(60 + 299)) is None
    assert LN.decide(r, _m(60 + 300)) == "new"


def test_nagyonallatshop_esete_egy_level():
    # 3 urlap-lead (08:13:56, 08:15:10, 08:16:26) + uzenetek 08:16:16-ig -> egy 'new' level a csend utan
    r = _row(pending=True, first_pending_at=_m(56), last_lead_at=_m(206), last_msg=_m(196))
    for s in (100, 200, 300, 400):
        assert LN.decide(r, _m(s)) is None
    assert LN.decide(r, _m(206 + 300)) == "new"


def test_max_wait_beats_activity():
    r = _row(pending=True, first_pending_at=T0, last_lead_at=T0, last_msg=_m(1790))
    assert LN.decide(r, _m(1799)) is None
    assert LN.decide(r, _m(1800)) == "new"


def test_supplement_new_lead_after_notified():
    r = _row(pending=True, last_notified=_m(500), first_pending_at=_m(900), last_lead_at=_m(900))
    assert LN.decide(r, _m(1200)) == "supplement"


def test_msgs_after_notified():
    r = _row(last_notified=_m(500), last_lead_at=T0, last_msg=_m(700))
    assert LN.decide(r, _m(900)) is None
    assert LN.decide(r, _m(1000)) == "msgs"
    r2 = _row(last_notified=_m(500), last_lead_at=T0, last_msg=_m(400))
    assert LN.decide(r2, _m(5000)) is None


# --- substantive / merge -------------------------------------------------------------------

def test_substantive():
    triv = lambda q: q.lower().startswith("koszon")  # noqa: E731
    assert not LN.substantive(["Koszonom szepen", "ok", ""], trivial=triv)
    assert LN.substantive(["Koszonom", "82797 rendeles szamom"], trivial=triv)
    assert not LN.substantive([], trivial=triv)


def test_merge_contacts_latest_non_empty():
    m = LN.merge_contacts([
        {"email": "a@x.hu", "phone": "0670", "source": None},
        {"email": "a@x.hu", "phone": "", "source": None},
        {"email": "b@x.hu", "phone": None, "source": "chat"},
    ])
    assert m["email"] == "b@x.hu" and m["phone"] == "0670" and m["source"] is None
    assert LN.merge_contacts([{"email": "c@x.hu", "source": "chat"}])["source"] == "chat"


def test_note_tartalom():
    assert "Ne kérd újra" in LN.NOTE and "collect_lead" in LN.NOTE


# --- leadmail kiegeszites ------------------------------------------------------------------

def _mail(supp):
    return LM.build_lead_email(client_id="bolt", name=None, email="a@x.hu", phone=None,
                               message=None, source=None, reply_to="a@x.hu",
                               turns=[("Q1", "A1"), ("Q2", "A2")], bot_name="Bot",
                               supplement=supp)


def test_leadmail_supplement():
    s, t, h = _mail(True)
    assert s.endswith("(kiegészítés)") and t.startswith("Kiegészítés:") and "Kiegészítés" in h
    s, t, h = _mail(False)
    assert s == "Új érdeklődő – bolt chatbot" and t.startswith("Új érdeklődő érkezett")
    assert "Kiegészítés" not in h
    # idorend: Q1 a Q2 elott, mindket alakban
    assert t.index("Q1") < t.index("A1") < t.index("Q2") < t.index("A2")
    assert h.index("Q1") < h.index("A1") < h.index("Q2") < h.index("A2")


# --- store_lead: session-es lead -> NINCS azonnali level --------------------------------------

def test_store_lead_sessionnel_nem_kuld_azonnal():
    m113 = _load("tests/test_m113_lead_replyto.py", "m113_for_m123")
    calls = []
    leads = m113._load_leads(calls, m113._load_mailer().safe_reply_to)
    import types
    tenant = types.SimpleNamespace(lead_email="info@bolt.hu", bot_name="Bot")
    req = m113._req("vevo@example.com")
    req.session_id = "s1"
    sess = m113._Session(tenant)
    asyncio.run(leads.store_lead(sess, req))
    assert calls == []
    assert getattr(sess.added, "notified_at", None) is None
    # session nelkul azonnal megy, es notified_at ki van toltve
    calls2 = []
    leads2 = m113._load_leads(calls2, m113._load_mailer().safe_reply_to)
    sess2 = m113._Session(tenant)
    asyncio.run(leads2.store_lead(sess2, m113._req("vevo@example.com")))
    assert len(calls2) == 1 and sess2.added.notified_at is not None


# --- bekotes ------------------------------------------------------------------------------

def test_chat_bekotes_sorrend():
    src = (ROOT / "app/api/chat.py").read_text(encoding="utf-8")
    i_chk = src.index("_lead123 = bool((await session.execute(")
    i_commit = src.index("await session.commit()  # m67: kapcsolat vissza a poolba")
    i_note = src.index("system_prompt[1] + _M123_NOTE")
    i_llm = src.index("raw = await generate_reply(")
    i_supp = src.index("m123 collect_lead elnyomva")
    i_unans = src.index("await log_unanswered(session, req.client_id, req.session_id, "
                        "message, top_score, parsed.action)")
    assert i_chk < i_commit < i_note < i_llm < i_supp < i_unans


def test_main_inditja_a_ciklust():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "from app.services.leadnotify import start_loop" in src and "on_event(\"startup\")" in src


def test_lead_model_notified_at():
    src = (ROOT / "app/models/db_models.py").read_text(encoding="utf-8")
    assert "notified_at: Mapped[datetime | None]" in src

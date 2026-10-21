# -*- coding: utf-8 -*-
"""m124: tenantonkenti atadas-valasz (tenants.handoff_replies)."""
import importlib.util
import os

_D = os.path.dirname(__file__)
_P = os.path.join(_D, "..", "app", "services", "handoffnote.py")
_spec = importlib.util.spec_from_file_location("handoffnote_m124", _P)
hn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hn)

DEF = "Természetesen! 📨 Továbbítottam a beszélgetésünket a kollégáinknak."
NB = ("Köszönöm az érdeklődést! 📨 Továbbítottam a beszélgetésünket a kollégáknak. "
      "Milyen termék érdekel, és kb. hány darab?")
RULES = [{"match": "Céges érdeklődés", "reply": NB}]


def test_button_text_matches():
    assert hn.tenant_reply("Céges érdeklődés - projekt jellegű beszerzés.", RULES, DEF) == NB
    assert hn.tenant_reply("ceges erdeklodes", RULES, DEF) == NB


def test_other_handoff_keeps_default():
    for m in ("élő személlyel beszélnék", "Kérek egy munkatársat", ""):
        assert hn.tenant_reply(m, RULES, DEF) == DEF, m


def test_none_or_bad_config_keeps_default():
    for r in (None, [], {}, "x", [1], [{"match": "Céges"}], [{"match": "Céges", "reply": 5}],
              [{"match": "Céges", "reply": "rövid"}], [{"match": "Céges", "reply": "x" * 900}]):
        assert hn.tenant_reply("Céges érdeklődés", r, DEF) == DEF, r


def test_reply_without_mark_rejected():
    r = [{"match": "Céges", "reply": "Köszönöm, hamarosan keresünk, kérlek add meg az e-mail-címed."}]
    assert hn.tenant_reply("Céges érdeklődés", r, DEF) == DEF


def test_star_default_and_specific_priority():
    star = "Rendben! Továbbítottam a beszélgetésünket a kollégáknak, kérlek add meg az e-mail-címed."
    r = [{"match": "*", "reply": star}, {"match": "Céges", "reply": NB}]
    assert hn.tenant_reply("Céges érdeklődés", r, DEF) == NB
    assert hn.tenant_reply("ügyintézőt kérek", r, DEF) == star


def test_short_match_ignored():
    assert hn.tenant_reply("Céges", [{"match": "ce", "reply": NB}], DEF) == DEF


def test_custom_reply_detected_by_m119():
    assert hn.handoff_done([{"role": "assistant", "content": NB}])


def test_human_question_still_honest_m120():
    assert hn.reply_for("Emberrel beszélek?", NB) == hn.HONEST_REPLY
    assert hn.reply_for("Céges érdeklődés - projekt jellegű beszerzés.", NB) == NB


def test_hooks_present():
    chat = open(os.path.join(_D, "..", "app", "api", "chat.py"), encoding="utf-8").read()
    assert "m124" in chat and "handoff_replies" in chat and "reply=_ho_reply" in chat
    mdl = open(os.path.join(_D, "..", "app", "models", "db_models.py"), encoding="utf-8").read()
    assert "handoff_replies: Mapped" in mdl
    cfg = open(os.path.join(_D, "..", "app", "api", "config.py"), encoding="utf-8").read()
    assert 'if "handoff_replies" in row' in cfg

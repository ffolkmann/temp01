# -*- coding: utf-8 -*-
"""m120: ember/robot-kerdesnel oszinte atadas-valasz."""
import importlib.util
import os

_P = os.path.join(os.path.dirname(__file__), "..", "app", "services", "handoffnote.py")
_spec = importlib.util.spec_from_file_location("handoffnote_m120", _P)
hn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hn)

DEF = "Természetesen! 📨 Továbbítottam a beszélgetésünket a kollégáinknak."


def test_human_questions_get_honest_reply():
    for m in ("Üdvözlöm! Emberrel beszélek?", "emberrel szeretnék beszélni", "Ez egy robot?",
              "Élő emberrel tudnék beszélni?", "Te bot vagy?", "Gép válaszol?? Gép vagy?",
              "valódi személlyel beszélhetnék", "Ez AI?"):
        assert hn.reply_for(m, DEF) == hn.HONEST_REPLY, m


def test_plain_handoff_keeps_default():
    for m in ("Ügyintézővel szeretnék beszélni", "Kérek egy munkatársat", "Hívjon vissza egy kolléga",
              "Kapcsolj egy ügyintézőt, a rendelésemről van szó", "Tudna segíteni egy kolléga?"):
        assert hn.reply_for(m, DEF) == DEF, m


def test_honest_reply_is_detected_as_handoff_m119():
    assert hn.handoff_done([{"role": "assistant", "content": hn.HONEST_REPLY}])
    assert hn.handoff_done([{"role": "assistant", "content": DEF}])
    assert not hn.HONEST_REPLY.startswith("Természetesen")


def test_chat_hook_present():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "api", "chat.py"), encoding="utf-8").read()
    assert "m120" in src and "reply=_ho_reply" in src

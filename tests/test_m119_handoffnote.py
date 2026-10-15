# -*- coding: utf-8 -*-
"""m119: handoff utani rendszer-teny a promptban."""
import importlib.util
import os
import types

_P = os.path.join(os.path.dirname(__file__), "..", "app", "services", "handoffnote.py")
_spec = importlib.util.spec_from_file_location("handoffnote_m119", _P)
hn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hn)

HO = ("Természetesen! 📨 Továbbítottam a beszélgetésünket a kollégáinknak. Kérlek, add meg az "
      "e-mail-címed (és ha szeretnéd, a telefonszámod), hogy mielőbb fel tudják venni veled a kapcsolatot.")


def test_detects_assistant_handoff_dict_and_obj():
    assert hn.handoff_done([{"role": "user", "content": "Emberrel beszélek?"},
                            {"role": "assistant", "content": HO}])
    obj = types.SimpleNamespace(role="assistant", content=HO)
    assert hn.handoff_done([obj])


def test_user_quote_or_other_reply_not_counted():
    assert not hn.handoff_done([{"role": "user", "content": HO}])
    assert not hn.handoff_done([{"role": "assistant", "content": "Szia! Miben segíthetek?"}])
    assert not hn.handoff_done(None)
    assert not hn.handoff_done([{"role": "assistant"}])


def test_note_content():
    assert "rendszer-tény" in hn.NOTE
    assert "ne vond vissza" in hn.NOTE
    assert hn.NOTE.startswith("\n\n# ")


def test_chat_hook_present():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "api", "chat.py"), encoding="utf-8").read()
    assert "handoffnote" in src and "m119" in src

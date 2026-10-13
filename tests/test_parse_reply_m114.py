# -*- coding: utf-8 -*-
"""m114: ures envelope-reply mellett a JSON-on kivuli sima szoveg a valasz."""
import importlib.util
import os

_P = os.path.join(os.path.dirname(__file__), "..", "app", "services", "parse_reply.py")
_spec = importlib.util.spec_from_file_location("parse_reply_m114", _P)
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)

TXT = ("Szuper választás! A [Lenovo ThinkVision T34WD-40](https://notebookstore.hu/x-p19087) "
       "jelenleg **raktáron** van, **149 990 Ft**-ért.\n\n- 34\"-os ívelt VA panel")


def test_plain_text_plus_flag_json_trailer():
    r = pr.parse_reply(TXT + '\n\n{"collect_lead": false, "order_form": false}')
    assert r.reply == TXT
    assert r.action is None
    assert r.note == "m114"


def test_plain_text_plus_empty_reply_json():
    r = pr.parse_reply(TXT + '\n```json\n{"reply": "", "collect_lead": false}\n```')
    assert r.reply == TXT
    assert r.note == "m114"


def test_json_before_text():
    r = pr.parse_reply('{"reply": ""}\n' + TXT)
    assert r.reply == TXT


def test_trailer_collect_lead_true_keeps_flag():
    r = pr.parse_reply(TXT + '\n{"collect_lead": true}')
    assert r.reply == TXT
    assert r.action == "collect_lead"


def test_only_empty_envelope_still_fallback():
    r = pr.parse_reply('```json\n{"reply": "", "collect_lead": false}\n```')
    assert r.reply == pr._FALLBACK
    assert r.action == "collect_lead"
    assert r.note is None


def test_short_junk_outside_still_fallback():
    r = pr.parse_reply('Ok.\n{"reply": ""}')
    assert r.reply == pr._FALLBACK


def test_normal_envelope_unchanged():
    r = pr.parse_reply('{"reply": "Szia, ez a valasz.", "collect_lead": false, "order_form": true}')
    assert r.reply == "Szia, ez a valasz."
    assert r.action == "order_status_form"
    assert r.note is None


def test_plain_text_without_json_unchanged():
    r = pr.parse_reply(TXT)
    assert r.reply == TXT
    assert r.note is None


def test_alt_key_still_wins():
    r = pr.parse_reply(TXT + '\n{"reply": "", "answer": "Masik kulcs alatti valasz itt van."}')
    assert r.reply == "Masik kulcs alatti valasz itt van."
    assert r.note is None

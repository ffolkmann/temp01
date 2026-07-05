"""parse_reply keményítés (m24) — csonkolt/fence-elt/hibrid modellkimenetek.

A modult FÁJLBÓL töltjük (importlib), mert a suite többi tesztje üres stubokkal
írja felül az app.* csomagfát a sys.modules-ban -> a sima import elhasalna.
"""

import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "parse_reply.py"
_spec = importlib.util.spec_from_file_location("parse_reply_under_test", _p)
_pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pr)
parse_reply, _FALLBACK = _pr.parse_reply, _pr._FALLBACK


def test_valid_json():
    p = parse_reply('{"reply": "Szia!", "collect_lead": false, "order_form": false}')
    assert p.reply == "Szia!" and p.action is None


def test_fenced_valid_json():
    p = parse_reply('```json\n{"reply": "Szia!", "collect_lead": true, "order_form": false}\n```')
    assert p.reply == "Szia!" and p.action == "collect_lead"


def test_plain_text_passthrough():
    p = parse_reply("Sima szoveges valasz JSON nelkul.")
    assert p.reply == "Sima szoveges valasz JSON nelkul." and p.action is None


def test_truncated_fenced_json_fo_incidens():
    # FO messages #64 mintaja: plain bevezeto + fence + csonkolt string (nincs zaro " es })
    raw = (
        "Mit szeretnel pontosan?\n\n"
        '```json\n{\n  "reply": "Jó! A **spicckínálatunkról** tudok több infót adni. 😊 \\n\\n'
        '[SPICC BENZAR](https://x.hu/p1) – 3 790 Ft\\n- [CARP EXPERT](https://x.hu/p2) – 4'
    )
    p = parse_reply(raw)
    assert p.reply.startswith("Jó! A **spicckínálatunkról**")
    assert "```" not in p.reply and '"reply"' not in p.reply
    assert "\\n" not in p.reply and "\n" in p.reply   # escape-ek feloldva


def test_truncated_with_flags():
    raw = '{"collect_lead": true, "order_form": false, "reply": "Hagyd meg az e-mail-cimed es'
    p = parse_reply(raw)
    assert p.reply.startswith("Hagyd meg") and p.action == "collect_lead"


def test_raw_newline_inside_json_string():
    p = parse_reply('{"reply": "Első sor\nMásodik sor", "collect_lead": false, "order_form": false}')
    assert p.reply == "Első sor\nMásodik sor"


def test_empty_reply_fallback():
    p = parse_reply('{"reply": "", "collect_lead": false, "order_form": false}')
    assert p.reply == _FALLBACK and p.action == "collect_lead"

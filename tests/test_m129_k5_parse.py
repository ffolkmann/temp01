# -*- coding: utf-8 -*-
"""m129 (K5): rovid/csonka/JSON-os valasz — parse_reply mentesei + csonka-link levagas + bekotes."""
import importlib.util
import os

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _load():
    p = os.path.join(_ROOT, "app", "services", "parse_reply.py")
    spec = importlib.util.spec_from_file_location("m129_parse_reply", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pr = _load()


def test_unescaped_hungarian_quote_not_truncated():
    raw = ('{"reply": "Igen, a termék **címében** szerepel a „Windows 11 Professional" felirat, '
           'tehát telepítve érkezik.", "collect_lead": true, "order_form": false}')
    p = pr.parse_reply(raw)
    assert p.reply.endswith("telepítve érkezik.")
    assert '„Windows 11 Professional"' in p.reply
    assert p.action == "collect_lead"
    assert p.note == "m129q"


def test_unescaped_quote_in_parens():
    raw = ('{"reply": "Ezt a kérdést megértem, de a termék elnevezésének ezt a részét '
           '("WITH BATTERY OPEN") nem tudom megmondani.", "collect_lead": true, "order_form": false}')
    p = pr.parse_reply(raw)
    assert p.reply.endswith("nem tudom megmondani.")
    assert '("WITH BATTERY OPEN")' in p.reply


def test_unescaped_quote_reply_last_key():
    raw = '{"collect_lead": false, "order_form": false, "reply": "Szia! Csak egy „U" érkezett. Miben segíthetek?"}'
    p = pr.parse_reply(raw)
    assert p.reply == 'Szia! Csak egy „U" érkezett. Miben segíthetek?'
    assert p.action is None


def test_escaped_newline_inside_salvaged_reply():
    raw = '{"reply": "Első sor\\nMásodik „sor" vége.", "collect_lead": false, "order_form": false}'
    p = pr.parse_reply(raw)
    assert p.reply == 'Első sor\nMásodik „sor" vége.'


def test_plain_text_with_json_tail():
    raw = ('Bocsi, hogy előbb visszakérdeztem. Közvetlenül is elérheted őket: +36 30 623 2322, '
           'info@example.invalid", "collect_lead": true, "order_form": false}')
    p = pr.parse_reply(raw)
    assert p.reply.endswith("info@example.invalid")
    assert '"collect_lead"' not in p.reply
    assert p.action == "collect_lead"
    assert p.note == "m129t"


def test_plain_text_escaped_quote_leak():
    raw = 'A termékadatlapunkon ez a monitor 27\\"-os képátlóval szerepel.'
    p = pr.parse_reply(raw)
    assert p.reply == 'A termékadatlapunkon ez a monitor 27"-os képátlóval szerepel.'
    assert p.note == "m129e"


def test_truncated_max_tokens_still_lazy_salvage():
    raw = '{"reply": "Ezek vannak raktáron:\\n- [Lenovo T22i](https://x.hu/a): 50 000 Ft\\n- [Lenovo T23i](https://x.hu/lenovo-t23i-30-'
    p = pr.parse_reply(raw)
    assert p.reply.startswith("Ezek vannak raktáron:")
    assert p.action is None
    assert p.note is None


def test_normal_envelope_unchanged():
    raw = '{"reply": "Szia! A termék raktáron van.", "collect_lead": false, "order_form": true}'
    p = pr.parse_reply(raw)
    assert p.reply == "Szia! A termék raktáron van."
    assert p.action == "order_status_form"
    assert p.note is None


def test_properly_escaped_quote_unchanged():
    raw = '{"reply": "A „Pro\\" változat 27\\"-os.", "collect_lead": false, "order_form": false}'
    p = pr.parse_reply(raw)
    assert p.reply == 'A „Pro" változat 27"-os.'
    assert p.note is None


def test_plain_text_untouched():
    raw = 'Sima válasz, benne egy {kapcsos} és "idézet", vessző, kész.'
    p = pr.parse_reply(raw)
    assert p.reply == raw
    assert p.note is None


def test_empty_reply_still_fallback():
    p = pr.parse_reply('{"reply": "", "collect_lead": true, "order_form": false}')
    assert p.reply == pr._FALLBACK
    assert p.action == "collect_lead"


def test_trim_dangling_link_at_list_end():
    t = ("Ezek vannak raktáron:\n- [Lenovo T22i](https://x.hu/a): 50 000 Ft\n"
         "- [Lenovo T23i](https://notebookstore.hu/lenovo-t23i-30-monitor-63b2mat6eu-23-fullhd-")
    out, cut = pr.trim_dangling_link(t)
    assert cut is True
    assert out == "Ezek vannak raktáron:\n- [Lenovo T22i](https://x.hu/a): 50 000 Ft"


def test_trim_dangling_link_mid_sentence():
    t = "A merítőfejhez nyél is kell. A [Drennan Vertex 3m merítőnyél]("
    out, cut = pr.trim_dangling_link(t)
    assert cut is True
    assert out == "A merítőfejhez nyél is kell."


def test_trim_dangling_open_bracket_only():
    t = "Ezek a talicskák vannak raktáron most:\n- [PALISAD 170kg/78L kétkerekű kerti talicska"
    out, cut = pr.trim_dangling_link(t)
    assert cut is True
    assert out == "Ezek a talicskák vannak raktáron most:"


def test_trim_no_change_when_complete():
    t = "Nézd meg: [Talicska](https://x.hu/t) – 21 990 Ft."
    out, cut = pr.trim_dangling_link(t)
    assert cut is False and out == t


def test_trim_no_change_when_search_link_closes():
    t = "Nincs ilyen.\n\n[További találatok a webáruházban](https://x.hu/kereses?keyword=a+b)"
    out, cut = pr.trim_dangling_link(t)
    assert cut is False and out == t


def test_trim_no_change_when_nothing_would_remain():
    t = "[Lenovo T23i](https://notebookstore.hu/lenovo-"
    out, cut = pr.trim_dangling_link(t)
    assert cut is False and out == t


def test_chat_wiring_m129():
    src = open(os.path.join(_ROOT, "app", "api", "chat.py"), encoding="utf-8").read()
    i = src.index("m129 ures reply -> ujraproba")
    assert src.index("trim_dangling_link as _tdl129") < i
    assert src.index("m129 csonka link levagva") > i
    # a m129 blokk a m116 urlap-igeret ELOTT all — a levagott reply-t mar a m116 is latja
    assert i < src.index("# m116: URLAP-IGERET OSSZHANG")

# -*- coding: utf-8 -*-
"""m115: lead-ertesito ekezetes szoveg + formazott HTML."""
import importlib.util
import os

_P = os.path.join(os.path.dirname(__file__), "..", "app", "services", "leadmail.py")
_spec = importlib.util.spec_from_file_location("leadmail_m115", _P)
lm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lm)

A = ("Ezekkel a módokkal tudsz fizetni:\n- **Banki átutalás**\n- **Készpénz**\n\n"
     "Nézd meg: [Lenovo T34WD-40](https://notebookstore.hu/lenovo-p19087)")


def _build(**kw):
    base = dict(client_id="notebookstore", name="", email="a@b.hu", phone="+36301234567",
                message="", source=None, reply_to="a@b.hu",
                turns=[("Milyen fizetési módok vannak?", A), ("Monitort vennék <script>", None)],
                bot_name="NotebookStore asszisztens")
    base.update(kw)
    return lm.build_lead_email(**base)


def test_subject_accented():
    s, _, _ = _build()
    assert s == "Új érdeklődő – notebookstore chatbot"


def test_text_no_markdown_and_accents():
    _, t, _ = _build()
    assert "**" not in t and "](" not in t
    assert "Látogató: Milyen fizetési módok vannak?" in t
    assert "Lenovo T34WD-40 (https://notebookstore.hu/lenovo-p19087)" in t
    assert "TELJES BESZÉLGETÉS" in t
    assert "Név: –" in t


def test_html_link_bold_bullets_escape():
    _, _, h = _build()
    assert '<a href="https://notebookstore.hu/lenovo-p19087"' in h
    assert "<strong>Banki átutalás</strong>" in h
    assert "&bull;" in h
    assert "<script>" not in h and "&lt;script&gt;" in h
    assert "NotebookStore asszisztens" in h


def test_non_http_link_not_linked():
    h = lm.md_to_html("[x](javascript:alert(1))")
    assert "<a " not in h


def test_source_chat_note_and_no_turns():
    _, t, h = _build(source="chat", turns=[], reply_to="")
    assert "a chatbe írta be" in t and "a chatbe írta be" in h
    assert "TELJES" not in t and "Teljes beszélgetés" not in h
    assert "Erre a levélre" not in t

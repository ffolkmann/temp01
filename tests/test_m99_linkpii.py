"""m99: szemelyes adat a kereso-linkben, parbeszed-szavak, parse_reply mentes."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


lt = _load("m99_linkterm", "app/services/linkterm.py")
pr = _load("m99_parse_reply", "app/services/parse_reply.py")


def test_pii_felismeres():
    for s in ("Igen kovacsotto@gmail.com", "hivj: +36 30 623 2322", "06-30-123-4567",
              "rendelesszam 21196120792", "balogh1020@freemail.hu"):
        assert lt.has_pii(s), s
    for s in ("Einhell kompresszor 24 literes", "MTX 115mm P24 csiszolo",
              "Samsung VC07M3110VB/GE", "STELS 2T 181-345mm", "21196-1200"):
        assert not lt.has_pii(s), s


def test_pii_uzenetre_nincs_term():
    assert lt.link_search_term("kovacsotto@gmail.com - Kovacs Otto",
                               ["Samsung HEPA szuro"], None, context="x") == ""
    assert lt.link_search_term("Igen kovacsotto@gmail.com", [], None,
                               context="Igen kovacsotto@gmail.com") == ""


def test_kontextusbol_kiesik_a_pii():
    t = lt.link_search_term("HEPA szuro kellene",
                            ["Samsung HEPA szuro keszlet", "HEPA szuro Samsung"], None,
                            context="HEPA szuro kellene kovacsotto@gmail.com")
    assert t and "@" not in t and "gmail" not in t.lower()


def test_parbeszed_szo_nem_term():
    assert lt.link_search_term("Igen, rendben", [], None, context="Igen, rendben") == ""
    assert lt.link_search_term("Oke, varom", [], None, context="Oke, varom") == ""


def test_termek_kerdes_termje_marad():
    assert lt.link_search_term("Einhell kompresszor", [], None,
                               context="Einhell kompresszor") == "Einhell kompresszor"


def test_parse_reply_mas_kulcs_mentes():
    p = pr.parse_reply('{"answer": "Szia! Van raktaron.", "collect_lead": false}')
    assert p.reply == "Szia! Van raktaron." and p.action is None


def test_parse_reply_ures_marad_fallback():
    p = pr.parse_reply('{"reply": "", "collect_lead": false}')
    assert p.reply == pr._FALLBACK and p.action == "collect_lead"
    assert pr.parse_reply("").reply == pr._FALLBACK


def test_parse_reply_normal_valtozatlan():
    p = pr.parse_reply('{"reply": "Rendben.", "order_form": true}')
    assert p.reply == "Rendben." and p.action == "order_status_form"

# -*- coding: utf-8 -*-
"""m126 (K3): zaro-link kapu 2 - termek-jellegu kerdes, ertelmes kulcsszo (valodi esetek, d21b korpusz)."""
import importlib.util
import os

_D = os.path.dirname(__file__)
_P = os.path.join(_D, "..", "app", "services", "linkgate2.py")
_spec = importlib.util.spec_from_file_location("linkgate2_m126", _P)
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

# mini-katalogus (foldolt tokenek -> hany nevben); n = termekszam
DF = {"pellet": 80, "bojli": 50, "damil": 40, "horgaszbot": 30, "bot": 60, "reszes": 20, "tarto": 30,
      "endoszkop": 8, "slagvizmertek": 5, "kamera": 40, "akksi": 4, "sds": 30, "plus": 25, "csali": 40,
      "tesla": 700, "model": 900, "konzol": 6, "notebook": 450, "lezernyomtato": 12, "holegbefuvo": 9,
      "tarto": 30, "hossz": 21, "venni": 3, "drag": 4, "utan": 4, "tartozik": 3, "monitor": 50, "galaxy": 20}
DFX = (DF, 1000)


def test_hard_stop_order_pickup_complaint():
    for m in ("Hol tart mikorra várható", "múlt hét csütörtökön rendeltem", "De mar 6 nap telt el",
              "Nincs a spamba sem", "ma át tudom venni?", "Ezt a terméket ha személyesen szeretném átvenni",
              "Szeretném visszamondani a rendelést", "nem vette fel senki", "nincsenek banki adatok az emailben",
              "I just bought a hp mini pc. I would be happy to get free delivery"):
        t, blk, why = lg.gate_term(m, "", "x", DFX, topic=True)
        assert blk and why.startswith("rendeles"), m
    t, blk, _ = lg.gate_term("Kettő darabot", "rendelésszám #58623, e-mail: x@y.hu", "Kettő darabot", DFX, topic=True)
    assert blk


def test_non_product_messages_get_no_link():
    for m in ("Béláné", "szia drágám", "Mit ?", "jah", "Remélem jó lesz", "Nekem az nagyon messze van sajnos",
              "lenne venni", "Itt nálatok látom ennyiért"):
        t, blk, _ = lg.gate_term(m, "", lg.fold(m)[:20] or "x", DFX, topic=True)
        assert blk, m


def test_product_questions_keep_link():
    for m, kw in (("Pellet", "Pellet"), ("0.22 damilt keresek 1000 M", "damilt keresek"),
                  ("Hőlégbefúvót keresek", "Hőlégbefúvót"), ("Milyen lézernyomtatóitok vannak?", "lézernyomtatóitok"),
                  ("Kellene nekem egy SDS plus fúrotokmány", "Kellene nekem")):
        t, blk, _ = lg.gate_term(m, "", kw, DFX, topic=True)
        assert not blk and t, m


def test_topic_term_rebuilt_from_product_words():
    t, blk, why = lg.gate_term("Udvozlom! Az lenne a kerdesem h egy ket reszes bot tartóba", "", "lenne ket", DFX, topic=True)
    assert not blk and t == "reszes bot" and why == "term ujraepitve"
    t, _, _ = lg.gate_term("Kellene nekem egy SDS plus fúrotokmány", "", "Kellene nekem", DFX, topic=True)
    assert t == "SDS plus"
    t, _, _ = lg.gate_term("0.22 damilt keresek 1000 M", "", "damilt keresek", DFX, topic=True)
    assert t == "damilt"
    t, _, _ = lg.gate_term("bojlis horgászbot", "", "bojlis horgászbot", DFX, topic=True)
    assert t == "bojlis horgászbot"  # jo kulcsszo valtozatlan


def test_generic_brand_word_not_a_term():
    t, blk, _ = lg.gate_term("könyöklőborítás tesla model 3", "", "Tesla", DFX)
    assert blk
    t, blk, _ = lg.gate_term("Tesla y 2026 konzol kiegészítő", "", "Tesla konzol", DFX, topic=True)
    assert not blk and t in ("Tesla konzol", "konzol")


def test_history_name_term_followups():
    # termek-kovetes (meret) -> marad; udvariassag / logisztika -> nincs link
    assert not lg.gate_term("A 25 méteres kellene", "Slag víz mértéket vennék", "slagvízmérték", DFX)[1]
    assert not lg.gate_term("Hosszabb kell", "Slag víz mértéket vennék", "slagvízmérték", DFX)[1]
    assert lg.gate_term("Köszönöm az infot", "x", "Monitor", DFX)[1]
    assert lg.gate_term("Tudok neked kepet kuldeni ?", "x", "galaxy", DFX)[1]
    assert not lg.gate_term("tgyalu", "", "gyalu", ({"gyalu": 10}, 100))[1]  # a term a kerdesbol levezetheto


def test_shop_branch_filters_phrase():
    t, blk, _ = lg.gate_term("Szia. Nemsokára érkezünk hozzatok egy Federes bot", "",
                             "szia nemsokára érkezünk hozzatok federes bot", DFX, shop=True)
    assert not blk and t == "bot"
    assert lg.gate_term("Nem tudom át váltani", "", "nem tudom váltani", DFX, shop=True)[1]
    # m126b: a bolti kereso csonkolt tovel dolgozik ("pell") -> a kerdes szava a tartalek
    t, blk, _ = lg.gate_term("Pellet", "", "pell", DFX, shop=True)
    assert not blk and t == "Pellet"
    # a bolti agon 1 termeknev is eleg (a bolt keresoje mar talalt termeket)
    t, blk, _ = lg.gate_term("Hőlégbefúvót keresek", "", "hőlégbefúvó", ({"holegbefuvo": 1}, 9000), shop=True)
    assert not blk and t == "hőlégbefúvó"
    assert lg.gate_term("Hőlégbefúvót keresek", "", "Hőlégbefúvót", ({"holegbefuvo": 1}, 9000), topic=True)[1]


def test_fail_open_without_catalog():
    t, blk, why = lg.gate_term("Béláné", "", "Béláné", None, topic=True)
    assert not blk and t == "Béláné" and why == "nincs katalogus"
    assert lg.gate_term("Hol tart a rendelésem", "", "x", None)[1]  # a hard-stop katalogus nelkul is el


def test_catalog_word_rules():
    assert lg.catalog_word("pelletet", DF)
    assert not lg.catalog_word("tart", DF)          # beszelgetesi szo
    assert not lg.catalog_word("dragam", DF)        # drag (4 betus to, 2 betus rag) nem eleg
    assert not lg.catalog_word("valami", DF)


def test_prev_user():
    h = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"},
         {"role": "assistant", "content": "d"}]
    assert lg.prev_user(h) == "c"
    assert lg.prev_user([]) == ""


def test_chat_hooks_present():
    src = open(os.path.join(_D, "..", "app", "api", "chat.py"), encoding="utf-8").read()
    assert "m126 link gate" in src and "gate_term" in src and "_m126_block" in src

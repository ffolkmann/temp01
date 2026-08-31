#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""m96/1 + m96/2 regresszios tesztek - a d31a szal eles leletei.

Kulon fajl, hogy a m96 alap-tesztek erintetlenul maradjanak.
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "answerguard.py"
_spec = importlib.util.spec_from_file_location("answerguard_m96n1", _p)
ag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ag)

POLICY = {
    "redact_emails": ["info@konturreklam.hu"],
    "email_replacement": "https://www.konturreklam.hu/elerhetoseg",
    "gate_phones": ["+36 70 770 0396"],
}

# A d31a gatecheck VALODI eles valasza, ami csonkot hagyott:
#   "... hivd nyugodtan az irodat:."
ELES_ARAJANLAT = (
    "Az \u00e1raj\u00e1nlatot 24 \u00f3r\u00e1n bel\u00fcl elk\u00fcldj\u00fck, miut\u00e1n be\u00e9rkezett az ig\u00e9nyed. "
    "Ha ennyi id\u0151 alatt m\u00e9gsem \u00e9rkezne meg, h\u00edvd nyugodtan az irod\u00e1t: "
    "+36 70 770 0396."
)
ELES_ROVID = (
    "Az \u00e1raj\u00e1nlatot 24 \u00f3r\u00e1n bel\u00fcl elk\u00fcldj\u00fck. Ha ennyi id\u0151 alatt m\u00e9gsem "
    "\u00e9rkezne meg, h\u00edvd az irod\u00e1t: +36 70 770 0396."
)
CSAK_TELEFON = "H\u00edvj minket: +36 70 770 0396."


# --- m96/1: csonk-takaritas ------------------------------------------------
def test_nem_hagy_csonkot():
    out, info = ag.apply_policy(ELES_ARAJANLAT, POLICY,
                                "Mikor kapom meg az \u00e1raj\u00e1nlatot?")
    assert "770 0396" not in out
    assert ":." not in out
    assert not out.rstrip().endswith(":")
    assert "24 \u00f3r\u00e1n bel\u00fcl" in out       # az erdemi valasz megmarad
    assert info["phone"] == 1


def test_rovid_valasz_sem_hagy_csonkot():
    out, _ = ag.apply_policy(ELES_ROVID, POLICY, "mennyi id\u0151 alatt k\u00fcldtok aj\u00e1nlatot")
    assert "770 0396" not in out
    assert ":." not in out
    assert not out.rstrip().endswith(":")
    assert out.strip()


def test_listafelvezeto_kettospont_megmarad():
    """FP-vedelem: a legitim listafelvezeto ':' nem eshet aldozatul."""
    txt = ("A sz\u00fcks\u00e9ges adatok a k\u00f6vetkez\u0151k:\n"
           "- darabsz\u00e1m\n"
           "- grafika\n"
           "Ha k\u00e9rd\u00e9sed van, h\u00edvj: +36 70 770 0396.")
    out, _ = ag.apply_policy(txt, POLICY, "mit kell megadni az aj\u00e1nlatk\u00e9r\u00e9shez")
    assert "k\u00f6vetkez\u0151k:" in out          # a felvezeto kettospont megmaradt
    assert "darabsz\u00e1m" in out
    assert "grafika" in out
    assert "770 0396" not in out


def test_tobbmondatos_valaszban_csak_a_telefonos_mondat_esik_ki():
    txt = ("A g\u00e9pi h\u00edmz\u00e9s tart\u00f3s megold\u00e1s. "
           "A maxim\u00e1lis m\u00e9ret 30 x 20 cm. "
           "H\u00edvj minket a +36 70 770 0396-os sz\u00e1mon!")
    out, _ = ag.apply_policy(txt, POLICY, "h\u00edmz\u00e9s m\u00e9rete")
    assert "30 x 20 cm" in out
    assert "tart\u00f3s megold\u00e1s" in out
    assert "770 0396" not in out


def test_a_kapu_nyitva_semmit_nem_valtoztat():
    """Ha kertek a telefont, a valasz BETUre ugyanaz marad."""
    out, info = ag.apply_policy(ELES_ARAJANLAT, POLICY, "mi a telefonsz\u00e1motok?")
    assert out == ELES_ARAJANLAT
    assert info["asked"] is True


# --- m96/2: a fail-safe nem sertheti meg a garanciat ------------------------
def test_csak_telefonos_valasz_nem_adja_vissza_az_eredetit():
    """A legfontosabb: ures eredmenynel SEM kerulhet vissza a szam."""
    out, _ = ag.apply_policy(CSAK_TELEFON, POLICY, "mit csin\u00e1ltok")
    assert "770 0396" not in out
    assert out.strip()
    assert out != CSAK_TELEFON


def test_empty_fallback_ha_van():
    pol = dict(POLICY)
    pol["empty_fallback"] = "Az el\u00e9rhet\u0151s\u00e9geinket az aj\u00e1nlatk\u00e9r\u0151 oldalon tal\u00e1lod."
    out, _ = ag.apply_policy(CSAK_TELEFON, pol, "mit csin\u00e1ltok")
    assert out == pol["empty_fallback"]


def test_empty_fallback_nelkul_sem_szivarog():
    pol = {"gate_phones": ["+36 70 770 0396"]}
    out, _ = ag.apply_policy(CSAK_TELEFON, pol, "mit csin\u00e1ltok")
    assert "770 0396" not in out
    assert out.strip()

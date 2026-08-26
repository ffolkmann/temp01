"""m94: „nem valódi kérdés" felismerés — a megválaszolatlan-riport zajszűrője.

A teszt-készlet magja az ÉLES adatból jött (2548 unanswered sor, 16 tenant):
a szűkítés előtti változat kiszűrte volna az „és még?" folytatás-kérdést, ezért
az `es`/`meg` token kikerült — ez a `test_valodi_kerdes_marad` sor őrzi.
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])
for n in ("app", "app.sync"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


tq = _load("trivialq_m94", f"{ROOT}/app/services/trivialq.py")


def test_udvariassag():
    for q in ["szia", "Szia!", "SZIA", "sziasztok", "Üdv", "Üdvözlöm", "Jó reggelt",
              "Köszönöm", "Köszönöm szépen.", "köszi", "Kőszőnőm szépen a választ.",
              "Igen", "Nem", "ok", "Oké", "rendben", "Viszlát", "thanks", "Thank you"]:
        assert tq.is_trivial(q) is True, q


def test_parancs():
    assert tq.is_trivial("/clear") is True
    assert tq.is_trivial("  /reset") is True
    assert tq.is_trivial("/barmi ismeretlen") is True


def test_urlap_tormelek():
    """Lead-űrlap közben beírt adatok — ezek nem tudáshiányok (és személyes adatok)."""
    for q in ["tiespop01@gmail.com", "54861", "06304767954", "+36 30 214 0984",
              "1010000182391", "29.4", "M", "w", "."]:
        assert tq.is_trivial(q) is True, q


def test_valodi_kerdes_marad():
    """REGRESSZIÓ (éles adatból): ezek NEM tűnhetnek el a riportból."""
    for q in ["és még?", "és?", "miért?", "Nem értem", "nem értem a választ",
              "munkaruha", "Utca", "Van MSI laptopotok?", "hamburger van?",
              "Hol tart a rendelésem?", "Raktáron van a termék?", "Vízállóság?",
              "Köszönöm, ennyi volt!", "kapcsolj élő személyt", "Mi a telefonszámotok?"]:
        assert tq.is_trivial(q) is False, q


def test_ures_es_none():
    assert tq.is_trivial("") is True
    assert tq.is_trivial(None) is True
    assert tq.is_trivial("   ") is True


def test_normalizalas():
    assert tq.normalize("Köszönöm szépen!") == "koszonom szepen"
    assert tq.normalize("  ÜDV,  ") == "udv"


def test_hosszu_udvarias_mondat_marad():
    """5 szónál hosszabb mondatot nem minősítünk zajnak, akkor sem, ha udvarias."""
    assert tq.is_trivial(
        "köszönöm szépen a gyors és kimerítő választ minden részletre") is False

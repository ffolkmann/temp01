# -*- coding: utf-8 -*-
"""m104: a kerdesben megadott cikkszam lathatova tetele a promptban.

Fajl-betoltos import (a suite mas tesztjei fake app.services-t hagyhatnak a sys.modules-ben);
a prompt.py fake app-modulokkal, context managerben (a sys.modules a teszt utan visszaall).
"""
import contextlib
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


lx = _load("lexmatch_m104", "app/services/lexmatch.py")


@contextlib.contextmanager
def _fake_modules(mods):
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _load_prompt():
    fakes = {
        "app.models.db_models": _mod("app.models.db_models", Coupon=type("Coupon", (), {}),
                                     Tenant=type("Tenant", (), {})),
        "app.services.current_product": _mod("app.services.current_product",
                                             CurrentProduct=type("CurrentProduct", (), {})),
        "app.services.handoff_offer": _mod("app.services.handoff_offer", prompt_block=lambda: ""),
        "app.services.factuality": _mod("app.services.factuality", factuality_block=lambda: "\n\nFAKT"),
        "app.services.live_product": _mod("app.services.live_product",
                                          LivePriceStock=type("LivePriceStock", (), {})),
    }
    with _fake_modules(fakes):
        return _load("m104_prompt", "app/services/prompt.py")


pr = _load_prompt()


def _hit(i, sku, text="Termek szoveg", typ="product"):
    return {"id": i, "score": 0.5, "payload": {"type": typ, "sku": sku, "name": "N%d" % i, "text": text}}


# --- sku_match ---------------------------------------------------------------------
def test_pontos_egyezes_a_katalogus_alakot_adja():
    assert lx.sku_match("YT-82992", "Keresem a yt82992 cikkszàmú terméket") == "YT-82992"
    assert lx.sku_match("P-YT-73861", "mikorra jöhet meg? Cikkszám:  P-YT-73861") == "P-YT-73861"
    assert lx.sku_match("729809", "729809") == "729809"
    assert lx.sku_match("I-58450", "Ennek a terméknek Cikkszám:  I-58450 a méretét szeretném") == "I-58450"


def test_vegzodes_egyezes_a_latogato_alakjat_adja_nem_a_belso_skut():
    # szallito-elotagos belso sku ne keruljon ki a promptba
    assert lx.sku_match("P-YT-24231", "YT-24231 van raktáron?") == "YT-24231"
    assert lx.sku_match("mfishing-M-CCLGRI250", "M-CCLGRI250 van?") == "M-CCLGRI250"


def test_csupa_szam_vegzodes_nem_eleg():
    assert lx.sku_match("tolnagro-143167", "143167") == ""


def test_osszeg_es_rendelesszam_nem_cikkszam():
    # korpusz-sweep lelet (fishingoutlet): "van ra 20000 ft-om" -> a 20000 sku-ju termek jelolodott
    assert lx.sku_tokens("két napos túra és van rá 20000 ft-om, mit javasolsz") == []
    assert lx.sku_match("20000", "van rá 20000 ft-om") == ""
    assert lx.sku_tokens("1 db monitor 43.590 Ft") == []
    assert lx.sku_tokens("12990 forint alatt") == []
    assert lx.sku_tokens("rendelésem #30781") == []
    # a csupasz cikkszam es a betus kod tovabbra is kod
    assert lx.sku_tokens("729809") == ["729809"]
    assert lx.sku_tokens("YT-82992 ára?") == ["yt82992"]
    assert lx.sku_tokens("20000ft") == ["20000ft"]  # egy token, nem csupa szam: marad (katalogusban nincs)


def test_nincs_kod_vagy_mas_kod():
    assert lx.sku_match("YT-82992", "sarokcsiszoló porelszívó adapter") == ""
    assert lx.sku_match("YT-82992", "yt82993 kellene") == ""
    assert lx.sku_match("", "yt82992") == ""
    assert lx.sku_match(None, "yt82992") == ""
    # telefonszam-szeru szamsor nem kod
    assert lx.sku_match("06301234567", "hivjatok a 06301234567 szamon") == ""


# --- mark_sku ----------------------------------------------------------------------
def test_mark_csak_az_egyezo_termeket_jeloli():
    hits = [_hit(1, "YT-82992"), _hit(2, "YT-82993"), _hit(3, "YT-82992", typ="kb"), "nem dict"]
    n = lx.mark_sku(hits, "Keresem a yt82992 cikkszámú terméket")
    assert n == 1
    assert hits[0]["m104_sku"] == "YT-82992"
    assert "m104_sku" not in hits[1] and "m104_sku" not in hits[2]


def test_mark_kod_nelkul_semmit_nem_valtoztat():
    hits = [_hit(1, "YT-82992")]
    assert lx.mark_sku(hits, "Van sarokcsiszoló adapteretek?") == 0
    assert "m104_sku" not in hits[0]
    assert lx.mark_sku(None, "yt82992") == 0


def test_mark_aktualis_termek():
    cur = types.SimpleNamespace(sku="I-58450", text="Adatlap")
    assert lx.mark_sku([], "Cikkszám: I-58450 a méretét szeretném", cur) == 1
    assert cur.m104_sku == "I-58450"
    cur2 = types.SimpleNamespace(sku="I-58451", text="Adatlap")
    assert lx.mark_sku([], "I-58450", cur2) == 0
    assert not hasattr(cur2, "m104_sku")


# --- prompt ------------------------------------------------------------------------
def test_chunks_jelolt_talalat_ele_kerul_a_kod():
    hits = [_hit(1, "YT-82992", "YATO adapter — 12 990 Ft"), _hit(2, "X-1", "Masik termek")]
    hits[0]["m104_sku"] = "YT-82992"
    out = pr._chunks(hits)
    assert out[0].startswith(pr._m104_line("YT-82992"))
    assert out[0].endswith("YATO adapter — 12 990 Ft")
    assert u"Cikksz\u00e1m: YT-82992" in out[0]
    assert out[1] == "Masik termek"


def test_chunks_jeloles_nelkul_bitre_azonos():
    hits = [_hit(1, "YT-82992", "A"), {"payload": {"text": "KB"}}]
    assert pr._chunks(hits) == ["A", "KB"]

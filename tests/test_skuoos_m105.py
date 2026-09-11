# -*- coding: utf-8 -*-
"""m105: pontos cikkszamra kerdezett, nem raktaros termek is a kontextusba (hide_oos mellett is),
a prompt-sor jelzi, hogy nincs raktaron. Fajl-betoltos import, a prompt.py fake app-modulokkal."""
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


lx = _load("lexmatch_m105", "app/services/lexmatch.py")


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
        return _load("m105_prompt", "app/services/prompt.py")


pr = _load_prompt()

E = [
    (1, lx.fold("Lenovo ThinkCentre neo 55s G6 SFF (13G0001YHX)"), lx.norm_sku("13G0001YHX"), False),
    (2, lx.fold("Lenovo ThinkCentre neo 55s G6 SFF masik"), lx.norm_sku("13G0001YHY"), True),
    (3, lx.fold("Lenovo ThinkCentre tower raktaron"), "x1", True),
    (4, lx.fold("Lenovo ThinkCentre tower elfogyott"), "x2", False),
]


def test_sku_ag_alapbol_szuri_a_nem_raktarost():
    sku, _n, _i = lx.pick(E, "13G0001YHX", [], hide_oos=True)
    assert sku == []


def test_sku_oos_a_pontosan_megnevezett_nem_raktarost_is_hozza():
    sku, _n, _i = lx.pick(E, "13G0001YHX van?", [], hide_oos=True, sku_oos=True)
    assert sku == [1]
    # hide_oos nelkul ugyanaz
    assert lx.pick(E, "13G0001YHX", [], hide_oos=False, sku_oos=True)[0] == [1]


def test_sku_oos_a_nev_agat_nem_lazitja():
    _s, n, _i = lx.pick(E, "lenovo thinkcentre tower", [], hide_oos=True, sku_oos=True)
    assert 4 not in n


def test_sku_oos_exclude_ids_marad():
    assert lx.pick(E, "13G0001YHX", [], hide_oos=True, exclude_ids=[1], sku_oos=True)[0] == []


def test_mark_nem_raktaros_jelolese():
    hits = [{"id": 1, "payload": {"type": "product", "sku": "13G0001YHX", "available": False, "text": "T"}},
            {"id": 2, "payload": {"type": "product", "sku": "YT-82992", "available": True, "text": "U"}}]
    assert lx.mark_sku(hits, "13G0001YHX") == 1
    assert hits[0]["m104_sku"] == "13G0001YHX" and hits[0]["m105_oos"] is True
    assert lx.mark_sku(hits, "YT-82992") == 1
    assert "m105_oos" not in hits[1]


def test_mark_aktualis_termek_nem_raktaros():
    cur = types.SimpleNamespace(sku="I-58450", text="Adatlap", payload={"available": False})
    assert lx.mark_sku([], "I-58450 mérete?", cur) == 1
    assert cur.m105_oos is True
    cur2 = types.SimpleNamespace(sku="I-58450", text="Adatlap", payload={"available": True})
    lx.mark_sku([], "I-58450", cur2)
    assert not hasattr(cur2, "m105_oos")


def test_prompt_sor_raktaron_bitre_a_regi_nem_raktarosnal_jelzes():
    assert pr._m104_line("X-1") == (u"[Cikksz\u00e1m: X-1 \u2014 a l\u00e1togat\u00f3 \u00e1ltal megadott "
                                    u"cikksz\u00e1m ehhez a term\u00e9khez tartozik.]\n")
    oos = pr._m104_line("X-1", True)
    assert u"NINCS rakt\u00e1ron" in oos and oos.endswith(u"]\n")
    hits = [{"payload": {"type": "product", "text": "T"}, "m104_sku": "X-1", "m105_oos": True},
            {"payload": {"type": "product", "text": "U"}, "m104_sku": "X-2"}]
    out = pr._chunks(hits)
    assert u"NINCS rakt\u00e1ron" in out[0] and out[0].endswith("T")
    assert u"NINCS" not in out[1]

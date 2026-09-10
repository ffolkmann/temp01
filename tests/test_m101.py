"""m101: telefonszamos lead, Woo-statusz magyarul, relativ link, datum a promptban,
rendelesi mondat kivetele. Stdlib-modulok fajlbol; a prompt.py fake app-modulokkal,
context managerben (a sys.modules a teszt utan visszaall)."""
import contextlib
import datetime
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


cl = _load("m101_chatlead", "app/services/chatlead.py")
ol = _load("m101_orderlabels", "app/services/orderlabels.py")
lv = _load("m101_linkvalidate", "app/services/linkvalidate.py")


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
        return _load("m101_prompt", "app/services/prompt.py")


pr = _load_prompt()


# --- telefonszamos lead --------------------------------------------------------
def test_csak_telefon_is_lead():
    assert cl.extract_contact("0630/123-4567") == {"email": "", "phone": "0630/123-4567"}
    c = cl.extract_contact("a megadott szám foglalt, kérem hívjanak vissza a +36 30 123 4567 számon")
    assert c == {"email": "", "phone": "+36 30 123 4567"}
    c = cl.extract_contact("vistvan@ gmail.com 06 20 111 2233")
    assert c["email"] == "" and c["phone"] == "06 20 111 2233"
    assert cl.extract_contact("rendelésszám #0630275, e-mail: x@gmail.com") is None
    assert cl.extract_contact("Van raktáron 2 db?") is None


def test_telefon_normalizalas_es_bolt_sajat_szama():
    assert cl.phone_digits("+36 30 623 2322") == "306232322"
    assert cl.phone_digits("06-30-623-2322") == "306232322"
    assert cl.is_known_phone("06 30 623 2322", ["Ugyfelszolgalat: +36 30 623 2322 (H-P)"])
    assert not cl.is_known_phone("06 30 111 2222", ["Ugyfelszolgalat: +36 30 623 2322"])
    assert not cl.is_known_phone("06 30 111 2222", [None, ""])


# --- Woo-statusz -------------------------------------------------------------------
def test_woo_statusz_magyarul():
    assert ol.woo_status_hu("processing") == "Feldolgozás alatt"
    assert ol.woo_status_hu("wc-on-hold").startswith("Függőben")
    assert ol.woo_status_hu("completed") == "Teljesítve"
    assert ol.woo_status_hu("kiszallitas-alatt") == "kiszallitas-alatt"
    assert ol.woo_status_hu("") == "ismeretlen" and ol.woo_status_hu(None) == "ismeretlen"


# --- relativ link -------------------------------------------------------------------
def test_relativ_link_abszolut_lesz():
    out, n = lv.absolutize_links("[FCP lyuk takaro](fcp-univerzalis-lyuk-takaro-1539) 667 Ft",
                                 "https://webshop.4mfrigo.hu/")
    assert n == 1 and "(https://webshop.4mfrigo.hu/fcp-univerzalis-lyuk-takaro-1539)" in out
    out, n = lv.absolutize_links("[a](/termek/x)", "https://bolt.hu")
    assert n == 1 and "(https://bolt.hu/termek/x)" in out
    out, n = lv.absolutize_links("[a](www.bolt.hu/termek/x)", "https://bolt.hu")
    assert n == 1 and "(https://www.bolt.hu/termek/x)" in out


def test_abszolut_es_egyeb_link_erintetlen():
    s = ("[a](https://bolt.hu/x) [m](mailto:info@bolt.hu) [t](tel:+36301234567) "
         "[h](#tab) [k](https://bolt.hu/kereses?keyword=a+b)")
    assert lv.absolutize_links(s, "https://bolt.hu") == (s, 0)
    assert lv.absolutize_links("[a](x-1)", "") == ("[a](x-1)", 0)
    assert lv.absolutize_links("[a](x-1)", "bolt.hu") == ("[a](x-1)", 0)


# --- datum a promptban + rendelesi mondat ------------------------------------------
def test_now_block_formatum():
    b = pr._now_block(datetime.datetime(2026, 9, 10, 14, 5))
    assert "# AKTUALIS IDOPONT" in b
    assert "2026. szeptember 10., csutortok, 14:05" in b
    assert "szombat es a vasarnap nem munkanap" in b
    assert "# AKTUALIS IDOPONT" in pr._now_block()


def _tenant():
    return types.SimpleNamespace(system_prompt="Te vagy a bolt asszisztense.", platform="shoprenter",
                                 public_url="https://bolt.hu", elallas_url="")


def _ctx():
    return pr.PromptContext(page_is_product=False, page_product_name="", page_url="", page_url_norm="")


def test_prompt_dinamikus_resz_datum_es_kivetel():
    static, dynamic = pr.build_system_prompt_parts(_tenant(), [], None, [], _ctx())
    assert "# AKTUALIS IDOPONT" in dynamic and "# AKTUALIS IDOPONT" not in static
    assert "SOHA ne irj a chatbe" in dynamic
    assert "KIVETEL (m101)" in dynamic and "ugyanarra a rendelesre NE kerd ujra az urlapot" in dynamic


# --- bekotes --------------------------------------------------------------------------
def test_bekotes():
    chat = (ROOT / "app/api/chat.py").read_text(encoding="utf-8")
    assert chat.index("m101: (a) relativ") < chat.index("# m98: LINK-UTOVALIDACIO")
    assert "is_known_phone" in chat and "phone_digits" in chat
    osrc = (ROOT / "app/services/order_status.py").read_text(encoding="utf-8")
    assert "woo_status_hu" in osrc

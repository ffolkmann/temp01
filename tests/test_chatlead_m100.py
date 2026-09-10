"""m100: chatbe gepelt e-mail-cim -> lead (source=chat); rendelesszam kontakt nelkul."""
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


cl = _load("m100_chatlead", "app/services/chatlead.py")


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


def _load_intent():
    fakes = {
        "app.models.db_models": _mod("app.models.db_models", Tenant=object),
        "app.services.handoff_offer": _mod("app.services.handoff_offer",
                                           accepted_offer=lambda m, h: False),
        "app.services.chatlead": cl,
    }
    with _fake_modules(fakes):
        return _load("m100_intent", "app/services/intent.py")


it = _load_intent()


def _tenant(platform="shoprenter"):
    return types.SimpleNamespace(platform=platform, api_base="https://x", api_client_id="i",
                                 api_client_secret="s", lead_email="", handoff_keywords=None)


def _ord(msg, platform="shoprenter"):
    return it.detect_order_intent(msg, _tenant(platform), True)


# --- chatlead ---------------------------------------------------------------

def test_kapcsolat_kinyeres():
    assert cl.extract_contact("kovacsotto@gmail.com - Kovacs Otto") == {
        "email": "kovacsotto@gmail.com", "phone": ""}
    assert cl.extract_contact("E-mail címem: abc.def@gmail.com")["email"] == "abc.def@gmail.com"
    c = cl.extract_contact("abc@freemail.hu 0620/3602797")
    assert c["email"] == "abc@freemail.hu" and c["phone"] == "0620/3602797"
    assert cl.extract_contact("abc@gmail.com +36 70 616 0856")["phone"] == "+36 70 616 0856"
    c = cl.extract_contact("Igen, keressenek meg a abc@gamma.co.uk címen. Köszönöm!")
    assert c["email"] == "abc@gamma.co.uk" and c["phone"] == ""
    c = cl.extract_contact("abc@freemail.hu,àrat is kèrek")
    assert c["email"] == "abc@freemail.hu"


def test_nem_lead():
    for s in ("", "   ", "Van raktáron Einhell kompresszor?",
              "rendelésszám #57035, e-mail: abc@freemail.hu",
              "Rendelésszám #31437, e-mail: x@gmail.com",
              "hivjanak: +36 30 623 2322"):
        assert cl.extract_contact(s) is None, s


def test_capture_kapu():
    assert cl.should_capture(None) and cl.should_capture("collect_lead")
    assert not cl.should_capture("order_status_form")
    assert not cl.should_capture("operator_wait")


def test_bolt_sajat_cime():
    d = "kellegyszerszam.hu,www.kellegyszerszam.hu"
    assert cl.is_shop_email("info@kellegyszerszam.hu", d)
    assert cl.is_shop_email("Info@Shop.Kellegyszerszam.hu", d)
    assert not cl.is_shop_email("x@gmail.com", d)
    assert not cl.is_shop_email("x@notkellegyszerszam.hu", d)
    assert not cl.is_shop_email("x@gmail.com", None)
    assert cl.is_shop_email("x@forest4.hu", "https://forest4.mysellvio.com/, forest4.hu")


def test_strip_contacts():
    s = cl.strip_contacts("Címem: abc@gmail.com Tel: 0630/235-7558")
    assert not any(ch.isdigit() for ch in s), s
    s = cl.strip_contacts("e- mail : abc@gmail.com telefon: +36308149415 kérem")
    assert "3630" not in s and "@" not in s
    assert not any(ch.isdigit() for ch in cl.strip_contacts("06 20 360 27 97 hivjanak"))
    assert not any(ch.isdigit() for ch in cl.strip_contacts("06-30-123-4567"))
    assert "21196-121504" in cl.strip_contacts("21196-121504 abc@gmail.com")
    assert "57035" in cl.strip_contacts("rendelésszám #57035, e-mail: abc@freemail.hu")
    assert "1985" not in cl.strip_contacts("kovacs.1985@gmail.com")


# --- intent: rendelesszam kontakt nelkul ------------------------------------

def test_kapcsolat_nem_rendeles():
    for s in ("Címem: abc@gmail.com Tel: 0630/235-7558",
              "e- mail : abc@gmail.com telefon: +36308149415  kérem a kolléga "
              "segítségét, 1 db -ra van szükségem",
              "kovacs.1985@gmail.com",
              "abc@freemail.hu 0620/3602797"):
        assert not _ord(s).is_order_status, s


def test_valodi_rendeles_marad():
    o = _ord("rendelésszám #57035, e-mail: abc@freemail.hu")
    assert o.is_order_status and o.order_id == "57035"
    o = _ord("56514 abc@gmail.com")
    assert o.is_order_status and o.order_id == "56514"
    o = _ord("abc@gmail.com 31533")
    assert o.is_order_status and o.order_id == "31533"
    o = _ord("rendelésszám #7, e-mail: abc@b.hu")
    assert o.is_order_status and o.order_id == "7"
    o = _ord("21196-121071 abc@gmail.com", "unas")
    assert o.is_order_status and o.order_id == "21196-121071"
    o = _ord("a 56862-es rendelesem hol tart? abc@gmail.com")
    assert o.is_order_status and o.order_id == "56862"


# --- bekotes: sorrend a chat.py-ban, forras-sor az ertesitoben --------------

def test_chat_hook_sorrend():
    src = (ROOT / "app/api/chat.py").read_text(encoding="utf-8")
    i_prep = src.index("m100: a chatbe GEPELT")
    i_unans = src.index("await log_unanswered(session, req.client_id, req.session_id, "
                        "message, top_score, parsed.action)")
    i_turn = src.index("await log_turn(session, req.client_id, req.session_id, message, "
                       "parsed.reply, parsed.action)")
    i_store = src.index("await store_lead(session, _req100)")
    assert i_prep < i_unans < i_turn < i_store


def test_ertesito_forras_sor():
    src = (ROOT / "app/services/leads.py").read_text(encoding="utf-8")
    assert 'req.source == "chat"' in src and "chatbe irta" in src

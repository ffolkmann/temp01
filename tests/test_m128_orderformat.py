"""m128 (K4): rendelesszam-alak orseg (orderformat.py, pure) + evszam-FP az intentben + bekotes."""
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


of = _load("m128_orderformat", "app/services/orderformat.py")
cl = _load("m128_chatlead", "app/services/chatlead.py")


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
        return _load("m128_intent", "app/services/intent.py")


it = _load_intent()

SR = ["58344", "58623", "58660", "58573", "57875", "58247", "58797"]
UNAS = ["21196-123449", "21196-123680", "21196-123320", "21196-122772", "21196-123172"]
WD = ["2026/0050954", "2026/0050808", "2026/0050722", "2026/0049794", "0050200", "0050054", "0048147"]


def _tenant(platform="shoprenter"):
    return types.SimpleNamespace(platform=platform, api_base="https://x", api_client_id="i",
                                 api_client_secret="s", lead_email="", handoff_keywords=None)


# --- learn_shapes ------------------------------------------------------------

def test_learn_shapes_sr():
    assert of.learn_shapes(SR) == [("99999", "", 7)]


def test_learn_shapes_unas_prefix():
    assert of.learn_shapes(UNAS) == [("99999-999999", "21196", 5)]


def test_learn_shapes_webdoc_ket_alak():
    s = of.learn_shapes(WD)
    assert s[0] == ("9999/9999999", "2026", 4)
    assert s[1] == ("9999999", "", 3)


def test_learn_shapes_keves_minta_fail_open():
    assert of.learn_shapes(SR[:4]) == []
    assert of.learn_shapes([]) == []
    # 5 minta, de egyik alak sem er el 3-at -> ures
    assert of.learn_shapes(["1", "22", "333", "4444", "55555"]) == []


def test_learn_shapes_vegyes_prefix_nincs():
    ids = ["21196-1", "21197-2", "21198-3", "21199-4", "21100-5"]
    # a kozos elotag ("211") rovidebb a csoportnal -> NINCS prefix
    assert of.learn_shapes(ids) == [("99999-9", "", 5)]


# --- check -------------------------------------------------------------------

def test_check_sr():
    sh = of.learn_shapes(SR)
    assert of.check("58770", sh) == ("ok", "58770")
    assert of.check("#58770", sh) == ("ok", "58770")
    assert of.check("100001", sh) == ("ok", "100001")          # +1 jegy: atlepheti a 99999-et
    for bad in ("5615", "7176", "3076", "9152521", "3420015380", "9", "2018-2024"):
        assert of.check(bad, sh)[0] == "mismatch", bad
    assert of.check("558656", sh) == ("ok", "558656")             # +1 jegy -> az API dont


def test_check_unas_fix():
    sh = of.learn_shapes(UNAS)
    assert of.check("21196-123754", sh) == ("ok", "21196-123754")
    assert of.check("21196123172", sh) == ("fix", "21196-123172")
    assert of.check("#21196123172", sh) == ("fix", "21196-123172")
    for bad in ("21196", "2119612", "0620265", "235-7558", "60", "2026-7317"):
        assert of.check(bad, sh)[0] == "mismatch", bad
    # masik bolt-azonosito ugyanazzal az alakkal: atmegy az API-ra (a prefix nem feltetel)
    assert of.check("12345-123456", sh) == ("ok", "12345-123456")


def test_check_webdoc_csak_rovid_szam():
    sh = of.learn_shapes(WD)
    assert of.check("2026/0050954", sh, platform="webdoc") == ("ok", "2026/0050954")
    assert of.check("2027/0000012", sh, platform="webdoc") == ("ok", "2027/0000012")
    assert of.check("50954", sh, platform="webdoc") == ("ok", "50954")
    assert of.check("6720", sh, platform="webdoc") == ("mismatch", "6720")
    assert of.check("2026", sh, platform="webdoc") == ("mismatch", "2026")


def test_check_fail_open():
    assert of.check("5615", []) == ("ok", "5615")
    assert of.check("", of.learn_shapes(SR)) == ("ok", "")


# --- example / reply ---------------------------------------------------------

def test_example_es_valasz():
    assert of.example(of.learn_shapes(SR)) == "xxxxx (5 számjegy)"
    assert of.example(of.learn_shapes(UNAS)) == "21196-xxxxxx"
    assert of.example(of.learn_shapes(WD)) == "2026/xxxxxxx"
    assert of.example([]) == ""
    r = of.mismatch_reply("5615", of.learn_shapes(SR))
    assert "5615" in r and "xxxxx (5 számjegy)" in r and "visszaigazoló" in r
    assert "elküldtük" not in r
    r2 = of.mismatch_reply("x", [])
    assert "rendelésszám-alakja." in r2


# --- intent: evszam-tartomany nem rendelesszam -------------------------------

def test_intent_evszam_nem_rendeles():
    o = it.detect_order_intent("DEYE csomag 2018-2024 garancia abc@gmail.com rendelés", _tenant(), True)
    assert o.order_id != "2018-2024"
    o = it.detect_order_intent("21196-121071 abc@gmail.com", _tenant("unas"), True)
    assert o.is_order_status and o.order_id == "21196-121071"
    o = it.detect_order_intent("rendelésszám #57035, e-mail: abc@freemail.hu", _tenant(), True)
    assert o.is_order_status and o.order_id == "57035"


# --- bekotes a chat.py-ban ---------------------------------------------------

def test_chat_hook():
    src = (ROOT / "app/api/chat.py").read_text(encoding="utf-8")
    i_rl = src.index("if await rl_is_blocked(rl_key, ORDER_LOOKUP_LIMIT):")
    i_of = src.index("from app.services import orderformat as _of128")
    i_call = src.index("reply, matched = await handle_order_status_ex(tenant, order)")
    i_lead = src.index("_of128.LEAD_OFFER", i_call)   # a 2. (nem matched ag) a lekeres UTAN
    assert i_rl < i_of < i_call < i_lead
    assert src.count("order_lookup_mismatch") == 1
    assert 'action=_act128b' in src

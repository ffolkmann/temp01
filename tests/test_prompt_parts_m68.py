"""m68 - build_system_prompt_parts: a (statikus, dinamikus) par konkatenacioja
byte-ra azonos a build_system_prompt kimenetevel; a statikus resz a tenant-prompt
+ teny-korlat, minden mas a dinamikusban van. Fajlbol toltve, fake app.* modulokkal."""

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]

_app_snapshot = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
for _k in list(_app_snapshot):
    del sys.modules[_k]


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    m.__path__ = []
    sys.modules[name] = m
    return m


for _name in ("app", "app.core", "app.services", "app.models"):
    _mod(_name)

_mod("app.models.db_models", Coupon=type("Coupon", (), {}), Tenant=type("Tenant", (), {}))
_mod("app.services.current_product", CurrentProduct=type("CurrentProduct", (), {}))
_mod("app.services.handoff_offer", prompt_block=lambda: "\n\n# ELO ATADAS FAKE")
_FAKT = "\n\n# TENYEK FAKE BLOKK"
_mod("app.services.factuality", factuality_block=lambda: _FAKT)
_mod("app.services.live_product", LivePriceStock=type("LivePriceStock", (), {}))

spec = importlib.util.spec_from_file_location(
    "prompt_m68_under_test", ROOT / "app" / "services" / "prompt.py")
_prompt = importlib.util.module_from_spec(spec)
sys.modules["prompt_m68_under_test"] = _prompt
spec.loader.exec_module(_prompt)

for _k in [x for x in list(sys.modules) if x == "app" or x.startswith("app.")]:
    del sys.modules[_k]
sys.modules.update(_app_snapshot)


def _tenant(**kw):
    base = dict(system_prompt="Te vagy a bolt asszisztense.", platform="webdoc",
                public_url="https://bolt.hu", elallas_url="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _ctx():
    return _prompt.PromptContext(
        page_is_product=False, page_product_name="", page_url="", page_url_norm="")


def test_concat_equals_legacy():
    t = _tenant()
    args = (t, [], None, [], _ctx())
    static, dynamic = _prompt.build_system_prompt_parts(*args)
    assert static + dynamic == _prompt.build_system_prompt(*args)


def test_static_is_base_plus_factuality():
    static, dynamic = _prompt.build_system_prompt_parts(_tenant(), [], None, [], _ctx())
    assert static == "Te vagy a bolt asszisztense." + _FAKT
    assert "# TUDASBAZIS" not in static
    assert "# TUDASBAZIS" in dynamic
    assert "# VALASZ FORMATUM" in dynamic


def test_operator_block_stays_dynamic():
    t = _tenant()
    s1, d1 = _prompt.build_system_prompt_parts(t, [], None, [], _ctx(), operator_online=False)
    s2, d2 = _prompt.build_system_prompt_parts(t, [], None, [], _ctx(), operator_online=True)
    assert s1 == s2
    assert "# ELO ATADAS FAKE" in d2 and "# ELO ATADAS FAKE" not in d1

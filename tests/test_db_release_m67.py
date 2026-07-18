"""m67 - a /chat lassu szakasza (embedding+qdrant+LLM) DB-kapcsolat NELKUL fut.

A chat.py-t fajlbol toltjuk (suite-konvencio), az OSSZES app.* importjat fake
modulokkal helyettesitve; a hivas-sorrendet a CALLS lista rogziti. A chat.py
futasideju lazy importjait (app.services.superlative) a hivas idejere ideiglenesen
sys.modules-be tett fake fedi. Ellenorizzuk:
  - a session.commit() a kuponok/plan-olvasas UTAN es a retrieve/LLM ELOTT fut,
  - a lassu szakasz alatt a session-hoz nem nyulunk (execute tiltva),
  - a search_fallback esemeny-log az LLM UTAN tortenik (deferred),
  - LLM-hiba eseten a fallback-valasz + log_turn tovabbra is megy.
"""

import asyncio
import importlib.util
import pathlib
import sys
import types

# --- sys.modules snapshot/purge (m52-konvencio: a suite fake-stubjai ellen) ---
_LIBS = ("sqlalchemy", "fastapi", "starlette", "pydantic", "httpx", "anyio")
_lib_snapshot = {
    k: v for k, v in sys.modules.items()
    if any(k == l or k.startswith(l + ".") for l in _LIBS)
}
for _k in list(_lib_snapshot):
    del sys.modules[_k]
import fastapi  # noqa: E402,F401
import pydantic  # noqa: E402,F401
import sqlalchemy  # noqa: E402,F401
import sqlalchemy.ext.asyncio  # noqa: E402,F401

_app_snapshot = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
for _k in list(_app_snapshot):
    del sys.modules[_k]

ROOT = pathlib.Path(__file__).resolve().parents[1]

CALLS: list[str] = []


def _mod(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    m.__path__ = []
    sys.modules[name] = m
    return m


def _rec(name: str, result=None):
    async def _f(*a, **kw):
        CALLS.append(name)
        return result
    return _f


class _FakeSession:
    """A lassu szakasz alatt execute tilos; a commit a CALLS-ba kerul."""

    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1
        CALLS.append("commit")

    async def rollback(self):
        CALLS.append("rollback")

    async def execute(self, stmt):  # a patchelt _get_tenant/_plan_* miatt nem hivodhat
        raise AssertionError("session.execute a stub-tesztben tiltott")


# --- fake app.* modulok a chat.py importjaihoz ---
for _name in ("app", "app.core", "app.services", "app.models", "app.api"):
    _mod(_name)

async def _fake_get_session():
    yield _FakeSession()

_mod("app.core.db", get_session=_fake_get_session)


class _LLMBoom(Exception):
    status_code = None


_LLM = {"raise": False, "reply": "Valasz szoveg."}

async def _generate_reply(system_prompt, history, message, model=None):
    CALLS.append("llm")
    if _LLM["raise"]:
        raise _LLMBoom("llm down")
    return _LLM["reply"]

_mod("app.core.llm", generate_reply=_generate_reply)
_mod("app.core.redis", get_redis=lambda: None)
_mod("app.models.db_models", Plan=type("Plan", (), {}), Tenant=type("Tenant", (), {}))

from pydantic import BaseModel  # noqa: E402


class _ChatRequest(BaseModel):
    model_config = {"extra": "allow"}
    client_id: str = ""
    session_id: str | None = None
    message: str | None = None
    history: list | None = None
    page_context: object | None = None
    type: str | None = None
    event: str | None = None
    url: str | None = None
    title: str | None = None
    order_id: str | None = None
    value: float | None = None
    currency: str | None = None


class _ChatResponse:
    def __init__(self, reply="", action=None, configurator=None, order_form=None):
        self.reply, self.action = reply, action
        self.configurator, self.order_form = configurator, order_form


class _Ref:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_mod(
    "app.models.schemas",
    ChatRequest=_ChatRequest, ChatResponse=_ChatResponse,
    ConfiguratorRef=_Ref, EventAck=_Ref, OrderFormRef=_Ref,
)

_mod(
    "app.services.conversations",
    format_transcript=lambda turns, bot: "", get_transcript=_rec("transcript", []),
    log_turn=_rec("log_turn"),
)
_mod(
    "app.services.events",
    WIDGET_KINDS=set(), count_product_links=lambda reply, tenant: 0,
    log_event=lambda session, cid, sid, kind, meta=None: _rec(f"event:{kind}")(),
)
_mod("app.services.coupons", active_coupons=_rec("coupons", []))
_mod(
    "app.services.current_product",
    get_current_product=_rec("current_product", None), normalize_url=lambda u: str(u or ""),
)
_mod("app.services.feedback", store_feedback=_rec("feedback"))
_mod("app.services.handoff", HANDOFF_REPLY="HR", send_handoff_email=_rec("ho_mail"))

_NO = types.SimpleNamespace(
    is_order_status=False, is_configurator=False, cfg=None, is_handoff=False, page="",
    order_id=None,
)
_mod(
    "app.services.intent",
    detect_configurator=lambda m, t: _NO, detect_handoff=lambda m, t, h, u: _NO,
    detect_order_intent=lambda m, t, la: _NO,
)
_mod("app.services.leads", store_lead=_rec("lead"))
_mod(
    "app.services.live_agent",
    LIVE_AGENT_WAIT_REPLY="WAIT", add_message=_rec("la_add"),
    get_session_state=_rec("la_state", "bot"), poll_messages=_rec("la_poll", []),
    request_operator=_rec("la_req"), session_live_state=_rec("la_live", "bot"),
)
_mod("app.services.live_product", fetch_live_price_stock=_rec("live_ps", None))
_mod("app.services.operator_hours", operators_available=lambda t: False)
_mod("app.services.operator_presence", is_operator_online=_rec("op_online", False))
_mod("app.services.operator_notify", notify_operators=_rec("op_notify"))
_mod(
    "app.services.rate_limit",
    ORDER_LOOKUP_LIMIT=3, ORDER_LOOKUP_WINDOW=600, clear=_rec("rl_clear"),
    is_blocked=_rec("rl_blocked", False), order_lookup_key=lambda c, s: "k",
    register_failure=_rec("rl_fail"),
)
_mod(
    "app.services.order_status",
    ORDER_LOOKUP_BLOCKED_REPLY="BLK", handle_order_status_ex=_rec("order", ("", False)),
)
_mod(
    "app.services.parse_reply",
    parse_reply=lambda raw: types.SimpleNamespace(reply=raw, action=None),
)


class _Ctx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_mod(
    "app.services.prompt",
    PromptContext=_Ctx,
    build_system_prompt=lambda *a, **kw: "SP",
    _shop_search_url=lambda t: "",
)

_RETRIEVE = {"result": ([], 0.9, None)}

async def _retrieve(embed_input, message, client_id, page_url, page_url_norm):
    CALLS.append("retrieve")
    return _RETRIEVE["result"]

_mod("app.services.retrieval", retrieve=_retrieve)
_mod("app.services.search_query", build_queries=lambda m: ["q"])
_mod(
    "app.services.shop_search",
    SEARCH_FB_THRESHOLD=0.2, shop_front_search=_rec("sfb_search", [{"name": "X", "url": "u"}]),
)
_superlative_fake = _mod("app.services.superlative", STOCK_NOTES={}, topic_of=lambda m: "")
_mod("app.services.unanswered", log_unanswered=_rec("log_unanswered"))
_mod("app.services.usage", record_usage=_rec("usage"))
_mod("app.services.webdoc_status", order_form_fields=lambda p: [])

# --- a chat.py betoltese fajlbol a fake importok folott ---
_spec = importlib.util.spec_from_file_location("chat_m67_under_test", ROOT / "app" / "api" / "chat.py")
_chat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_chat)

_chat._plan_live_api = _rec("plan_live", False)
_chat._plan_search_fallback = _rec("plan_sfb", True)

# A chat.py futasideju lazy importja (from app.services.superlative import ...) miatt a
# hivas idejere ezeknek sys.modules-ben KELL lenniuk; a hivason kivul visszaallitjuk.
_LAZY = {
    "app": sys.modules["app"],
    "app.services": sys.modules["app.services"],
    "app.services.superlative": _superlative_fake,
}

# --- sys.modules visszaallitas (mas tesztek ne kapjanak fake app.*/lib modult) ---
for _k in [x for x in list(sys.modules) if x == "app" or x.startswith("app.")]:
    del sys.modules[_k]
sys.modules.update(_app_snapshot)
for _k in [x for x in list(sys.modules)
           if any(x == l or x.startswith(l + ".") for l in _LIBS)]:
    del sys.modules[_k]
sys.modules.update(_lib_snapshot)


def _tenant(**kw):
    base = dict(
        live_agent_enabled=False, welcome_message="Szia!", plan="pro",
        search_fallback=True, chat_model=None, bot_name="Bot", platform="webdoc",
        domain="", public_url="",
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _run(message="melyik a legolcsobb gep?", tenant=None, llm_raise=False):
    CALLS.clear()
    _LLM["raise"] = llm_raise
    t = tenant or _tenant()

    async def _get_tenant(session, cid):
        CALLS.append("get_tenant")
        return t

    _chat._get_tenant = _get_tenant
    req = _chat.ChatRequest(client_id="t1", session_id="s1", message=message, history=[])
    saved = {k: sys.modules.get(k) for k in _LAZY}
    sys.modules.update(_LAZY)
    try:
        return asyncio.run(_chat._handle_message(req, _FakeSession()))
    finally:
        _LLM["raise"] = False
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_commit_before_slow_span():
    _RETRIEVE["result"] = ([], 0.9, None)  # nincs search-fallback
    resp = _run()
    assert resp.reply == "Valasz szoveg."
    assert CALLS.count("commit") == 1
    ci = CALLS.index("commit")
    assert CALLS.index("coupons") < ci
    assert CALLS.index("plan_sfb") < ci
    assert ci < CALLS.index("retrieve") < CALLS.index("llm") < CALLS.index("log_turn")


def test_search_fallback_event_deferred_after_llm():
    _RETRIEVE["result"] = ([], 0.05, None)  # gyenge score -> fallback ag
    _run()
    assert "sfb_search" in CALLS and "event:search_fallback" in CALLS
    assert CALLS.index("commit") < CALLS.index("sfb_search")
    assert CALLS.index("llm") < CALLS.index("event:search_fallback")


def test_no_plan_read_when_tenant_flag_off():
    _RETRIEVE["result"] = ([], 0.05, None)
    _run(tenant=_tenant(search_fallback=False))
    assert "plan_sfb" not in CALLS and "sfb_search" not in CALLS
    assert CALLS.count("commit") == 1


def test_llm_error_fallback_still_logged():
    _RETRIEVE["result"] = ([], 0.9, None)
    resp = _run(message="hali gep?", llm_raise=True)
    assert resp.reply == _chat._FALLBACK
    assert CALLS.index("commit") < CALLS.index("llm") < CALLS.index("log_turn")

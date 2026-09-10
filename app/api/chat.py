"""POST /chat — a CLAUDE.md C.rész szerződése + a prod Chat workflow (7ZtoREZGxJUxLYFU) parity.

A `type` mező multiplexál:
  - nincs type      -> ÜZENET: intent-kaszkád -> retrieval+rerank+current-product+LLM -> {reply, action, configurator}
  - "feedback"      -> 👍/👎 tárolás (válasz ignorálva a widgetben)
  - "lead"          -> lead tárolás + handoff e-mail (stub)

Az ÜZENET-ág a prod sorrendjét követi (lásd seed/prod_retrieval.txt):
  order-status -> configurator -> handoff -> (egyik sem) -> RAG + LLM.

A widget kompatibilitás miatt a route a /webhook/chat útvonalon IS elérhető.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.llm import generate_reply
from app.core.redis import get_redis
from app.models.db_models import Plan, Tenant
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ConfiguratorRef,
    EventAck,
    OrderFormRef,
)
from app.services.conversations import format_transcript, get_transcript, log_turn
from app.services.events import WIDGET_KINDS, count_product_links, log_event
from app.services.coupons import active_coupons
from app.services.current_product import get_current_product, normalize_url
from app.services.feedback import store_feedback
from app.services.handoff import HANDOFF_REPLY, send_handoff_email
from app.services.intent import detect_configurator, detect_handoff, detect_order_intent
from app.services.leads import store_lead
from app.services.live_agent import (
    LIVE_AGENT_WAIT_REPLY,
    add_message as la_add_message,
    get_session_state,
    poll_messages,
    request_operator,
    session_live_state,
)
from app.services.live_product import fetch_live_price_stock
from app.services.tenantgate import is_disabled  # m92
from app.services.operator_hours import operators_available
from app.services.operator_presence import is_operator_online
from app.services.operator_notify import notify_operators
from app.services.rate_limit import (
    ORDER_LOOKUP_LIMIT,
    ORDER_LOOKUP_WINDOW,
    clear as rl_clear,
    is_blocked as rl_is_blocked,
    order_lookup_key as rl_key_for,
    register_failure as rl_register_failure,
)
from app.services.order_status import ORDER_LOOKUP_BLOCKED_REPLY, handle_order_status_ex
from app.services.parse_reply import parse_reply
from app.services.prompt import PromptContext, build_system_prompt_parts
from app.services.retrieval import retrieve
from urllib.parse import quote_plus

from app.services.search_query import build_queries
from app.services.shop_search import SEARCH_FB_THRESHOLD, shop_front_search
from app.services.prompt import _shop_search_url
from app.services.unanswered import log_unanswered
from app.services.usage import record_usage
from app.services.webdoc_status import order_form_fields

logger = logging.getLogger("cx.chat")
router = APIRouter()

_FALLBACK = "Elnézést, most nem tudok válaszolni."
_FALLBACK_BUSY = "Elnézést, éppen nagyon sokan kérdeznek. Kérlek, próbáld újra pár másodperc múlva!"  # m53: 529


async def _get_tenant(session: AsyncSession, client_id: str) -> Tenant | None:
    return (
        await session.execute(select(Tenant).where(Tenant.client_id == client_id))
    ).scalar_one_or_none()


async def _plan_live_api(session: AsyncSession, plan: str | None) -> bool:
    if not plan:
        return False
    row = (
        await session.execute(select(Plan).where(Plan.plan == plan))
    ).scalar_one_or_none()
    return bool(row and row.live_api)


async def _plan_search_fallback(session: AsyncSession, plan: str | None) -> bool:
    if not plan:
        return False
    row = (
        await session.execute(select(Plan).where(Plan.plan == plan))
    ).scalar_one_or_none()
    return bool(row and getattr(row, "search_fallback", False))


async def _handle_message(req: ChatRequest, session: AsyncSession) -> ChatResponse:
    tenant = await _get_tenant(session, req.client_id)
    if tenant is None:
        logger.warning("ismeretlen tenant: %s", req.client_id)
        return ChatResponse(reply=_FALLBACK)

    # m92: KIKAPCSOLT (active=false) tenant -> a bot nem valaszol. Eddig az `active`
    # CSAK a syncet szurte, a chat-vegpont nem nezte: egy tavozo ugyfel boltjaban a
    # widget a lekapcsolas utan is valaszolt volna. A widget maga a /chat-config
    # `disabled` jelzojere meg sem indul el (m92), ez itt a szerver-oldali zar.
    if is_disabled(tenant):
        from fastapi import HTTPException
        logger.info("m92: kikapcsolt tenant, nem valaszolunk: %s", req.client_id)
        raise HTTPException(status_code=404, detail="inactive tenant")

    message = (req.message or "").strip()
    if not message:
        return ChatResponse(reply=tenant.welcome_message or _FALLBACK)

    # --- Élő operátor-átvétel (m28): ha a session már requested/operator, a bot
    #     elnémul (handoff_bot_silent), a látogató üzenete a chat_messages-be kerül,
    #     a widget a válaszokat /chat/poll-lal olvassa. Fail-safe: hiba -> normál bot.
    if getattr(tenant, "live_agent_enabled", False) and req.session_id:
        try:
            la_state = await get_session_state(session, req.client_id, req.session_id)
        except Exception:  # noqa: BLE001
            la_state = "bot"
        if la_state in ("requested", "operator"):
            try:
                await la_add_message(session, req.client_id, req.session_id, "user", message)
            except Exception:  # noqa: BLE001
                logger.exception("live-agent: user-üzenet mentés hiba")
            if la_state == "operator" or bool(getattr(tenant, "handoff_bot_silent", True)):
                return ChatResponse(reply="", action="operator_wait")
            # requested + handoff_bot_silent=False -> a bot tovább válaszol (fall through)

    # usage-accounting: minden bejövő USER üzenet (message +1; conversation ha új session/period)
    await record_usage(session, get_redis(), req.client_id, req.session_id)

    pc = req.page_context
    ctx = PromptContext(
        page_is_product=bool(pc and pc.is_product),
        page_product_name=str(pc.product_name or "") if pc else "",
        page_url=str(pc.url or "") if pc else "",
        page_url_norm=normalize_url(pc.url if pc else ""),
    )

    # --- Pre-LLM intent kaszkád (a prod sorrendjében) ---
    live_api = await _plan_live_api(session, tenant.plan)

    # 1) order-status: a prod élő order-lekérést végez, majd "Send Status Email"-t küld
    #    a vevőnek; a /chat ettől függetlenül SEMLEGES választ ad (adat-szivárgás ellen).
    #    Platform szerinti dispatch (Sellvio/Shoprenter/Unas/WooCommerce) a service-ben.
    order = detect_order_intent(message, tenant, live_api)
    if order.is_order_status:
        # m29: rate limit — a Webdocnál a rendelés id-je a rendelésszámból számolható,
        # és a szolgáltatónál nincs szerver-oldali korlát; a masodlagos titok az irsz.
        rl_key = rl_key_for(req.client_id, req.session_id)
        if await rl_is_blocked(rl_key, ORDER_LOOKUP_LIMIT):
            await log_turn(session, req.client_id, req.session_id, message,
                           ORDER_LOOKUP_BLOCKED_REPLY)
            await log_event(session, req.client_id, req.session_id, "order_lookup_blocked",
                            {"order_id": order.order_id})
            return ChatResponse(reply=ORDER_LOOKUP_BLOCKED_REPLY, action=None)

        reply, matched = await handle_order_status_ex(tenant, order)
        if matched:
            await rl_clear(rl_key)          # a johiszemu vevot ne buntessuk
        else:
            await rl_register_failure(rl_key, ORDER_LOOKUP_WINDOW)
        await log_turn(session, req.client_id, req.session_id, message, reply)
        await log_event(session, req.client_id, req.session_id, "order_lookup",
                        {"order_id": order.order_id, "matched": matched})
        return ChatResponse(reply=reply, action=None)

    # 2) configurator (csak configurator_shop tenantnál)
    cfg = detect_configurator(message, tenant)
    if cfg.is_configurator and cfg.cfg:
        cfg_reply = (
            "Szívesen segítek kiszámolni a klíma telepítés becsült díját! "
            "Kérlek, töltsd ki az alábbi pár kérdést."
        )
        await log_turn(
            session, req.client_id, req.session_id, message, cfg_reply, "quote_configurator"
        )
        await log_event(session, req.client_id, req.session_id, "configurator", None)
        return ChatResponse(
            reply=cfg_reply,
            action="quote_configurator",
            configurator=ConfiguratorRef(**cfg.cfg),
        )

    # m32: van-e EPPEN online ugyintezo ehhez a tenanthoz? (a handoff-ag es a prompt is
    # hasznalja; a Redist csak akkor kerdezzuk, ha az elo atvetel be van kapcsolva)
    op_online = False
    if getattr(tenant, "live_agent_enabled", False) and operators_available(tenant):
        op_online = await is_operator_online(tenant.client_id)

    # 3) handoff
    ho = detect_handoff(message, tenant, req.history, ctx.page_url)
    if ho.is_handoff:
        # m28: élő operátor-átvétel (ha be van kapcsolva ÉS van session) -> várólistára;
        #      a bot elnémul, a látogató a /chat/poll-on kapja az operátor válaszait.
        #      Fail-safe: bármi hiba -> a régi e-mailes handoff ág (lentebb).
        if op_online and req.session_id:  # m28/m30/m32: bekapcsolva + nyitva + online pult
            try:
                # az eddigi (bot-)átirat mint kontextus az operátornak (system-üzenet)
                turns = await get_transcript(session, req.client_id, req.session_id)
                if turns:
                    ctx_txt = format_transcript(turns, tenant.bot_name or "Bot")
                    await la_add_message(
                        session, req.client_id, req.session_id, "system",
                        f"[Beszélgetés előzménye]\n{ctx_txt}",
                    )
                await request_operator(session, req.client_id, req.session_id)
                await la_add_message(session, req.client_id, req.session_id, "user", message)
                await log_turn(
                    session, req.client_id, req.session_id, message,
                    LIVE_AGENT_WAIT_REPLY, "operator_wait",
                )
                await log_event(
                    session, req.client_id, req.session_id, "handoff",
                    {"page": ho.page, "mode": "live"},
                )
                # m28 fázis5: Telegram-ping az operátor(ok)nak — fail-safe (a Telegram-
                #   hiba NE okozzon e-mail-fallbacket, ezért külön try/except).
                try:
                    await notify_operators(tenant, message)
                except Exception:  # noqa: BLE001
                    logger.exception("live-agent: Telegram-ping hiba (nem kritikus)")
                return ChatResponse(reply=LIVE_AGENT_WAIT_REPLY, action="operator_wait")
            except Exception:  # noqa: BLE001 — élő átvétel hiba -> essünk vissza e-mailre
                logger.exception("live-agent: átvétel-kérés hiba, e-mail handoff fallback")
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001
                    pass

        # e-mailes handoff (eredeti viselkedés / fallback)
        # előbb logolunk, hogy az aktuális kérés IS benne legyen a teljes átiratban
        await log_turn(
            session, req.client_id, req.session_id, message, HANDOFF_REPLY, "collect_lead"
        )
        turns = await get_transcript(session, req.client_id, req.session_id)
        transcript = format_transcript(turns, tenant.bot_name or "Bot") if turns else None
        await send_handoff_email(req.client_id, ho, transcript=transcript)
        await log_event(session, req.client_id, req.session_id, "handoff", {"page": ho.page})
        return ChatResponse(reply=HANDOFF_REPLY, action="collect_lead")

    # --- RAG + LLM ---
    # embed-input: termékoldalon a termék neve + üzenet, különben csak az üzenet.
    # m24: rövid follow-upnál ("bojlik érdekelnek") a téma/márka kiesne a kereső-
    # queryből -> az előző user-üzenetet prepend-eljük az embed-inputhoz. A rerank
    # `message` paramétere VÁLTOZATLANUL az eredeti üzenet (parity).
    embed_input = (
        f"{ctx.page_product_name}. {message}"
        if ctx.page_is_product and ctx.page_product_name
        else message
    )
    if len(message) <= 48 and not (ctx.page_is_product and ctx.page_product_name):
        try:
            prev_turns = await get_transcript(session, req.client_id, req.session_id)
            prev_q = str(prev_turns[-1].question or "").strip() if prev_turns else ""
            if prev_q and prev_q.lower() not in message.lower():
                embed_input = f"{prev_q[:120]}. {message}"
        except Exception:  # noqa: BLE001 — kontextus-dúsítás hibája ne törje a chatet
            pass
    # --- m67: DB-kapcsolat elengedése a lassú szakaszra ---
    # Minden még szükséges DB-olvasást ELŐRE hozunk (plan search_fallback flag,
    # kuponok), majd a commit() a kapcsolatot visszaadja a poolba (expire_on_commit=False
    # -> a már betöltött ORM-objektumok használhatók maradnak). Az embedding + qdrant +
    # külső HTTP + LLM (akár 25 mp) így KAPCSOLAT NÉLKÜL fut; a záró írások friss,
    # rövid kapcsolatot kérnek. (m65/m66 incidens: "idle in transaction" -> pool-kimerülés.)
    search_fb_allowed = False
    if bool(getattr(tenant, "search_fallback", False)):
        try:
            search_fb_allowed = await _plan_search_fallback(session, tenant.plan)
        except Exception:  # noqa: BLE001 — a flag-olvasás hibája ne törje a chatet
            search_fb_allowed = False
    coupons = await active_coupons(session, req.client_id)
    await session.commit()  # m67: kapcsolat vissza a poolba a lassú szakaszra

    _hide_oos = not bool(getattr(tenant, "recommend_out_of_stock", False))  # m73: default TILT
    # m80: rovid, megkotes-jellegu follow-up ("es ASUS markajuak kozul?") orokli az
    # elozo user-kerdes ar-szuperlativuszat a determinisztikus detektoroknak
    # (superlative/usage/constraints/topic) -- igy a 2. korben is a teljes
    # keszlet-szurt pool + brand-szures fut, nem a szuk top-k. Konzervativ gate:
    # csak ha az aktualis uzenet rovid, onmaga megkotest tartalmaz (brand/meret/
    # tipus), szuperlativuszt viszont nem, az elozo user-kerdes pedig igen.
    _det_msg = message
    try:
        if req.history and len(message) <= 60:
            from app.services.paramextract import detect_constraints as _dc80
            from app.services.superlative import detect_price_superlative as _dps80
            if _dc80(message, req.client_id) and not _dps80(message):
                _prev_u = [
                    str(getattr(h, "content", "") or "") for h in req.history
                    if str(getattr(h, "role", "") or "") == "user"
                ]
                # m80b: nem csak a kozvetlen elozo user-uzenet -- a lancolt
                # follow-upnal ("uzleti notebook" -> "es ASUS?" -> "es Lenovo?")
                # az utolso ar-szuperlativuszos user-kerdesig keresunk vissza
                _anchor = next((u for u in reversed(_prev_u) if _dps80(u)), None)
                if _anchor:
                    _det_msg = _anchor.strip() + " " + message
                    logger.info("m80 follow-up merge client=%s: %r", req.client_id, _det_msg[:120])
    except Exception:  # noqa: BLE001 - a merge hibaja ne torje a chatet
        _det_msg = message
    hits, top_score, _rmode = await retrieve(
        embed_input, _det_msg, req.client_id, ctx.page_url, ctx.page_url_norm, hide_oos=_hide_oos
    )
    current = await get_current_product(req.client_id, ctx.page_url_norm)
    # élő ár/készlet a megnyitott termékre (plan.live_api-gated, csak termékoldalon);
    # FAIL-SAFE: hiba/None -> a synced adatlap marad
    live = None
    if ctx.page_is_product and live_api and current is not None:
        live = await fetch_live_price_stock(tenant, current)
    # webshop-kereso fallback (m25): gyenge score-nal a bolt sajat keresoje ad jelolteket
    shop_hits: list[dict] | None = None
    _sfb_meta: dict | None = None
    if top_score < SEARCH_FB_THRESHOLD and search_fb_allowed:
        try:
            shop_hits = await shop_front_search(tenant, message)
            if shop_hits:
                _sfb_meta = {"q": message[:80], "n": len(shop_hits)}
        except Exception:  # noqa: BLE001 — a fallback hibaja ne torje a chatet
            logger.exception("search_fallback hiba")
            shop_hits = None
    from app.services.superlative import STOCK_NOTES  # m58
    if _hide_oos and not _rmode:
        _rmode = "oos_guard"  # m73: = superlative.OOS_GUARD -- kemeny OOS-tilto szabaly a promptba
    # m68: (statikus, dinamikus) system-par -> a llm.py cache_control-lal kuldi
    _rnote = STOCK_NOTES.get(_rmode, "")
    # m77: ismetelt ar-kerdesnel a modell a sajat korabbi (elavult) valaszat masolta a
    # friss kontextus elleneben — history jelenleteben explicit feluliras a jegyzetben.
    if req.history and _rnote:
        _rnote += (
            " FIGYELEM: ha a beszelgetes korabbi valaszaiban mas termeket neveztel a"
            " legolcsobbnak/legjobbnak, az a valasz ELAVULT. Kizarolag a MOSTANI"
            " # TUDASBAZIS talalataibol valassz, akkor is, ha ez ellentmond a korabbi"
            " valaszodnak, es roviden jelezd, hogy pontositod a korabbi informaciot."
        )
    system_prompt = build_system_prompt_parts(
        tenant, hits, current, coupons, ctx, live=live, shop_search=shop_hits,
        operator_online=op_online, retrieval_note=_rnote,
    )

    try:
        raw = await generate_reply(system_prompt, req.history, message, model=getattr(tenant, "chat_model", None))
        # m77: onismetles-orseg — ar-modban a modell hajlamos a korabbi (elavult)
        # "legolcsobb" valaszat bajtra ujramasolni a friss kontextus elleneben.
        # Determinisztikus ellenorzes: ha a kontextus minimum-ara nincs a valaszban,
        # EGYSZERI ujrageneralas az assistant-fordulok nelkul (bizonyitottan jo ut).
        if req.history and _rmode in ("stock_filtered", "oos_guard"):
            try:
                _prices = []
                for _h in hits:
                    _pl = (_h.get("payload", {}) or {}) if isinstance(_h, dict) else {}
                    if str(_pl.get("type") or "") == "product":
                        _rawp = str(_pl.get("price") or "").replace(" ", "").replace("\u00a0", "")
                        try:
                            _prices.append((int(float(_rawp)), str(_pl.get("name") or "")))
                        except (TypeError, ValueError):
                            pass
                _minpair = min(_prices) if _prices else None
                _minp = _minpair[0] if _minpair else None
                _minname = (_minpair[1] if _minpair else "").strip()[:110]
                # m78: csak VALODI onismetlesnel regen — a valasz normalizaltan
                # ~azonos egy korabbi assistant-fordulattal ES a kontextus-minimum
                # hianyzik belole. Az ar-minimum onmagaban NEM trigger (megkoteses
                # szuperlativusznal a helyes ar != pool-minimum, m78 bug). Regen
                # TELJESEN ures historyval — a user-only regen arva user-kerdesekre
                # valaszolgatott (irrelevans bevezeto bekezdesek).
                from app.services.paramextract import build_filter_conditions as _bfc80c, detect_constraints as _dc80c  # m80c
                from app.services.policy_filter import is_policy_query as _ipq80  # m80b
                from app.services.facetdict import detect_facet_tags as _dft80c  # m82c
                from app.services.linkfacet import load_map as _lm80c  # m82c
                from app.services.selfrepeat import has_stale_price, is_self_repeat
                _olds = []
                for _t in req.history:
                    if getattr(_t, "role", "") == "assistant":
                        _c = getattr(_t, "content", None) or (_t.get("content") if isinstance(_t, dict) else None) or getattr(_t, "text", "") or ""
                        _olds.append(str(_c))
                # m82c: a generikus facets-szures is Qdrant-szurt poolt jelent
                # (a kivezetett m76-os usage-ag helyett) -- ez nyitja a gate-et
                try:
                    # m82c/2: ugyanaz a kategoria-kapu, mint a retrieval-oldalon
                    # (kerdes-kategoria elsobbseggel), kulonben a gate mast lat,
                    # mint amivel a pool tenylegesen szurve lett
                    from app.services.facetdict import detect_category as _dcat80c
                    from app.services.retrieval import category_catalog as _cc80c
                    _fdt80c = _dft80c(
                        _det_msg,
                        [str((_h.get("payload") or {}).get("category") or "") for _h in (hits or [])],
                        _lm80c(req.client_id),
                        category=_dcat80c(_det_msg, await _cc80c(req.client_id)),
                    )
                except Exception:  # noqa: BLE001
                    _fdt80c = []
                _nraw = (raw or "").replace(" ", "").replace("\u00a0", "")
                if (
                    _minp is not None
                    and str(_minp) not in _nraw
                    and not _ipq80(message)  # m80b: policy-valaszban nincs pool-min-ar
                    and (
                        is_self_repeat(raw, _olds)
                        or has_stale_price(raw, _olds)
                        # m80c: Qdrant-szurt poolnal (brand/p_* must vagy usage-cimke)
                        # a pool-minimum megbizhatoan a helyes valasz -- ha hianyzik,
                        # regen ismetles-gyanu nelkul is (LLM-variancia: "uzleti =
                        # Expertbook sorozat" felreertelmezes a 175 990-es Vivobook
                        # helyett). A link-only meret-kulcsok NEM nyitjak a gate-et.
                        or (
                            _rmode == "stock_filtered"
                            and bool(_bfc80c(_dc80c(_det_msg, req.client_id)) or _fdt80c)
                        )
                    )
                ):
                    logger.info("m78 self-repeat guard: regen ures historyval (client=%s min=%s)", req.client_id, _minp)
                    # m80c: a regen determinisztikus hintet kap -- ures history
                    # onmagaban nem eleg, ha a modell a KONTEXTUSBOL valasztja a
                    # rosszabb talalatot (pl. "uzleti = Expertbook sorozat")
                    _hint = (
                        "\n\n# GUARD - LEGOLCSOBB SZURT TALALAT (determinisztikus adat)\n"
                        "A szuresi felteteleknek megfelelo legolcsobb, raktaron levo termek: "
                        + _minname + " - " + f"{_minp:,}".replace(",", " ") + " Ft. "
                        "Ar-szuperlativuszos kerdesnel EZT a termeket nevezd meg elsokent."
                    )
                    if isinstance(system_prompt, (tuple, list)) and len(system_prompt) == 2:
                        _sp2 = (system_prompt[0], (system_prompt[1] or "") + _hint)
                    else:
                        _sp2 = str(system_prompt) + _hint
                    raw = await generate_reply(_sp2, [], message, model=getattr(tenant, "chat_model", None))
            except Exception:  # noqa: BLE001 — az orseg hibaja ne torje a valaszt
                pass

        # m87: NEM-LATIN SZO-ORSEG. Eles ugyfel-bejelentes (notebookstore): a valaszban
        # ukran/orosz szo jelent meg ("Fontos: ez a <cirill> ar a most elerheto adataim
        # alapjan"). MERES (tools/m87_langscan.py, 3767 valodi tarolt valasz): 10 szivargas
        # = 0,27% (notebookstore 1,0%), es a kontextus-kapu utan UGYANANNYI -> 0 hamis
        # pozitiv, tehat az egyszeri regen koltsege elhanyagolhato (szemben a m77 62%-os
        # tuzelesevel). A m77 tanulsaga: erre prompt-szabaly NEM eleg, kod-szintu
        # utoellenorzes kell a mar legeneralt valaszon. Harom retegu: eszlel -> regen
        # nyelvi hinttel -> ha az is szivarog, determinisztikus tisztitas.
        try:
            from app.services.langguard import foreign_tokens as _ft87
            from app.services.langguard import strip_foreign as _sf87
            _allow87 = " ".join(
                str((_h.get("payload") or {}).get("name") or "")
                + " " + str((_h.get("payload") or {}).get("text") or "")
                for _h in (hits or []) if isinstance(_h, dict)
            )
            _bad87 = _ft87(raw or "", _allow87)
            if _bad87:
                logger.warning(
                    "m87 langguard: nem-latin szo a valaszban %r -> regen (client=%s)",
                    _bad87[:5], req.client_id)
                _hint87 = (
                    "\n\n# GUARD - NYELV (determinisztikus szabaly)\n"
                    "A valasz KIZAROLAG magyar nyelvu es LATIN betus lehet. Cirill, gorog "
                    "vagy barmilyen mas irasrendszeru karakter NEM szerepelhet benne."
                )
                if isinstance(system_prompt, (tuple, list)) and len(system_prompt) == 2:
                    _sp87 = (system_prompt[0], (system_prompt[1] or "") + _hint87)
                else:
                    _sp87 = str(system_prompt) + _hint87
                _raw87 = None
                try:
                    _raw87 = await generate_reply(
                        _sp87, req.history, message,
                        model=getattr(tenant, "chat_model", None))
                except Exception:  # noqa: BLE001 — a regen hibaja ne torje a valaszt
                    _raw87 = None
                if _raw87 and not _ft87(_raw87, _allow87):
                    raw = _raw87
                else:
                    logger.warning(
                        "m87 langguard: a regen is szivargott -> determinisztikus tisztitas "
                        "(client=%s)", req.client_id)
                    raw = _sf87(_raw87 or raw, _allow87)
        except Exception:  # noqa: BLE001 — az orseg hibaja ne torje a valaszt
            pass
    except Exception as _llm_err:  # noqa: BLE001 — a widget mindig kapjon választ
        logger.exception("LLM hívás hiba")
        _fb = _FALLBACK_BUSY if getattr(_llm_err, "status_code", None) == 529 else _FALLBACK
        await log_turn(session, req.client_id, req.session_id, message, _fb)
        return ChatResponse(reply=_fb)

    parsed = parse_reply(raw)
    # m99: a JSON-hibas tartalek-valasz ("Hagyd meg az e-mail-cimed") okat eddig nem
    # lattuk (napi ~0,5 eset, e-mailt megado uzenetre is) -> a nyers kimenet a logba
    try:
        from app.services.parse_reply import _FALLBACK as _prfb99
        if parsed.reply == _prfb99:
            logger.warning("m99 parse fallback: raw_len=%d raw=%r client=%s",
                           len(str(raw or "")), str(raw or "")[:500], req.client_id)
    except Exception:  # noqa: BLE001 - a naplozas sose torje a valaszt
        pass
    # m102/1: UJRAKOSZONES-ORSEG. d10c: a folyamatban levo beszelgetesek nem-elso
    # koreinek 11%-a (fishingoutlet 24%) "Szia!"-val kezdodott, holott a latogato nem
    # koszont ujra. Determinisztikus levagas (stilus-hibara a prompt nem eleg, m77).
    # Csak ha van korabbi bot-valasz a history-ban. Fail-safe: hiba -> valtozatlan.
    try:
        from app.services.greetguard import strip_regreet as _srg102
        _new102g = _srg102(parsed.reply, message, req.history)
        if _new102g != parsed.reply:
            logger.info("m102/1 regreet: koszones levagva client=%s", req.client_id)
            try:
                parsed.reply = _new102g
            except Exception:  # noqa: BLE001 - frozen dataclass eseten
                from dataclasses import replace as _dc_replace102g
                parsed = _dc_replace102g(parsed, reply=_new102g)
    except Exception:  # noqa: BLE001 - az or hibaja sose torje a valaszt
        pass
    # m89: ZARO-LINK KAPU - a "Tovabbi talalatok" kereso-link CSAK akkor, ha a
    # beszelgetes TERMEKRE iranyul. Merve 3526 valodi valaszon: a linkesek 14,1%-a
    # policy-kerdesre ment ki (notebookstore: 96-bol 89). Fail-safe: hiba eseten
    # a mai viselkedes (link kimegy).
    _link_ok = True
    _link_ok_shop = True
    _lg_why89s = "ok"
    try:
        from app.services.linkgate import should_offer_link as _sol89
        from app.services.policy_filter import is_policy_query as _ipq89
        _pol89 = _ipq89(message)
        _link_ok, _lg_why89 = _sol89(message, hits, _pol89)
        # m89/1: a m25 (search_fallback) agon a BOLT SAJAT keresoje adta a
        # talalatokat -> ott a "nincs termek a kontextusban" fail-safe hibasan
        # vagna (a Qdrant-pool eppen azert gyenge, mert emiatt indult a bolti
        # kereses; a shop_hits elemeknek nincs payload kulcsuk sem). Merve 583
        # valodi fallback-kerdesen: 391 (67,1%) veszne el. A kerdes-oldali
        # hard-stopok (policy / rendeles / bolt-info / koszones) ott is elnek.
        _link_ok_shop, _lg_why89s = _sol89(message, None, _pol89, True)
        if not _link_ok:
            logger.info("m89 link gate: nincs zaro-link (%s) client=%s",
                        _lg_why89, req.client_id)
    except Exception:  # noqa: BLE001 - a kapu hibaja sose torje a valaszt
        _link_ok = True
        _link_ok_shop = True
    # m99: rendeles-urlapos (order_status_form) valaszra, es olyan uzenetre, amiben a
    # latogato e-mail-cimet / telefonszamot / rendelesszamot irt, nincs zaro kereso-link
    # (d10a, m95 ota: 56 rendeles-urlapos + 27 szemelyes-adatos link, 17-ben az e-mail
    # a kereso-URL-ben). Fail-safe: hiba eseten a mai viselkedes.
    try:
        from app.services.linkterm import has_pii as _hp99
        _of99 = getattr(parsed, "action", None) == "order_status_form"
        if _of99 or _hp99(message):
            if _link_ok or _link_ok_shop:
                logger.info("m99 link gate: nincs zaro-link (%s) client=%s",
                            "rendeles-urlap" if _of99 else "szemelyes adat", req.client_id)
            _link_ok = False
            _link_ok_shop = False
    except Exception:  # noqa: BLE001 - a kapu hibaja sose torje a valaszt
        pass
    # m102: BOLTI TEMA - kupon, nyitvatartas, szemelyes atvetel, "mikor jon meg",
    # telefon/ugyfelszolgalat, reszlet/hitel/utalas, szamla, regisztracio. Merve
    # (d10c, 1886 valasz 08-27 ota): 107 zaro kereso-link ment ki ilyen kerdes ala.
    # Csak akkor vagunk, ha a valasz NEM linkel kontextusbeli termeket (vegyes
    # kerdesnel a kereso-link marad). Fail-safe: hiba eseten a mai viselkedes.
    try:
        if _link_ok or _link_ok_shop:
            from app.services.linkgate import shop_topic as _st102
            from app.services.linkgate import reply_has_product_link as _rpl102
            # m102/3: identitas-/meta-kerdes ("Hogy hivnak?", "Te vagy Sanyi?",
            # "robot vagy?", "bena robot vagy") - d10d: 6/6 ertelmetlen termu link.
            from app.services.linkgate import meta_topic as _mt102
            _w102 = "bolti tema" if _st102(message) else (
                "identitas/meta" if _mt102(message) else "")
            if _w102 and not _rpl102(parsed.reply, hits, shop_hits):
                logger.info("m102 link gate: nincs zaro-link (%s) client=%s",
                            _w102, req.client_id)
                _link_ok = False
                _link_ok_shop = False
    except Exception:  # noqa: BLE001 - a kapu hibaja sose torje a valaszt
        pass
    # m62: szuperlativusz/keszlet-modnal determinisztikus kereso-link a valasz vegen
    # (mint az m25-os zarolink) — a latogato egy kattintassal a bolt keresojeben folytathatja.
    if _rmode and not shop_hits and _link_ok:  # m89 kapu
        _su2 = _shop_search_url(tenant)
        # m82e/2: a dedup korabban a KERESO-alap URL-re nezett, ezert ha a modell
        # sajat maga beirt egy /termek-kereses?k=... linket a szovegbe, az EGESZ
        # blokk kimaradt -- vele a m79b/m82b fasetta-link is (eles eset: az
        # onboarding B, "es ASUS markajuak kozul?" -> nem jott a .../asus link).
        # Mostantol a kapu csak a markert nezi, a tenyleges URL-re valo dedup
        # pedig lentebb, a MAR KISZAMOLT _more_url ellen tortenik.
        if _su2 and u"További találatok a webáruházban" not in parsed.reply:
            from app.services.superlative import topic_of as _topic_of  # pure fuggveny
            # m79a: a zaro link keresoterme a kontextus-talalatok nevebol jon
            # (a bolt sajat elnevezese -> garantalt talalat a keresoben),
            # fallback: toltelekszo-mentes rovid topic. A teljes kerdes-frazis
            # k= parametere a Webdoc keresoben 0 talalatot adott (m79 bug).
            from app.services.linkterm import link_search_term
            _hn = []
            _hb = []
            _hc = []
            try:
                for _h2 in hits or []:
                    _pl2 = (_h2.get("payload", {}) or {}) if isinstance(_h2, dict) else {}
                    if str(_pl2.get("type") or "") == "product" and _pl2.get("name"):
                        _hn.append(str(_pl2.get("name")))
                        if _pl2.get("brand"):
                            _hb.append(str(_pl2.get("brand")))
                        if _pl2.get("category"):
                            _hc.append(str(_pl2.get("category")))
            except Exception:  # noqa: BLE001 — a linkterm hibaja ne torje a valaszt
                _hn = []
            # m95: a nev-alapu kereso-term csak akkor ervenyes, ha a latogato
            # SAJAT szavaibol (aktualis + korabbi uzenetek) levezetheto —
            # kulonben a pool zaja (eles eset: "jelgenerator" kerdesre
            # search=forrasztopaka). Ha term nem all elo -> nincs zaro-link.
            _uctx95 = message
            try:
                _uctx95 = message + " " + " ".join(
                    str(getattr(h, "content", "") or "") for h in (req.history or [])
                    if str(getattr(h, "role", "") or "") == "user")
            except Exception:  # noqa: BLE001 — a kapu hibaja sose torje a valaszt
                _uctx95 = message
            _q2 = link_search_term(message, _hn, _hb, context=_uctx95)
            _more_url = (_su2 + quote_plus(_q2)) if _q2 else None  # m95
            _more_url_base = _more_url  # m82b: valtozott-e a m79b fasetta-linkre
            # m79b: ha a kerdesben felismert megkotes van (paramextract) es letezik
            # hozza fasetta/SEO-szuro-oldal a crawl-terkepben (linkfacet), arra
            # linkelunk; kulonben marad az m79a kereso-link (fail-safe).
            try:
                from app.services.linkfacet import facet_link as _fl79b
                from app.services.linkfacet import load_map as _lm79b
                from app.services.paramextract import detect_constraints as _dc79b
                _cons79b = _dc79b(_det_msg, req.client_id)  # m80: follow-up merge-elt szoveg
                if _cons79b and _hc:
                    _fu79b = _fl79b(
                        str(getattr(tenant, "public_url", "") or ""),
                        _hc, _cons79b, _lm79b(req.client_id),
                    )
                    if _fu79b:
                        _more_url = _fu79b
                        logger.info("m79b facet link: %s client=%s", _fu79b, req.client_id)
            except Exception:  # noqa: BLE001 - a facet-link hibaja ne torje a valaszt
                pass
            # m82b: ha a m79b-nek nem volt megkotese/linkje, de a generikus
            # szotar felismert bolt-szurot, arra linkelunk (ugyanaz a
            # kategoria-kapu, mint a retrieval-oldali szuresnel)
            try:
                if _more_url == _more_url_base and _hc:
                    from app.services.facetdict import detect_facet_tags as _dft82
                    from app.services.facetdict import facet_tag_url as _ftu82
                    from app.services.linkfacet import load_map as _lm82
                    from app.services.facetdict import detect_category as _dcat82  # m82c/2
                    from app.services.retrieval import category_catalog as _cc82  # m82c/2
                    _fmap82 = _lm82(req.client_id)
                    # m82c/2: a zaro-link is a kerdes kategoriajara mutat
                    _qcat82 = _dcat82(_det_msg, await _cc82(req.client_id))
                    _fu82 = _ftu82(
                        str(getattr(tenant, "public_url", "") or ""),
                        _hc, _dft82(_det_msg, _hc, _fmap82, category=_qcat82), _fmap82,
                        category=_qcat82,
                    )
                    if _fu82:
                        _more_url = _fu82
                        logger.info("m82b facet link: %s client=%s", _fu82, req.client_id)
            except Exception:  # noqa: BLE001 - a facet-link hibaja ne torje a valaszt
                pass
            # m82f/2: ha se megkotes-, se cimke-link nincs, de a KERDESBOL
            # feloldodott a kategoria, a kategoria-oldalra linkelunk (a m79a
            # kereso-link egy talalatnevbol vett kulcsszoval dolgozik).
            try:
                if _more_url == _more_url_base:
                    from app.services.facetdict import category_url as _cu82f
                    from app.services.facetdict import detect_category as _dcat82f
                    from app.services.linkfacet import load_map as _lm82f
                    from app.services.retrieval import category_catalog as _cc82f
                    _qc82f = _dcat82f(_det_msg, await _cc82f(req.client_id))
                    _fu82f = _cu82f(
                        str(getattr(tenant, "public_url", "") or ""),
                        [], _lm82f(req.client_id), category=_qc82f,
                    ) if _qc82f else None
                    if _fu82f:
                        _more_url = _fu82f
                        logger.info("m82f category link: %s client=%s",
                                    _fu82f, req.client_id)
            except Exception:  # noqa: BLE001 - a link hibaja ne torje a valaszt
                pass
            if not _more_url:
                logger.info(
                    "m95 link gate: nincs a latogato szavaibol levezetheto "
                    "keresoszo -> nincs zaro-link client=%s", req.client_id)
            if _more_url and _more_url not in parsed.reply:  # m82e/2
                _newreply2 = (
                    parsed.reply.rstrip()
                    + u"\n\n[További találatok a webáruházban](" + _more_url + u")"
                )
                try:
                    parsed.reply = _newreply2
                except Exception:  # noqa: BLE001 — frozen dataclass eseten
                    from dataclasses import replace as _dc_replace2
                    parsed = _dc_replace2(parsed, reply=_newreply2)
    # m25: search_fallback zaro-link determinisztikusan (az LLM nem mindig teszi be magatol)
    if shop_hits and not _link_ok_shop:
        logger.info("m89 link gate (bolti kereses): nincs zaro-link (%s) client=%s",
                    _lg_why89s, req.client_id)
    if shop_hits and _link_ok_shop:  # m89/1 kapu (a bolti talalat = termek-kontextus)
        _su = _shop_search_url(tenant)
        if _su and _su not in parsed.reply and "További találatok a webáruházban" not in parsed.reply:
            _q = quote_plus((build_queries(message) or [message[:60]])[0])
            _newreply = parsed.reply.rstrip() + "\n\n[További találatok a webáruházban](" + _su + _q + ")"
            try:
                parsed.reply = _newreply
            except Exception:  # noqa: BLE001 — frozen dataclass eseten
                from dataclasses import replace as _dc_replace
                parsed = _dc_replace(parsed, reply=_newreply)
    # m102: ha a kapu a zaro-linket NEM engedte, az LLM altal (a m25 prompt-utasitasra)
    # maga beirt "Tovabbi talalatok" linket is levesszuk (08-27 ota 3 ilyen szivargas,
    # de a m102-es bolti temaknal a bolti kereso-ag gyakoribb). Fail-safe.
    try:
        _fin102 = _link_ok_shop if shop_hits else _link_ok
        if not _fin102 and u"[Tov\u00e1bbi tal\u00e1latok a web\u00e1ruh\u00e1zban](" in parsed.reply:
            from app.services.linkgate import strip_more_link as _sml102
            _new102 = _sml102(parsed.reply)
            if _new102 != parsed.reply and _new102.strip():
                logger.info("m102 link gate: LLM-irta zaro-link levetele client=%s",
                            req.client_id)
                try:
                    parsed.reply = _new102
                except Exception:  # noqa: BLE001 - frozen dataclass eseten
                    from dataclasses import replace as _dc_replace102
                    parsed = _dc_replace102(parsed, reply=_new102)
    except Exception:  # noqa: BLE001 - a kapu hibaja sose torje a valaszt
        pass
    # m96: VALASZ-ORSEG - tenant-szintu kapcsolat-redakcio (tenants.answer_policy).
    # Ugyfel-keres (Kontur Reklam): az e-mail-cim sose menjen ki, a telefonszam
    # csak akkor, ha a LATOGATO kerdezett ra. Merve 54 valodi valaszon: 43% / 44%
    # erintett; a prompt-kor ezt 0/7-re vitte, de a prompt valoszinusegi -- ez a
    # determinisztikus halo (m77/m87 tanulsaga: erre nem eleg a prompt-szabaly).
    # A log_turn ELOTT fut, hogy a naplo es az e-mail-atirat is azt orizze, amit a
    # latogato TENYLEG latott. Policy nelkuli tenantnal no-op.
    try:
        _pol96 = getattr(tenant, "answer_policy", None)
        if _pol96:
            from app.services.answerguard import apply_policy as _ap96
            _new96, _info96 = _ap96(parsed.reply, _pol96, message, req.history)
            if _new96 != parsed.reply:
                logger.info(
                    "m96 answerguard: email=%d phone=%d asked=%s client=%s",
                    _info96.get("email", 0), _info96.get("phone", 0),
                    _info96.get("asked"), req.client_id)
                try:
                    parsed.reply = _new96
                except Exception:  # noqa: BLE001 - frozen dataclass eseten
                    from dataclasses import replace as _dc_replace96
                    parsed = _dc_replace96(parsed, reply=_new96)
    except Exception:  # noqa: BLE001 - az orseg hibaja sose torje a valaszt
        pass
    # m101: (a) relativ termek-link abszolutra (4mfrigo: 8 domain nelkuli link / 30 nap
    # -> torott), a m98 validacio ELOTT; (b) SHADOW-meres: sikeres rendeles-lekeres utan
    # ujra kert rendeles-urlap (d10b: 157 lekereses sessionbol 29-ben a bot letagadta a
    # lekerest es ujra urlapot kert; a javitas prompt-oldali, ez a maradekot szamolja).
    try:
        from app.services.linkvalidate import absolutize_links as _abs101
        _base101 = str(getattr(tenant, "public_url", "") or "").strip()
        if not _base101:
            _d101 = [x.strip() for x in str(getattr(tenant, "domain", "") or "").split(",") if x.strip()]
            _base101 = ("https://" + _d101[0]) if _d101 else ""
        if _base101:
            _new101, _n101 = _abs101(parsed.reply, _base101)
            if _n101:
                logger.info("m101 relativ link -> abszolut: %d client=%s", _n101, req.client_id)
                try:
                    parsed.reply = _new101
                except Exception:  # noqa: BLE001 - frozen dataclass eseten
                    from dataclasses import replace as _dc_replace101
                    parsed = _dc_replace101(parsed, reply=_new101)
        if getattr(parsed, "action", None) == "order_status_form" and any(
                getattr(_h, "role", "") == "assistant"
                and str(getattr(_h, "content", "") or "").startswith("A(z) #")
                for _h in (req.history or [])):
            logger.info("m101 order-form ismetles lekeres utan (shadow) client=%s", req.client_id)
    except Exception:  # noqa: BLE001 - sose torje a valaszt
        pass
    # m98: LINK-UTOVALIDACIO - a valaszban kiment termek-linkek determinisztikus
    # ellenorzese. Mert lelet (d09b_ctxscan.py, 144 valodi valasz / 261 link,
    # kellegyszerszam): 11 link (4,2%) FABRIKALT slugra mutat -> garantalt 404
    # ("DENZEL 1200W 15L ... porszivo" nev + kitalalt URL). A KONTEXTUS NEM jo
    # referencia: a linkek 32%-a letezo termekre mutat ugy, hogy a mostani
    # poolban nincs benne (page_context terméke, korabbi fordulo, SKU-s
    # follow-up) - a naiv "ismeretlen URL -> ki" 94 vagasbol 83 JOT vagna.
    # Ezert a hivatkozasi alap a KATALOGUS (Qdrant `url` payload, m67 ota
    # keyword-indexelt): csak a kontextuson KIVULI URL-eket kerdezzuk le.
    # Ketto fail-safe: (a) a find_by_url hibat is None-nal jelez, ezert vagas
    # elott egy ISMERT ctx-URL-lel ellenorizzuk, hogy a lookup egyaltalan
    # mukodik; (b) barmi kivetel -> a valasz valtozatlan.
    # A log_turn ELOTT fut (m96-mintara), hogy a naplo es az e-mail-atirat is
    # azt orizze, amit a latogato TENYLEG latott.
    try:
        from app.services import linkvalidate as _lv98
        _ctx98: dict = {}
        for _h98 in (hits or []):
            _pl98 = (_h98.get("payload") or {}) if isinstance(_h98, dict) else {}
            if str(_pl98.get("type") or "") == "product" and _pl98.get("url"):
                _ctx98[str(_pl98["url"])] = str(_pl98.get("name") or "")
        if isinstance(current, dict):
            _plc98 = current.get("payload") if isinstance(current.get("payload"), dict) else current
            if _plc98.get("url"):
                _ctx98.setdefault(str(_plc98["url"]), str(_plc98.get("name") or ""))
        _cand98 = _lv98.lookup_candidates(parsed.reply, set(_ctx98))
        _rg98 = _lv98.repair_guesses(parsed.reply, set(_ctx98))   # m98/2 R3
        _miss98: set = set()
        _names98: dict = {}
        _rep98: dict = {}
        if _cand98 or _rg98:
            from app.core.qdrant import get_qdrant as _gq98
            _qc98 = _gq98()

            async def _known98(u: str) -> bool:
                for _v in (u, u.rstrip("/"), u.rstrip("/") + "/"):
                    _pt98 = await _qc98.find_by_url(req.client_id, _v)
                    if _pt98:
                        # m98/2 (B): a kontextuson kivuli linkelt termek NEVE is
                        # kell, hogy R2/R2b arra is fusson (d10a: +3 jo csere)
                        _pl98b = (_pt98.get("payload") or {}) if isinstance(_pt98, dict) else {}
                        if _pl98b.get("name"):
                            _names98[u] = str(_pl98b.get("name"))
                        return True
                return False

            # m98/2 R3: dupla URL / elirt utvonal-elotag -> csak IGAZOLT tipp
            _ck98 = {_lv98.url_key(_x) for _x in _ctx98}
            for _o98, _gl98 in _rg98.items():
                for _g98 in _gl98:
                    if _lv98.url_key(_g98) in _ck98 or await _known98(_g98):
                        _rep98[_o98] = _g98
                        break
            for _u98 in _cand98:
                if _u98 in _rep98:
                    continue
                if not await _known98(_u98):
                    _miss98.add(_u98)
            if _miss98:
                # fail-safe (a): mukodik-e egyaltalan a lookup? (qdrant-hiba
                # eseten a find_by_url is None-t ad -> minden link "hianyzo")
                _probe98 = next(iter(_ctx98), None)
                if _probe98 is None or not await _known98(str(_probe98)):
                    logger.warning(
                        "m98 linkfix: a katalogus-lookup nem igazolhato -> kihagyva "
                        "(client=%s)", req.client_id)
                    _miss98 = set()
        if _miss98 and not _lv98.r1_enabled(getattr(tenant, "platform", "")):
            # m98/1: R1 csak ott vag, ahol a premissza MERVE van (Unas). Mashol
            # shadow-log a kesobbi meresnek (d10a HTTP-check: copygo 22/23,
            # fishingoutlet 28/32 "hianyzo" URL ELO termekoldal volt).
            logger.info(
                "m98 linkfix shadow: would_remove=%d client=%s",
                len(_miss98), req.client_id)
            _miss98 = set()
        for _nu98, _nn98 in _names98.items():
            _ctx98.setdefault(_nu98, _nn98)
        _new98, _i98 = _lv98.apply_fixes(parsed.reply, _ctx98, _miss98, _rep98)
        if _new98 != parsed.reply:
            logger.info(
                "m98 linkfix: removed=%d retargeted=%d num=%d repaired=%d client=%s",
                _i98.get("removed", 0), _i98.get("retargeted", 0), _i98.get("num", 0),
                _i98.get("repaired", 0), req.client_id)
            try:
                parsed.reply = _new98
            except Exception:  # noqa: BLE001 - frozen dataclass eseten
                from dataclasses import replace as _dc_replace98
                parsed = _dc_replace98(parsed, reply=_new98)
    except Exception:  # noqa: BLE001 - az orseg hibaja sose torje a valaszt
        logger.exception("m98 linkfix hiba (a valasz valtozatlan)")
    # m67: a search_fallback esemény-log a lassú szakasz UTÁN (rövid, friss kapcsolat)
    if _sfb_meta:
        await log_event(session, req.client_id, req.session_id, "search_fallback", _sfb_meta)
    # m100: a chatbe GEPELT e-mail-cim -> lead (source="chat") + ertesito a boltnak.
    # d10b: 30 nap alatt 18 valaszban igerte a bot, hogy "rogzitettem / kollegank
    # hamarosan felveszi veled a kapcsolatot", de lead CSAK a widget-urlapbol
    # keletkezett -> a bolt sosem tudott rola (koztuk egy rendeles-lemondas).
    # Feco dontese: checkbox nelkul is lead. Itt csak ELOKESZITUNK (dup-szures, a
    # lead-urlap ne jojjon fel ujra); a rogzites a log_turn UTAN fut, hogy az
    # ertesito atiratban a mostani kor is benne legyen. Fail-safe: hiba -> mai ut.
    _lead100 = None
    try:
        from app.services import chatlead as _cl100
        _c100 = _cl100.extract_contact(message)
        if _c100 and (not _cl100.should_capture(getattr(parsed, "action", None))
                      or _cl100.is_shop_email(_c100["email"], getattr(tenant, "domain", None))):
            _c100 = None
        if _c100 and not _c100["email"]:
            # m101: csak telefonszam -> a bolt SAJAT szamat (tenant-prompt, a bot korabbi
            # valaszai) nem rogzitjuk latogatoi leadkent
            _known101 = [str(getattr(tenant, "system_prompt", "") or "")] + [
                str(getattr(_h, "content", "") or "") for _h in (req.history or [])
                if getattr(_h, "role", "") == "assistant"]
            if _cl100.is_known_phone(_c100["phone"], _known101):
                _c100 = None
        if _c100 and req.session_id:
            _dup100 = None
            try:
                from sqlalchemy import text as _t100
                if _c100["email"]:
                    _q100 = ("SELECT 1 FROM leads WHERE client_id = :c AND session_id = :s "
                             "AND lower(email) = lower(:e) LIMIT 1")
                    _p100 = {"c": req.client_id, "s": req.session_id, "e": _c100["email"]}
                else:
                    _q100 = ("SELECT 1 FROM leads WHERE client_id = :c AND session_id = :s "
                             "AND right(regexp_replace(coalesce(phone, ''), '[^0-9]', '', 'g'), 8)"
                             " = :p LIMIT 1")
                    _p100 = {"c": req.client_id, "s": req.session_id,
                             "p": _cl100.phone_digits(_c100["phone"])[-8:]}
                _dup100 = (await session.execute(_t100(_q100), _p100)).first()
            except Exception:  # noqa: BLE001
                logger.exception("m100 chat lead: dup-ellenorzes hiba -> nincs rogzites")
                _dup100 = True
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001
                    pass
            if _dup100:
                logger.info("m100 chat lead: nincs uj rogzites (dup) client=%s", req.client_id)
                _c100 = None
        if _c100:
            _lead100 = _c100
            if getattr(parsed, "action", None) == "collect_lead":
                try:
                    parsed.action = None
                except Exception:  # noqa: BLE001 - frozen dataclass eseten
                    from dataclasses import replace as _dc_replace100
                    parsed = _dc_replace100(parsed, action=None)
    except Exception:  # noqa: BLE001 - a lead-elokeszites sose torje a valaszt
        logger.exception("m100 chat lead: elokeszites hiba client=%s", req.client_id)
        _lead100 = None
    # megválaszolatlan-naplózás (Eval Unanswered): low_score / collect_lead / order_form
    await log_unanswered(session, req.client_id, req.session_id, message, top_score, parsed.action)
    # beszélgetés-napló (m22): a stat.html visszanéző + e-mail átiratok forrása
    await log_turn(session, req.client_id, req.session_id, message, parsed.reply, parsed.action)
    # m100: a chatbe irt elerhetoseg rogzitese (elokeszites fent, a log_unanswered elott)
    if _lead100:
        try:
            _req100 = req.model_copy(update={
                "email": _lead100["email"] or None, "phone": _lead100.get("phone") or None,
                "source": "chat", "type": "lead"})
            await store_lead(session, _req100)
            logger.info("m100 chat lead: rogzitve (email=%s telefon=%s) client=%s",
                        "igen" if _lead100.get("email") else "nem",
                        "igen" if _lead100.get("phone") else "nem", req.client_id)
        except Exception:  # noqa: BLE001 - a rogzites hibaja sose torje a valaszt
            logger.exception("m100 chat lead: rogzites hiba client=%s", req.client_id)
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
    # termékajánlás-számláló (m22): a válaszban linkelt webshop-termékek
    rec_n = count_product_links(parsed.reply, tenant)
    if rec_n:
        await log_event(session, req.client_id, req.session_id, "product_rec", {"count": rec_n})
    # m29: az order-urlap mezoi platformfuggoek (webdoc -> irsz, egyebkent e-mail)
    _of = (
        OrderFormRef(fields=order_form_fields(tenant.platform))
        if parsed.action == "order_status_form"
        else None
    )
    return ChatResponse(
        reply=parsed.reply, action=parsed.action, configurator=None, order_form=_of
    )


@router.post("/chat", response_model=None)
@router.post("/webhook/chat", response_model=None)
async def chat(req: ChatRequest, session: AsyncSession = Depends(get_session)):
    t = (req.type or "").strip().lower()

    if t == "feedback":
        await store_feedback(session, req)
        return EventAck(stored="feedback")

    if t == "lead":
        await store_lead(session, req)
        return EventAck(stored="lead")

    if t == "event":
        # widget-esemény (m22): csak whitelistelt fajta; ismeretlen -> csendes ack
        kind = (req.event or "").strip().lower()
        if kind in WIDGET_KINDS:
            meta = {"url": (req.url or "")[:500], "title": (req.title or "")[:200]}
            if kind == "purchase":
                # m48: chat-asszisztalt vasarlas - order_id / ertek / devizanem a widgettol
                meta["order_id"] = str(req.order_id or "")[:64]
                try:
                    meta["value"] = float(req.value) if req.value is not None else None
                except (TypeError, ValueError):
                    meta["value"] = None
                meta["currency"] = str(req.currency or "")[:8]
            await log_event(session, req.client_id, req.session_id, kind, meta)
        return EventAck(stored="event")

    # nincs type -> üzenet
    return await _handle_message(req, session)


@router.get("/chat/poll")
async def chat_poll(
    client_id: str = Query(...),
    session_id: str = Query(...),
    after: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Widget-polling (m28): operátor-mód üzenetei.

    Vissza: {state, messages:[{id,sender,text,ts}]}. Csak az OPERÁTOR-üzeneteket adja
    (a látogató a sajátjait már látja); `after` = a widget által utoljára látott id.
    """
    state = await get_session_state(session, client_id, session_id)
    messages = await poll_messages(session, session_id, after, senders=("operator",))
    return {"state": state, "messages": messages}
@router.get("/chat/state")
async def chat_state(
    client_id: str = Query(...),
    session_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """m47/C: konnyu widget state-poll -> {"state": "bot" | "operator"}.

    Redis-first (nagy forgalmu polling-cel, a DB-t kimeljuk), DB csak
    cache-miss eseten (session_live_state). A widget nyitott panel + bot-mod
    mellett ritkan (~25 s) pollolja; 'operator' -> azonnali operator-mod."""
    return {"state": await session_live_state(session, get_redis(), session_id)}

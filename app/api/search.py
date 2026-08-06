"""SmartSearch widget-végpontok (S2).

- ``GET  /search/settings?client_id=...`` — szinonimák, egyirányú szinonimák,
  népszerű keresések/termékek, merchandising-szabályok (ezt hívja a widget
  ``loadSyn()``-je, hibára némán).
- ``POST /search/event`` — ``ss_search`` | ``ss_click`` | ``ss_purchase`` az
  ``events`` táblába (ugyanaz az infra, amit a chat-widget használ).
- ``POST /search/answer`` — AI-válasz a keresésre (S6/2): a widget felküldi a
  kérdést és a saját top jelöltjeit, az LLM csak VÁLOGAT közülük és indokol.
  Alapból kikapcsolva; a ``?cxai=1`` demó-kapcsoló (``force``) nyitja.

A tenant-konfiguráció forrása a ``data/smartsearch.json`` — ugyanaz a fájl, amit
az ``app/search`` indexelő CLI olvas, és ami a compose-ban be van mountolva
(``/docker/chatbot-prod/data:/app/data``), tehát szerkesztéséhez nem kell újraépítés::

    {"tenants": {"teslashop": {
        "enabled": true,
        "synonyms": [["felni", "kerek"], ["szonyeg", "matrica"]],
        "oneway": [{"f": "noti", "t": ["notebook"]}],
        "popular_terms": ["..."], "popular_skus": ["..."],
        "merch": [{"kw": ["..."], "skus": ["..."], "w": "front",
                   "from": "2026-08-01", "to": "2026-08-31"}]
    }}}

Üres ``popular_terms`` / ``popular_skus`` esetén a lista automatikusan az utolsó
30 nap ``ss_search`` / ``ss_click`` eseményeiből áll elő.

Fail-safe: bármilyen hiba esetén üres konfig, ill. csendes 204 — a widget sosem
törik el egy végpont-hibától. A CORS-t a ``TenantCORSMiddleware`` adja.

FONTOS: a widget ``sendBeacon``-nel küld, ``text/plain`` content-type-pal (az
``application/json`` CORS-preflightot váltana ki, amit a sendBeacon nem tud
kezelni) — ezért a body-t nyersen parse-oljuk, nem a content-type alapján.
"""

import json
import logging
import os
import time
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.services.events import log_event

logger = logging.getLogger("cx.search")
router = APIRouter()

DEFAULT_CONFIG_PATH = "data/smartsearch.json"
SEARCH_KINDS = {"ss_search", "ss_click", "ss_purchase"}
POPULAR_DAYS = 30
MAX_TERMS = 8
MAX_PRODUCTS = 10
MERCH_WEIGHTS = ("front", "up", "down", "back")
CACHE_SECONDS = 300


# --------------------------------------------------------------------------- #
# konfiguráció
# --------------------------------------------------------------------------- #
def config_path() -> str:
    """Hívásonként olvassuk — így teszteléskor átállítható."""
    return os.environ.get("SS_CONFIG", DEFAULT_CONFIG_PATH)


def load_config(client_id: str) -> dict[str, Any]:
    """A tenant smartsearch-blokkja (hibára / ismeretlen tenantra üres dict)."""
    if not client_id:
        return {}
    try:
        with open(config_path(), encoding="utf-8") as fh:
            cfg = json.load(fh)
        tenants = cfg.get("tenants") if isinstance(cfg, dict) else None
        row = (tenants or {}).get(client_id)
        return row if isinstance(row, dict) else {}
    except Exception:  # noqa: BLE001 — a widget sosem törhet el a configon
        logger.warning("search: config olvasas sikertelen (%s)", config_path())
        return {}


_SQL_TENANT_CFG = text("SELECT search_config FROM tenants WHERE client_id = :cid")


async def db_config(session: Any, client_id: str) -> dict[str, Any]:
    """A tenant ``tenants.search_config`` jsonb-je (hibara / hianyzo sorra ures dict)."""
    try:
        row = (await session.execute(_SQL_TENANT_CFG, {"cid": client_id})).scalar()
    except Exception:  # noqa: BLE001 - a widget sosem torhet el a configon
        logger.warning("search: search_config olvasas sikertelen (%s)", client_id)
        return {}
    if isinstance(row, str):
        try:
            row = json.loads(row)
        except Exception:  # noqa: BLE001
            return {}
    return row if isinstance(row, dict) else {}


async def get_config(session: Any, client_id: str) -> dict[str, Any]:
    """S3 igazsag-forras: tenants.search_config; ha ures/hibas -> data/smartsearch.json."""
    if not client_id:
        return {}
    cfg = await db_config(session, client_id)
    return cfg if cfg else load_config(client_id)


# --------------------------------------------------------------------------- #
# normalizálók (a widget által várt alak)
# --------------------------------------------------------------------------- #
def _str_list(value: Any, cap: int = 64, maxlen: int = 80) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            s = " ".join(str(item).split()).strip()
            if s:
                out.append(s[:maxlen])
            if len(out) >= cap:
                break
    return out


def norm_groups(value: Any) -> list[list[str]]:
    """Kölcsönös szinonima-csoportok: legalább 2 tag, max 8."""
    out: list[list[str]] = []
    if isinstance(value, list):
        for group in value[:100]:
            tags = _str_list(group, cap=8, maxlen=40)
            if len(tags) >= 2:
                out.append(tags)
    return out


def norm_oneway(value: Any) -> list[dict[str, Any]]:
    """Egyirányú szinonimák: ``{"f": "noti", "t": ["notebook"]}``."""
    out: list[dict[str, Any]] = []
    if isinstance(value, list):
        for row in value[:100]:
            if not isinstance(row, dict):
                continue
            frm = " ".join(str(row.get("f") or "").split()).strip()
            tos = _str_list(row.get("t"), cap=8, maxlen=40)
            if frm and tos:
                out.append({"f": frm[:40], "t": tos})
    return out


def active_merch(rules: Any, today: date | None = None) -> list[dict[str, Any]]:
    """Csak az időablakban lévő merch-szabályok (from/to inkluzív, hiányzó = nyitott)."""
    out: list[dict[str, Any]] = []
    if not isinstance(rules, list):
        return out
    day = (today or date.today()).isoformat()
    for rule in rules[:100]:
        if not isinstance(rule, dict):
            continue
        weight = str(rule.get("w") or "").strip()
        skus = _str_list(rule.get("skus"), cap=50, maxlen=64)
        if weight not in MERCH_WEIGHTS or not skus:
            continue
        frm = str(rule.get("from") or "").strip()
        to = str(rule.get("to") or "").strip()
        if (frm and day < frm) or (to and day > to):
            continue
        out.append({"kw": _str_list(rule.get("kw"), cap=20, maxlen=60), "skus": skus, "w": weight})
    return out


def pick_terms(rows: Any, cap: int = MAX_TERMS) -> list[str]:
    """Top keresések: min. 3 karakter + prefix-dedup (a gépelés-töredékek ellen)."""
    out: list[str] = []
    for raw in rows or []:
        term = " ".join(str(raw or "").split()).strip()
        if len(term) < 3:
            continue
        low = term.lower()
        merged = False
        for i, kept in enumerate(out):
            kl = kept.lower()
            if low.startswith(kl) or kl.startswith(low):
                if len(low) > len(kl):
                    out[i] = term
                merged = True
                break
        if merged:
            continue
        out.append(term)
        if len(out) >= cap:
            break
    return out


def _int(value: Any, lo: int = 0, hi: int = 10**9) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(lo, min(hi, n))


# --------------------------------------------------------------------------- #
# automatikus népszerű-listák az eseményekből
# --------------------------------------------------------------------------- #
_SQL_TERMS = text(
    "SELECT meta->>'q' AS q, count(*) AS n, "
    "sum(CASE WHEN coalesce(meta->>'total', '0') ~ '^[1-9][0-9]*$' THEN 1 ELSE 0 END) AS hits "
    "FROM events "
    "WHERE client_id = :cid AND kind = 'ss_search' "
    "AND created_at > now() - make_interval(days => :days) "
    "AND coalesce(meta->>'q', '') <> '' "
    "GROUP BY 1 ORDER BY 2 DESC LIMIT 60"
)

_SQL_IDS = text(
    "SELECT meta->>'pid' AS pid, count(*) AS n "
    "FROM events "
    "WHERE client_id = :cid AND kind = 'ss_click' "
    "AND created_at > now() - make_interval(days => :days) "
    "AND coalesce(meta->>'pid', '') <> '' "
    "GROUP BY 1 ORDER BY 2 DESC LIMIT :lim"
)


async def auto_terms(session: AsyncSession, client_id: str) -> list[str]:
    """Találatot hozó top keresések az elmúlt 30 napból (hibára üres lista)."""
    try:
        rows = (await session.execute(_SQL_TERMS, {"cid": client_id, "days": POPULAR_DAYS})).all()
    except Exception:  # noqa: BLE001
        logger.warning("search: auto_terms hiba (%s)", client_id)
        return []
    return pick_terms([r[0] for r in rows if _int(r[2]) > 0])


async def auto_ids(session: AsyncSession, client_id: str) -> list[str]:
    """Legtöbbet kattintott termék-azonosítók az elmúlt 30 napból."""
    try:
        rows = (await session.execute(
            _SQL_IDS, {"cid": client_id, "days": POPULAR_DAYS, "lim": MAX_PRODUCTS}
        )).all()
    except Exception:  # noqa: BLE001
        logger.warning("search: auto_ids hiba (%s)", client_id)
        return []
    return [str(r[0]) for r in rows if str(r[0] or "").strip()]


# --------------------------------------------------------------------------- #
# végpontok
# --------------------------------------------------------------------------- #
@router.get("/search/settings")
async def search_settings(
    client_id: str = Query("", max_length=64),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """A widget beállításai. Ismeretlen/kikapcsolt tenantnál üres, de valid válasz."""
    cid = (client_id or "").strip()
    cfg = await get_config(session, cid)
    body: dict[str, Any] = {
        "tenant": cid,
        "groups": norm_groups(cfg.get("synonyms")),
        "oneway": norm_oneway(cfg.get("oneway")),
        "popular_terms": _str_list(cfg.get("popular_terms"), cap=MAX_TERMS, maxlen=60),
        "popular_skus": _str_list(cfg.get("popular_skus"), cap=MAX_PRODUCTS, maxlen=64),
        "popular_ids": [],
        "merch": active_merch(cfg.get("merch")),
    }
    if cfg.get("enabled"):
        if not body["popular_terms"]:
            body["popular_terms"] = await auto_terms(session, cid)
        if not body["popular_skus"]:
            body["popular_ids"] = await auto_ids(session, cid)
    return JSONResponse(body, headers={"Cache-Control": f"public, max-age={CACHE_SECONDS}"})


@router.post("/search/event")
async def search_event(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Kereső-esemény naplózása. Mindig 204 — a beacon-hívást sosem büntetjük hibával."""
    try:
        raw = await request.body()
        data = json.loads((raw or b"").decode("utf-8", "replace") or "{}")
    except Exception:  # noqa: BLE001
        return Response(status_code=204)
    if not isinstance(data, dict):
        return Response(status_code=204)

    kind = str(data.get("event") or "").strip().lower()
    cid = str(data.get("client_id") or "").strip()[:64]
    if kind not in SEARCH_KINDS or not cid:
        return Response(status_code=204)
    if not (await get_config(session, cid)).get("enabled"):
        # ismeretlen vagy kikapcsolt tenant -> csendes eldobás (nem szemeteljük a táblát)
        return Response(status_code=204)

    raw_meta = data.get("meta")
    meta_in = raw_meta if isinstance(raw_meta, dict) else {}
    meta = {
        "q": str(meta_in.get("q") or "")[:120],
        "pid": str(meta_in.get("pid") or "")[:64],
        "total": _int(meta_in.get("total")),
        "extra": _int(meta_in.get("extra")),
    }
    sid = str(data.get("session_id") or "")[:64] or None
    await log_event(session, cid, sid, kind, meta)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# S6/2 — AI-válasz a keresőben: POST /search/answer
#
# "Válaszd ki és indokold", nem RAG: a jelölteket a widget küldi fel a kliens-
# oldali indexből, az LLM csak VÁLOGAT közülük. Az ár és a készlet ezért mindig
# az indexből jön — a generált szövegben szám/ár nem lehet (``strip_prices``).
#
# Költség-kapuk (Redis NINCS az infrán, ezért minden in-process):
#   1. tenant-kapu: csak engedélyezett tenant, és csak ``ai_answer`` VAGY ``force``
#      (a ``?cxai=1`` demó-kapcsoló) — ismeretlen client_id sosem hív LLM-et;
#   2. trigger: ``needs_answer`` (kérdés-jellegű VAGY nulla találat);
#   3. cache: (tenant, normalizált kérdés) → válasz, 24 h;
#   4. napi plafon tenantonként (``search_config.ai_daily_cap``, alap 200).
# --------------------------------------------------------------------------- #
AI_CACHE_TTL = 24 * 3600
AI_CACHE_MAX = 500
AI_DAILY_CAP = 200
AI_MAX_INPUT = 60          # ennyi NYERS jelöltnél tovább nem olvasunk

_ai_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_ai_calls: dict[tuple[str, str], int] = {}

_SQL_CHAT_MODEL = text("SELECT chat_model FROM tenants WHERE client_id = :cid")


def ai_cache_get(key: tuple[str, str]) -> dict[str, Any] | None:
    """Cache-találat, ha még nem járt le (különben None)."""
    row = _ai_cache.get(key)
    if not row:
        return None
    born, value = row
    if time.time() - born > AI_CACHE_TTL:
        _ai_cache.pop(key, None)
        return None
    return value


def ai_cache_put(key: tuple[str, str], value: dict[str, Any]) -> None:
    """Csak SIKERES választ cache-elünk; teltségnél a legrégebbi felét dobjuk."""
    if len(_ai_cache) >= AI_CACHE_MAX:
        for old in sorted(_ai_cache, key=lambda k: _ai_cache[k][0])[: AI_CACHE_MAX // 2]:
            _ai_cache.pop(old, None)
    _ai_cache[key] = (time.time(), value)


def ai_cap(cfg: dict[str, Any]) -> int:
    """Napi plafon a configból: hiányzó/üres = alap, 0 = teljesen kikapcsolva."""
    raw = cfg.get("ai_daily_cap")
    if raw is None or str(raw).strip() == "":
        return AI_DAILY_CAP
    return _int(raw)


def ai_take(client_id: str, cap: int) -> bool:
    """Foglal egy hívást a napi keretből (naponta nullázódik). Konténer-újraindításnál
    a számláló elveszik — a plafon így felső korlát, nem könyvelés."""
    if cap <= 0:
        return False
    today = date.today().isoformat()
    used = _ai_calls.get((client_id, today), 0)
    if used >= cap:
        return False
    for stale in [k for k in _ai_calls if k[1] != today]:
        _ai_calls.pop(stale, None)
    _ai_calls[(client_id, today)] = used + 1
    return True


async def chat_model(session: Any, client_id: str) -> str | None:
    """Tenant-szintű modell-felülbírálat (hibára None = globális alapmodell)."""
    try:
        row = (await session.execute(_SQL_CHAT_MODEL, {"cid": client_id})).scalar()
    except Exception:  # noqa: BLE001
        return None
    value = str(row or "").strip()
    return value or None


@router.post("/search/answer")
async def search_answer(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """AI-válasz a kereséshez.

    Siker: ``{"answer": "...", "pids": [...], "cached": 0|1}``; minden más esetben
    ``{}`` (nincs válasz-sáv). MINDIG 200 — a widget sosem törhet el emiatt.
    """
    try:
        from app.services import searchanswer as sa   # lazy: fake app.services a tesztekben
    except Exception:  # noqa: BLE001
        logger.warning("search/answer: searchanswer modul nem toltheto")
        return JSONResponse({})

    try:
        raw = await request.body()
        data = json.loads((raw or b"").decode("utf-8", "replace") or "{}")
    except Exception:  # noqa: BLE001
        return JSONResponse({})
    if not isinstance(data, dict):
        return JSONResponse({})

    cid = str(data.get("client_id") or "").strip()[:64]
    q = " ".join(str(data.get("q") or "").split())[:200]
    force = bool(data.get("force"))
    if not cid or not q:
        return JSONResponse({})

    cfg = await get_config(session, cid)
    if not cfg.get("enabled"):
        # ismeretlen vagy kikapcsolt tenant: a végpont nyilvános, LLM-et nem hívunk
        return JSONResponse({})
    if not (cfg.get("ai_answer") or force):
        return JSONResponse({})
    if not sa.needs_answer(q, _int(data.get("total")), force):
        return JSONResponse({})

    key = (cid, sa.norm_q(q))
    hit = ai_cache_get(key)
    if hit is not None:
        return JSONResponse(dict(hit, cached=1))

    items = data.get("candidates")
    cands = sa.clean_candidates(items[:AI_MAX_INPUT] if isinstance(items, list) else None)
    if not cands:
        return JSONResponse({})

    if not ai_take(cid, ai_cap(cfg)):
        logger.warning("search/answer: napi plafon elerve (%s)", cid)
        return JSONResponse({})

    try:
        from app.core.llm import generate_reply   # lazy: nehéz import (Anthropic SDK)

        reply = await generate_reply(
            sa.SYSTEM_PROMPT,
            [],
            sa.build_user_prompt(q, cands),
            model=await chat_model(session, cid),
        )
    except Exception:  # noqa: BLE001 — LLM 5xx/timeout: nincs sáv, de nincs 500 sem
        logger.warning("search/answer: LLM hiba (%s)", cid, exc_info=True)
        return JSONResponse({})

    out = sa.finalize(reply, cands)
    if not out:
        logger.info("search/answer: nincs sav (%s) q=%r", cid, key[1])
        return JSONResponse({})
    ai_cache_put(key, out)
    return JSONResponse(dict(out, cached=0))

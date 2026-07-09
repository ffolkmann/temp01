"""Pre-LLM intent kaszkád — a prod `Detect Order Intent` / `Detect Configurator` /
`Detect Handoff` Code node-ok 1:1 portja (lásd seed/prod_retrieval.txt).

A normál üzenetnél, az LLM ELŐTT fut, a prod sorrendjében:
  order-status -> configurator -> handoff -> (egyik sem) -> RAG+LLM.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.models.db_models import Tenant

# konfigurátor webhook bázis (a prod Detect Configurator-ból)
_CONFIG_BASE = "https://n8n.codexpress.cloud/webhook/"

_LIVE_PLATFORMS = {"sellvio", "shoprenter", "unas", "woocommerce", "webdoc"}


def _ascii_fold(s: str) -> str:
    """lowercase + ékezet-strip (NFD) — a prod normalize('NFD').replace(/[̀-ͯ]/g,'')."""
    s = str(s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


# --- Order intent -----------------------------------------------------------
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_INTENT_WORDS = re.compile(
    r"(rendel|csomag|szállít|hol tart|hol van|státus|status|track|"
    r"nyomkövet|mikor érkez|feldolgoz)"
)


@dataclass
class OrderIntent:
    is_order_status: bool
    order_email: str = ""
    order_id: str = ""
    order_zip: str = ""          # m29 (webdoc): az e-mail helyett ez a masodlagos titok
    live_ok: bool = False
    platform: str = ""


# --- Webdoc: rendelesszam + iranyitoszam (az API nem ad e-mailt) -------------
_WD_NUMBER_RE = re.compile(r"(\d{4}\s*/\s*\d{3,9})")
_WD_HASH_RE = re.compile(r"#\s*(\d{4,9})\b")
_WD_ZIP_LABEL_RE = re.compile(
    r"(?:ir[a\u00e1]ny[i\u00ed]t[o\u00f3]sz[a\u00e1]m|irsz|isz)\s*[:=]?\s*(\d{4})\b",
    re.IGNORECASE,
)
_WD_ZIP_RE = re.compile(r"\b(\d{4})\b")


def _detect_webdoc_order(msg: str, live_ok: bool, plat: str) -> OrderIntent:
    """Webdoc: rendelesszam (`2026/0047322` vagy `#47322`) + 4 jegyu iranyitoszam.

    A rendelesszamot ELOBB kivagjuk a szovegbol, es csak a maradekban keresunk
    iranyitoszamot -- kulonben a `2026` ev-szegmens vagy a sorszam 4 jegye
    iranyitoszamnak latszana. Cimke nelkul csak akkor fogadjuk el a 4 jegyu
    szamot, ha egyertelmu (pontosan egy van a maradekban).
    """
    number = ""
    rest = msg
    m = _WD_NUMBER_RE.search(msg) or _WD_HASH_RE.search(msg)
    if m:
        number = re.sub(r"\s+", "", m.group(1))
        rest = msg[: m.start()] + " " + msg[m.end():]

    zipc = ""
    mz = _WD_ZIP_LABEL_RE.search(rest)
    if mz:
        zipc = mz.group(1)
    else:
        nums = _WD_ZIP_RE.findall(rest)
        if len(nums) == 1:
            zipc = nums[0]

    return OrderIntent(
        is_order_status=bool(live_ok and number and zipc),
        order_email="",
        order_id=number,
        order_zip=zipc,
        live_ok=live_ok,
        platform=plat,
    )


def detect_order_intent(message: str, tenant: Tenant, live_api: bool) -> OrderIntent:
    msg = str(message or "")
    low = msg.lower()
    plat = str(tenant.platform or "")
    # Unasnal nincs tenant-szintu api_base (fix UNAS_BASE + kulcs a secretben)
    if plat == "unas":
        _has_cred = bool(str(tenant.api_client_secret or "").strip())
    elif plat == "webdoc":
        # a webdoc api_base a publikus termek-feed URL-je (auth nelkul); a rendeles-API
        # Basic auth kulcsa a client_id/secret parban all.
        _has_cred = bool(str(tenant.api_client_id or "").strip()) and bool(
            str(tenant.api_client_secret or "").strip()
        )
    else:
        _has_cred = bool(str(tenant.api_base or "").strip())
    live_ok = plat in _LIVE_PLATFORMS and _has_cred and live_api is True

    if plat == "webdoc":
        return _detect_webdoc_order(msg, live_ok, plat)

    m = _EMAIL_RE.search(msg)
    email = m.group(0).strip() if m else ""

    order_id = ""
    m = re.search(r"#\s*(\d{3,6}-\d{4,9}|\d{1,7})", msg)
    if m:
        order_id = m.group(1)
    if not order_id:
        m = re.search(r"\b(\d{3,6}-\d{4,9})\b", msg)
        if m:
            order_id = m.group(1)
    if not order_id:
        m = re.search(r"(?:rendel\w*|order|azonos\w*)\D{0,12}(\d{1,7})", low)
        if m:
            order_id = m.group(1)
    if not order_id:
        nums = re.findall(r"\b\d{1,7}\b", msg)
        if len(nums) == 1:
            order_id = nums[0]

    has_intent = bool(_INTENT_WORDS.search(low))
    is_order = (
        live_ok
        and bool(email)
        and bool(order_id)
        and (has_intent or (bool(email) and bool(order_id)))
    )
    return OrderIntent(
        is_order_status=is_order,
        order_email=email,
        order_id=order_id,
        live_ok=live_ok,
        platform=plat,
    )


# --- Configurator -----------------------------------------------------------
_CONFIG_KW = re.compile(r"(szerel|telepit|beszerel|kalkul|konfigur|felmer)")


@dataclass
class ConfiguratorIntent:
    is_configurator: bool
    cfg: dict[str, str] | None = None


def detect_configurator(message: str, tenant: Tenant) -> ConfiguratorIntent:
    shop = str(tenant.configurator_shop or "").strip().lower()
    if not shop:
        return ConfiguratorIntent(is_configurator=False, cfg=None)
    ascii_msg = _ascii_fold(message)
    from urllib.parse import quote

    cfg = {
        "config_url": _CONFIG_BASE + "klima-config?shop=" + quote(shop, safe=""),
        "calculate_url": _CONFIG_BASE + "klima-calculate?shop=" + quote(shop, safe=""),
        "email_url": _CONFIG_BASE + "klima-email",
    }
    is_config = bool(_CONFIG_KW.search(ascii_msg))
    return ConfiguratorIntent(is_configurator=is_config, cfg=cfg)


# --- Handoff ----------------------------------------------------------------
_HANDOFF_STRONG = re.compile(
    r"(elo segitseg|valodi ember(rel)?|igazi ember(rel)?|emberi ugyintez|"
    r"kapcsolj(on)?\s+(at|ossze)|hivj(atok|on)?\s+(fel|vissza)|visszahivast|"
    r"telefonon\s+(szeretnek|akarok|tudnek)\s+beszelni|nem\s+(a\s+)?robottal|"
    r"nem\s+(a\s+)?bottal|ugyfelszolgalattal\s+(szeretnek|akarok)\s+beszelni)"
)
_HANDOFF_PERSON = re.compile(r"(emberrel|munkatars|kollega|ugyintezo|operator)")
_HANDOFF_VERB = re.compile(
    r"(beszel|kapcsol|hiv|keres|kerem|kerek|kerne|szeretnek|akarok|valthatnek)"
)
_HANDOFF_FALLBACK_EMAIL = "folkmann.ferenc@gmail.com"


@dataclass
class HandoffIntent:
    is_handoff: bool
    to: str = ""
    transcript: str = ""
    page: str = ""


def detect_handoff(
    message: str,
    tenant: Tenant,
    history: list | None = None,
    page_url: str = "",
) -> HandoffIntent:
    msg = str(message or "")
    a = _ascii_fold(msg)
    is_handoff = bool(_HANDOFF_STRONG.search(a)) or bool(
        _HANDOFF_PERSON.search(a) and _HANDOFF_VERB.search(a)
    )
    hist = (history or [])[-10:]
    lines = [
        ("BOT: " if getattr(h, "role", "") == "assistant" else "LATOGATO: ")
        + str(getattr(h, "content", "") or "")
        for h in hist
    ]
    lines.append("LATOGATO: " + msg)
    to = str(tenant.lead_email or "").strip() or _HANDOFF_FALLBACK_EMAIL
    return HandoffIntent(
        is_handoff=is_handoff,
        to=to,
        transcript="\n".join(lines),
        page=str(page_url or ""),
    )

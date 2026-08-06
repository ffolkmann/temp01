"""CX Konfigurator lead-fogado — tiszta fuggvenyek (kf/9, stdlib-only).

A widget eddig KOZVETLENUL egy tenantonkent klonozott n8n-webhookra postolt
(``lead.post_url``), ezert minden uj partner bekapcsolasa fejlesztoi munka volt
(webhook + e-mail node klonozasa, drotozott cimzettel). Ez a modul a KOZOS ut
tiszta magja: a ``POST /konf/lead`` vegpont ezekkel a fuggvenyekkel dolgozik.

Cimzett-feloldas (az elso nem ures nyer):
    1. ruleset ``lead.to_email``      — tenantonkent, az admin config_json-jeben
    2. ``tenants.lead_email``         — a chatbot-lead cimzettje ugyanennel a boltnal
    3. ruleset ``lead.fallback_email`` — a widget "irj nekunk" cime

A ``post_url`` NEM szunik meg: ha a rulesetben be van allitva, a widget tovabbra
is oda kuld (visszafele kompatibilitas). Aki mindkettot akarja — DB + sajat n8n
folyamat —, annak a ``lead.forward_url`` valo: a vegpont tovabbitja a leadet, de
a tarolas es az ertesito e-mail a mienk marad.

Stdlib-only es fajl-betoltheto (a suite konvencioja): itt nincs se sqlalchemy,
se fastapi — a DB-iras es a kuldes a vegponte (app/api/konf.py).
"""
import json
import re
from urllib.parse import parse_qsl

MAX_NAME = 120
MAX_EMAIL = 160
MAX_PHONE = 40
MAX_NOTE = 2000
MAX_SUMMARY = 4000
MAX_PAGE = 300
MAX_URL = 300

# rate limit: (tenant, IP) parosonkent ennyi lead ennyi masodperc alatt
RATE_LIMIT = 5
RATE_WINDOW = 600

SOURCE = "configurator"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
_DIGIT_RE = re.compile(r"\d")


def _s(v, maxlen=150):
    """Egysoros, osszevont whitespace-u, hosszkorlatos szoveg."""
    return " ".join(str(v if v is not None else "").split()).strip()[:maxlen]


def _text(v, maxlen):
    """Tobbsoros szoveg: a sorvegek megmaradnak, a hossz korlatos."""
    s = str(v if v is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()[:maxlen]


def parse_body(raw, content_type=""):
    """A body dict-te alakitva, a Content-Type-tol FUGGETLENUL.

    A widget urlencoded-et kuld (igy a keres CORS-ertelemben egyszeru marad, nincs
    preflight), a REST-hivo JSON-t. Hibara ures dict — a vegpont ezt 400-zal zarja.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", "replace")
    raw = (raw or "").strip()
    if not raw:
        return {}
    if raw[0] in "{[":
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}
    try:
        return dict(parse_qsl(raw, keep_blank_values=True))
    except Exception:  # noqa: BLE001
        return {}


def normalize(data):
    """A nyers body -> tisztitott, hosszkorlatos lead-mezok."""
    d = data if isinstance(data, dict) else {}
    return {
        "client_id": _s(d.get("client_id") or d.get("tenant"), 64).lower(),
        "session_id": _s(d.get("session_id"), 64),
        "name": _s(d.get("name"), MAX_NAME),
        "email": _s(d.get("email"), MAX_EMAIL),
        "phone": _s(d.get("phone"), MAX_PHONE),
        "note": _text(d.get("note") or d.get("message"), MAX_NOTE),
        "summary": _text(d.get("summary"), MAX_SUMMARY),
        "page": _s(d.get("page") or d.get("url"), MAX_PAGE),
        "hp": _s(d.get("website") or d.get("hp"), 80),
    }


def has_contact(p):
    """Legalabb EGY hasznalhato elerhetoseg kell: ervenyes e-mail VAGY telefon."""
    p = p if isinstance(p, dict) else {}
    if _EMAIL_RE.match(p.get("email") or ""):
        return True
    return len(_DIGIT_RE.findall(p.get("phone") or "")) >= 6


def _mail(v):
    s = _s(v, 300)
    return s if "@" in s else ""


def recipient(lead_cfg, tenant_lead_email=""):
    """Cimzett: ruleset to_email -> tenants.lead_email -> ruleset fallback_email."""
    cfg = lead_cfg if isinstance(lead_cfg, dict) else {}
    for cand in (cfg.get("to_email"), tenant_lead_email, cfg.get("fallback_email")):
        m = _mail(cand)
        if m:
            return m
    return ""


def forward_url(lead_cfg):
    """Opcionalis tovabbitasi cim (sajat n8n/CRM) — csak http(s)."""
    cfg = lead_cfg if isinstance(lead_cfg, dict) else {}
    u = _s(cfg.get("forward_url"), MAX_URL)
    return u if u.startswith("http://") or u.startswith("https://") else ""


def compose(client_id, p, lead_cfg=None):
    """(targy, szoveg) az ertesito e-mailhez. A widget summary-ja a torzs vege."""
    cfg = lead_cfg if isinstance(lead_cfg, dict) else {}
    p = p if isinstance(p, dict) else {}
    subject = _s(cfg.get("subject"), 160) or (
        "Uj erdeklodo - %s konfigurator" % (client_id or "?")
    )
    lines = [
        "Uj erdeklodo erkezett a konfiguratorbol.",
        "",
        "Nev: %s" % (p.get("name") or "-"),
        "E-mail: %s" % (p.get("email") or "-"),
        "Telefon: %s" % (p.get("phone") or "-"),
        "Megjegyzes: %s" % (p.get("note") or "-"),
    ]
    if p.get("page"):
        lines.append("Oldal: %s" % p["page"])
    if p.get("summary"):
        lines += ["", "--- KONFIGURATOR ---", p["summary"]]
    return subject, "\n".join(lines)


def stored_message(p):
    """A ``leads.message`` tartalma: a sajat megjegyzes + a valasz-osszegzes.

    Azert egyben, mert az admin lead-listaja a message mezot mutatja — igy a
    kollega e-mail nelkul is latja, mire kapott ajanlatkerest.
    """
    p = p if isinstance(p, dict) else {}
    parts = [x for x in (p.get("note"), p.get("summary")) if x]
    return "\n\n".join(parts)[: MAX_NOTE + MAX_SUMMARY]


def history_blob(p):
    """A ``leads.history`` jsonb strukturalt valtozata (kesobbi kiertekeleshez)."""
    p = p if isinstance(p, dict) else {}
    return {
        "kind": "konfigurator",
        "page": p.get("page") or "",
        "summary": p.get("summary") or "",
    }


def forward_payload(client_id, p):
    """A tovabbitott JSON — a widget mezoi + a tenant azonositoja."""
    p = p if isinstance(p, dict) else {}
    return {
        "tenant": client_id,
        "client_id": client_id,
        "session_id": p.get("session_id") or "",
        "name": p.get("name") or "",
        "email": p.get("email") or "",
        "phone": p.get("phone") or "",
        "note": p.get("note") or "",
        "summary": p.get("summary") or "",
        "page": p.get("page") or "",
    }


def client_ip(headers, fallback=""):
    """A valodi kliens IP-je: Caddy mogott az X-Forwarded-For ELSO eleme."""
    h = headers if isinstance(headers, dict) else {}
    raw = ""
    for k in ("x-forwarded-for", "X-Forwarded-For", "x-real-ip", "X-Real-IP"):
        if h.get(k):
            raw = str(h[k])
            break
    ip = raw.split(",")[0].strip() if raw else ""
    return (ip or _s(fallback, 60) or "anon")[:60]


def rl_key(client_id, ip):
    """Rate-limit kulcs (a rate_limit modul Redis-nevterenek mintajara)."""
    return "cx:rl:konflead:%s:%s" % (client_id or "?", ip or "anon")

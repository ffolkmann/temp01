"""SmartSearch tenant-config: admin-urlap <-> kanonikus JSON (S3).

Kanonikus alak (ez megy a ``tenants.search_config`` jsonb-be, es ez van a
``data/smartsearch.json`` fallbackben is)::

    {"enabled": true,
     "synonyms": [["felni", "kerek"], ...],
     "oneway": [{"f": "felnik", "t": ["felni"]}, ...],
     "popular_terms": [...], "popular_skus": [...],
     "merch": [{"kw": [...], "skus": [...], "w": "front",
                "from": "2026-08-01", "to": "2026-08-31"}]}

Az admin szoveges mezoket szerkeszt (soronkent) -- a ket irany kozotti forditas
es a normalizalas itt van, hogy a /admin vegpont csak hivja. STDLIB ONLY: a
tesztek fajlbol toltik be (a suite fake-app konvencioja miatt).
"""

import datetime
import json
import os
import re

MAX_TERMS = 8
MAX_SKUS = 10
MAX_GROUPS = 100
MAX_GROUP_TAGS = 8
MAX_MERCH = 100
MAX_MERCH_KW = 20
MAX_MERCH_SKUS = 50
MERCH_WEIGHTS = ("front", "up", "down", "back")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_CONFIG_PATH = "data/smartsearch.json"


# --------------------------------------------------------------------------- #
# alap-normalizalok
# --------------------------------------------------------------------------- #
def _one(value, maxlen=80):
    """Egy sorba tomoritett, trimmelt, hosszra vagott szoveg."""
    return " ".join(str(value if value is not None else "").split()).strip()[:maxlen]


def _split(line, maxlen=60):
    """Vesszos lista -> tisztitott elemek (ures elemek kiesnek)."""
    return [x for x in (_one(p, maxlen) for p in str(line or "").split(",")) if x]


def _lines(text):
    """Sortores vagy lista -> nem ures sorok listaja."""
    raw = text if isinstance(text, list) else \
        str(text if text is not None else "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return [ln for ln in (str(x).strip() for x in raw) if ln]


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _date(value):
    """Ervenyes YYYY-MM-DD vagy ures (a 2026-13-99 alaku szemet is kiesik)."""
    d = _one(value, 10)
    if not _DATE_RE.match(d):
        return ""
    try:
        datetime.date.fromisoformat(d)
    except ValueError:
        return ""
    return d


# --------------------------------------------------------------------------- #
# szinonimak
# --------------------------------------------------------------------------- #
def parse_groups(text):
    """Soronkent vesszos lista -> kolcsonos szinonima-csoportok (min 2 tag)."""
    out = []
    for line in _lines(text)[:MAX_GROUPS]:
        tags = _split(line, 40)[:MAX_GROUP_TAGS]
        if len(tags) >= 2:
            out.append(tags)
    return out


def groups_to_text(groups):
    if not isinstance(groups, list):
        return ""
    return "\n".join(", ".join(_one(t, 40) for t in g if _one(t, 40))
                     for g in groups if isinstance(g, list) and len(g) >= 2)


def parse_oneway(text):
    """Soronkent ``forras > cel1, cel2`` -> [{"f": .., "t": [..]}]."""
    out = []
    for line in _lines(text)[:MAX_GROUPS]:
        if ">" not in line:
            continue
        left, right = line.split(">", 1)
        frm = _one(left, 40)
        tos = _split(right, 40)[:MAX_GROUP_TAGS]
        if frm and tos:
            out.append({"f": frm, "t": tos})
    return out


def oneway_to_text(rows):
    if not isinstance(rows, list):
        return ""
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        frm = _one(r.get("f"), 40)
        tos = [_one(t, 40) for t in (r.get("t") or []) if _one(t, 40)]
        if frm and tos:
            out.append("%s > %s" % (frm, ", ".join(tos)))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# nepszeru listak
# --------------------------------------------------------------------------- #
def parse_terms(text):
    return [_one(x, 60) for x in _lines(text)][:MAX_TERMS]


def parse_skus(text):
    return [_one(x, 64) for x in _lines(text)][:MAX_SKUS]


def list_to_text(items):
    if not isinstance(items, list):
        return ""
    return "\n".join(_one(x, 64) for x in items if _one(x, 64))


# --------------------------------------------------------------------------- #
# merchandising
# --------------------------------------------------------------------------- #
def parse_merch(text):
    """Soronkent ``kulcsszavak | cikkszamok | suly | tol | ig``.

    A suly: front/up/down/back (ures -> front). Cikkszam nelkuli vagy ismeretlen
    sulyu sor kiesik; a hibas datum ures marad (= nyitott idoablak).
    """
    out = []
    for line in _lines(text)[:MAX_MERCH]:
        parts = [p.strip() for p in str(line).split("|")]
        parts += [""] * (5 - len(parts))
        kw = _split(parts[0], 60)[:MAX_MERCH_KW]
        skus = _split(parts[1], 64)[:MAX_MERCH_SKUS]
        weight = _one(parts[2], 10).lower() or "front"
        if not skus or weight not in MERCH_WEIGHTS:
            continue
        rule = {"kw": kw, "skus": skus, "w": weight}
        frm, to = _date(parts[3]), _date(parts[4])
        if frm:
            rule["from"] = frm
        if to:
            rule["to"] = to
        out.append(rule)
    return out


def merch_to_text(rules):
    if not isinstance(rules, list):
        return ""
    out = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        skus = [_one(s, 64) for s in (r.get("skus") or []) if _one(s, 64)]
        weight = _one(r.get("w"), 10).lower()
        if not skus or weight not in MERCH_WEIGHTS:
            continue
        kw = [_one(k, 60) for k in (r.get("kw") or []) if _one(k, 60)]
        cells = [", ".join(kw), ", ".join(skus), weight,
                 _date(r.get("from")), _date(r.get("to"))]
        while len(cells) > 3 and not cells[-1]:
            cells.pop()
        out.append(" | ".join(cells))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# urlap <-> config
# --------------------------------------------------------------------------- #
def form_to_config(form):
    """Admin-urlap (szoveges mezok) -> kanonikus config-dict."""
    f = form if isinstance(form, dict) else {}
    return {
        "enabled": _as_bool(f.get("enabled")),
        "synonyms": parse_groups(f.get("synonyms")),
        "oneway": parse_oneway(f.get("oneway")),
        "popular_terms": parse_terms(f.get("popular_terms")),
        "popular_skus": parse_skus(f.get("popular_skus")),
        "merch": parse_merch(f.get("merch")),
    }


def config_to_form(cfg):
    """Kanonikus config-dict -> admin-urlap (szoveges mezok)."""
    c = cfg if isinstance(cfg, dict) else {}
    return {
        "enabled": _as_bool(c.get("enabled")),
        "synonyms": groups_to_text(c.get("synonyms")),
        "oneway": oneway_to_text(c.get("oneway")),
        "popular_terms": list_to_text(c.get("popular_terms")),
        "popular_skus": list_to_text(c.get("popular_skus")),
        "merch": merch_to_text(c.get("merch")),
    }


def load_file_config(client_id, path=None):
    """A data/smartsearch.json tenant-blokkja (fallback / bootstrap forras)."""
    p = path or os.environ.get("SS_CONFIG", DEFAULT_CONFIG_PATH)
    try:
        with open(p, encoding="utf-8") as fh:
            cfg = json.load(fh)
        row = (cfg.get("tenants") or {}).get(client_id) if isinstance(cfg, dict) else None
    except Exception:  # noqa: BLE001 - hianyzo/rossz fajl: ures config
        return {}
    return row if isinstance(row, dict) else {}


def index_info(client_id, base=None):
    """A statikus index manifestje (frissesseg-kijelzo az adminban).

    A manifest a webrootban keszul (``/cxsearch/<tenant>/manifest.json``, ro mount).
    Hianyzo fajl / hibas JSON -> ``ok=False`` + magyarazat, sosem dob.
    """
    root = base or os.environ.get("SS_INDEX_DIR", "/cxsearch")
    path = os.path.join(root, str(client_id or ""), "manifest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            man = json.load(fh)
        if not isinstance(man, dict):
            raise ValueError("nem objektum")
    except FileNotFoundError:
        return {"ok": False, "error": "nincs index (a szinkron meg nem futott)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "manifest olvasas: %s" % str(e)[:80]}
    err = _one(man.get("error"), 160)
    try:
        built = int(man.get("built_at") or 0)
    except (TypeError, ValueError):
        built = 0
    return {
        "ok": not err,
        "error": err,
        "count": man.get("count"),
        "pcount": man.get("pcount"),
        "version": man.get("v"),
        "built_at": built,
    }

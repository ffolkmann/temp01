"""CX Konfigurator — tenant-ruleset kezeles (K2, stdlib-only, fajl-betoltheto).

A konfigurator PLATFORM-FUGGETLEN termek: a widget egy kerdes->szuro/boost
rulesetet hajt vegre a smartsearch-index (index.json + params.json) felett.
Az index barmely platform-mapperbol johet (sellvio/shoprenter/webdoc/unas) —
a ruleset a mapperek altal KANONIZALT parameter-nevekre hivatkozik, igy egy uj
tenant barmely platformon = index-config + ruleset, nulla kod.

Ruleset-alak (tenantonkent; igazsag-forras a tenants.konf_config jsonb,
fallback a data/konfigurator.json "tenants" blokkja — az s3 search-mintaval
azonos feloldas):

    {"enabled": true,
     "index_base": "https://codexpress.cloud/cx-search/<tenant>",
     "ui": {"title": "...", "intro": "...", "accent": "#d02b20", "unit": "nyomtato"},
     "questions": [
        {"id": "szin", "title": "...", "sub": "...", "type": "single"|"multi",
         "skip_label": "Mindegy",
         "options": [
            {"id": "szines", "label": "...", "sub": "...",
             "filter": [ COND, ... ],          # kemeny szuro (AND)
             "boost":  [ COND+{"w": int}, ... ]  # puha pontozas
            }]}],
     "prior": {"pin": ["SKU"...], "boost": ["SKU"...], "stock_w": 25, "sale_w": 8},
     "result": {"top_n": 4},
     "lead": {"enabled": true, "title": "...", "text": "...",
              "post_url": "https://...", "fallback_email": "info@..."}}

COND: {"param": "<kanonikus parameter-nev>"} VAGY {"field": "<i|k|n|b|c|p|a|o|d>"}
      + {"op": "eq|neq|has_any|gte|lte|exists", "value": ...}
A "param" a params.json nevterere, a "field" az index-rekord tomor mezoire megy
(c=kategoria, b=marka, p=ar, a=keszlet-flag, o=athuzott ar).

A normalize_ruleset a widgetnek szant, MEGTISZTITOTT alakot adja: ismeretlen
kulcsok es ervenytelen feltetelek kiesnek, minden szoveg/lista meretkorlatos —
a widget sosem kap olyan configot, amitol eltorhet.
"""
import json
import os

CONFIG_PATH_ENV = "KONF_CONFIG"
DEFAULT_CONFIG_PATH = "data/konfigurator.json"

OPS = ("eq", "neq", "has_any", "gte", "lte", "exists")
FIELDS = ("i", "k", "n", "b", "c", "p", "a", "o", "d")
MAX_QUESTIONS = 12
MAX_OPTIONS = 10
MAX_CONDS = 12
MAX_SKUS = 50
SORTS = ("ajanlott", "ar_asc", "ar_desc", "nepszeru")


def config_path():
    return os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH)


def load_file_config(client_id, path=None):
    """A tenant blokkja a data/konfigurator.json-bol (hibara ures dict)."""
    if not client_id:
        return {}
    try:
        with open(path or config_path(), encoding="utf-8") as fh:
            cfg = json.load(fh)
        tenants = cfg.get("tenants") if isinstance(cfg, dict) else None
        row = (tenants or {}).get(client_id)
        return row if isinstance(row, dict) else {}
    except Exception:  # noqa: BLE001 — a widget/endpoint sosem torhet el a configon
        return {}


def _s(v, maxlen=150):
    return " ".join(str(v if v is not None else "").split()).strip()[:maxlen]


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _int(v, lo, hi, default):
    n = _num(v)
    if n is None:
        return default
    return int(max(lo, min(hi, n)))


def norm_cond(c, with_w=False):
    """Egy feltetel tisztitasa; ervenytelen -> None."""
    if not isinstance(c, dict):
        return None
    if "param" in c:
        key = _s(c.get("param"), 60).lower()
        out = {"param": key}
    elif "field" in c:
        key = _s(c.get("field"), 2).lower()
        if key not in FIELDS:
            return None
        out = {"field": key}
    else:
        return None
    if not key:
        return None
    op = _s(c.get("op") or "eq", 12).lower()
    if op not in OPS:
        return None
    out["op"] = op
    v = c.get("value")
    if op in ("gte", "lte"):
        n = _num(v)
        if n is None:
            return None
        out["value"] = n
    elif op == "has_any":
        vals = v if isinstance(v, list) else [v]
        vals = [_s(x) for x in vals if _s(x)]
        if not vals:
            return None
        out["value"] = vals[:MAX_CONDS]
    elif op == "exists":
        pass
    else:  # eq / neq
        s = _s(v)
        if not s:
            return None
        out["value"] = s
    if with_w:
        out["w"] = _int(c.get("w"), 0, 1000, 0)
    return out


def _norm_conds(lst, with_w=False):
    out = []
    if isinstance(lst, list):
        for c in lst[:MAX_CONDS]:
            n = norm_cond(c, with_w=with_w)
            if n is not None:
                out.append(n)
    return out


def _norm_option(o):
    if not isinstance(o, dict):
        return None
    label = _s(o.get("label"), 120)
    if not label:
        return None
    out = {"id": _s(o.get("id"), 40) or label.lower()[:40], "label": label}
    sub = _s(o.get("sub"), 160)
    if sub:
        out["sub"] = sub
    f = _norm_conds(o.get("filter"))
    if f:
        out["filter"] = f
    b = _norm_conds(o.get("boost"), with_w=True)
    if b:
        out["boost"] = b
    return out


def _norm_question(q):
    if not isinstance(q, dict):
        return None
    title = _s(q.get("title"), 160)
    opts = []
    for o in (q.get("options") or [])[:MAX_OPTIONS]:
        n = _norm_option(o)
        if n is not None:
            opts.append(n)
    if not title or len(opts) < 2:
        return None
    out = {"id": _s(q.get("id"), 40) or "q", "title": title,
           "type": "multi" if _s(q.get("type")).lower() == "multi" else "single",
           "options": opts}
    sub = _s(q.get("sub"), 200)
    if sub:
        out["sub"] = sub
    skip = _s(q.get("skip_label"), 60)
    if skip:
        out["skip_label"] = skip
    return out


def _sku_list(v):
    if isinstance(v, str):
        v = [x for x in v.replace("\n", ",").replace(";", ",").split(",")]
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        s = _s(x, 64)
        if s and s not in out:
            out.append(s)
        if len(out) >= MAX_SKUS:
            break
    return out


def _http_url(v, maxlen=300):
    s = _s(v, maxlen)
    return s if s.startswith("http://") or s.startswith("https://") else ""


def _sort_key(v):
    s = _s(v, 20).lower()
    return s if s in SORTS else ""


def _sorts(v):
    """Rendezes-modok whitelistelve, sorrend-tartoan, duplikatum nelkul."""
    if not isinstance(v, list):
        return list(SORTS)
    out = []
    for x in v[:len(SORTS)]:
        k = _sort_key(x)
        if k and k not in out:
            out.append(k)
    return out or list(SORTS)


def normalize_ruleset(cfg):
    """A widgetnek szant, tisztitott konfiguracio (ismeretlen tenantra kikapcsolt)."""
    if not isinstance(cfg, dict):
        cfg = {}
    ui_in = cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {}
    prior_in = cfg.get("prior") if isinstance(cfg.get("prior"), dict) else {}
    res_in = cfg.get("result") if isinstance(cfg.get("result"), dict) else {}
    lead_in = cfg.get("lead") if isinstance(cfg.get("lead"), dict) else {}
    stock_in = cfg.get("stock") if isinstance(cfg.get("stock"), dict) else {}
    img_in = cfg.get("image") if isinstance(cfg.get("image"), dict) else {}
    questions = []
    for q in (cfg.get("questions") or [])[:MAX_QUESTIONS]:
        n = _norm_question(q)
        if n is not None:
            questions.append(n)
    body = {
        "enabled": bool(cfg.get("enabled")) and bool(questions),
        "index_base": _http_url(cfg.get("index_base")),
        "ui": {
            "title": _s(ui_in.get("title"), 80) or "Term\u00e9kv\u00e1laszt\u00f3",
            "intro": _s(ui_in.get("intro"), 300),
            "accent": _s(ui_in.get("accent"), 20) or "#d02b20",
            "unit": _s(ui_in.get("unit"), 30) or "term\u00e9k",
        },
        "questions": questions,
        "prior": {
            "pin": _sku_list(prior_in.get("pin")),
            "boost": _sku_list(prior_in.get("boost")),
            "stock_w": _int(prior_in.get("stock_w"), 0, 1000, 25),
            "sale_w": _int(prior_in.get("sale_w"), 0, 1000, 8),
        },
        "result": {
            "top_n": _int(res_in.get("top_n"), 1, 12, 4),
            "more_n": _int(res_in.get("more_n"), 0, 200, 60),
            "sorts": _sorts(res_in.get("sorts")),
            "sort_default": _sort_key(res_in.get("sort_default")) or "ajanlott",
            "pin_label": _s(res_in.get("pin_label"), 30) or "Kiemelt",
        },
        "stock": {
            "only_available": bool(stock_in.get("only_available")),
            "label_in": _s(stock_in.get("label_in"), 30) or "K\u00e9szleten",
            "label_out": _s(stock_in.get("label_out"), 30) or "Rendelhet\u0151",
        },
        "image": {
            "prefix": _http_url(img_in.get("prefix")),
            "suffix": _s(img_in.get("suffix"), 20),
        },
        "lead": {
            "enabled": bool(lead_in.get("enabled")),
            "title": _s(lead_in.get("title"), 120),
            "text": _s(lead_in.get("text"), 400),
            "post_url": _http_url(lead_in.get("post_url")),
            "fallback_email": _s(lead_in.get("fallback_email"), 120),
        },
    }
    if not body["index_base"]:
        body["enabled"] = False
    return body


# --------------------------------------------------------------------------- #
# admin-kartya <-> config (a searchcfg mintajara)
# --------------------------------------------------------------------------- #
def config_to_form(cfg):
    """Admin-urlap mezok a nyers configbol."""
    if not isinstance(cfg, dict):
        cfg = {}
    prior = cfg.get("prior") if isinstance(cfg.get("prior"), dict) else {}
    res = cfg.get("result") if isinstance(cfg.get("result"), dict) else {}
    return {
        "enabled": bool(cfg.get("enabled")),
        "pin": ", ".join(_sku_list(prior.get("pin"))),
        "boost": ", ".join(_sku_list(prior.get("boost"))),
        "top_n": _int(res.get("top_n"), 1, 12, 4),
        "stock_only": bool((cfg.get("stock") or {}).get("only_available"))
        if isinstance(cfg.get("stock"), dict) else False,
        "config_json": json.dumps(cfg, ensure_ascii=False, indent=2) if cfg else "",
    }


def form_to_config(form, fallback=None):
    """Admin-urlapbol nyers config. (cfg, hiba) — hibas JSON eseten (None, uzenet)."""
    form = form if isinstance(form, dict) else {}
    raw = str(form.get("config_json") or "").strip()
    if raw:
        try:
            base = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            return None, "config_json nem ervenyes JSON: %s" % e
        if not isinstance(base, dict):
            return None, "config_json nem objektum"
    else:
        base = dict(fallback) if isinstance(fallback, dict) else {}
    base["enabled"] = bool(form.get("enabled"))
    prior = base.get("prior") if isinstance(base.get("prior"), dict) else {}
    prior["pin"] = _sku_list(form.get("pin"))
    prior["boost"] = _sku_list(form.get("boost"))
    base["prior"] = prior
    res = base.get("result") if isinstance(base.get("result"), dict) else {}
    res["top_n"] = _int(form.get("top_n"), 1, 12, 4)
    base["result"] = res
    stock = base.get("stock") if isinstance(base.get("stock"), dict) else {}
    stock["only_available"] = bool(form.get("stock_only"))
    base["stock"] = stock
    return base, None

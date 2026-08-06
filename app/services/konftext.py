"""CX Konfigurator — kerdes-szovegek AI-val (K3/3).

A kerdes-epito (admin) NYERS tervezetet general az index-adatbol: a cimek a
parameter-nevek ("Technologia - melyik felel meg?"), az opcio-cimkek a nyers
ertekek ("DADF"). Ez a modul ezekbol ir emberi szoveget: kerdes-cim, opcio-
cimke + rovid magyarazat, es kerdesenkenti sugo.

FONTOS: a modul CSAK SZOVEGET ad vissza. A szuro/boost feltetelekhez soha nem
nyul — az id-k alapjan parositunk, ismeretlen id kiesik. Igy egy rossz LLM-
valasz sem tudja elrontani a mukodo rulesetet.
"""
import json
import logging

logger = logging.getLogger("cx.konftext")

MAX_TITLE = 160
MAX_LABEL = 120
MAX_SUB = 160
MAX_HELP = 800
MAX_QUESTIONS = 12
MAX_OUT_TOKENS = 8000   # 12 kerdes sugoval bo keret

SYSTEM = (
    "Magyar e-kereskedelmi szovegiro vagy. Egy webaruhaz termekvalaszto "
    "varazslojanak kerdeseit fogalmazod meg ugy, ahogy egy tapasztalt bolti "
    "elado kerdezne — a vasarlo HELYZETERE kerdezel, nem a muszaki "
    "specifikaciora.\n\n"
    "Szabalyok:\n"
    "1. A kerdes cime rovid, kozvetlen, tegezo, es a hasznalatra kerdez "
    "(pl. 'Havonta korulbelul hany oldalt nyomtattok?' es NEM "
    "'Sebesseg ppm - melyik felel meg?').\n"
    "2. Az opcio-cimke legfeljebb 8 szo, a vasarlo nyelven. Ha a nyers ertek "
    "szakmai rovidites, forditsd le (pl. 'DADF' -> 'Automata ketoldalas "
    "lapadagolo'). A 'sub' mezobe egy fel mondatos gyakorlati magyarazat "
    "kerul, vagy hagyd uresen.\n"
    "3. A 'help' 300-600 karakteres sugo: mit jelent a kerdes, mibol erdemes "
    "kiindulni, mi a kovetkezmenye a valasztasnak. Konkret fogodzot adj "
    "(pl. 'egy csomag papir 500 oldal'), ne altalanossagot. Ne igerj olyat, "
    "amit az adat nem tamaszt ala, es ne emlits arat.\n"
    "4. A jelentest NEM valtoztathatod meg: az opcio ugyanazt a termekkort "
    "kell jelentse, mint a hozza tartozo szuro-feltetel.\n"
    "5. Ne hasznalj marketing-tolteleket ('a legjobb valasztas', "
    "'forradalmi'), ne szolitsd meg a felhasznalot nevvel.\n\n"
    "A valaszod KIZAROLAG egy JSON objektum, semmi mas — se bevezeto, se "
    "markdown kodblokk."
)


def _s(v, maxlen):
    return " ".join(str(v if v is not None else "").split()).strip()[:maxlen]


def cond_text(c):
    """Egy feltetel emberi leirasa a promptnak (a modell ebbol tudja, mit jelent)."""
    if not isinstance(c, dict):
        return ""
    key = c.get("param") or ("alapadat:" + str(c.get("field") or ""))
    op = str(c.get("op") or "eq")
    val = c.get("value")
    if isinstance(val, list):
        val = ", ".join(str(x) for x in val)
    names = {"eq": "=", "neq": "!=", "has_any": "egyike:", "gte": ">=",
             "lte": "<=", "exists": "meg van adva"}
    if op == "exists":
        return "%s %s" % (key, names[op])
    return "%s %s %s" % (key, names.get(op, op), val)


def build_user_prompt(cfg):
    """A ruleset -> ember/gep altal is olvashato feladat-leiras."""
    ui = cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {}
    lines = []
    unit = _s(ui.get("unit"), 30) or "termek"
    lines.append("Webaruhaz termekkore: %s (a varazslo ezt ajanlja)." % unit)
    if ui.get("title"):
        lines.append("A varazslo cime: %s" % _s(ui.get("title"), 80))
    if ui.get("intro"):
        lines.append("Bevezeto szoveg (a hangnem ehhez igazodjon): %s" % _s(ui.get("intro"), 300))
    lines.append("")
    lines.append("Az alabbi kerdes-tervezet nyers: a cimek es cimkek gepi "
                 "generalasbol szarmaznak. Fogalmazd meg oket emberi nyelven.")
    lines.append("A zarojeles resz a technikai feltetel — CSAK a megertest "
                 "segiti, a valaszban NE szerepeljen.")
    lines.append("")
    for q in (cfg.get("questions") or [])[:MAX_QUESTIONS]:
        if not isinstance(q, dict):
            continue
        lines.append("KERDES id=%s tipus=%s" % (q.get("id"), q.get("type") or "single"))
        lines.append("  jelenlegi cim: %s" % _s(q.get("title"), MAX_TITLE))
        for o in (q.get("options") or []):
            if not isinstance(o, dict):
                continue
            conds = [cond_text(c) for c in (o.get("filter") or [])]
            boosts = [cond_text(c) for c in (o.get("boost") or [])]
            det = []
            if conds:
                det.append("szur: " + " ES ".join(x for x in conds if x))
            if boosts:
                det.append("elorebb sorol: " + " ES ".join(x for x in boosts if x))
            lines.append("  - OPCIO id=%s cimke=%s (%s)" % (
                o.get("id"), _s(o.get("label"), MAX_LABEL),
                "; ".join(det) if det else "nincs feltetel, csak valasztas"))
        lines.append("")
    lines.append("Valasz-formatum (pontosan ezek a kulcsok, az id-ket VALTOZATLANUL add vissza):")
    lines.append('{"questions":[{"id":"...","title":"...","help":"...",'
                 '"options":[{"id":"...","label":"...","sub":"..."}]}]}')
    return "\n".join(lines)


def parse_result(text, cfg):
    """Az LLM valaszabol csak a SZOVEGEK, id-k szerint parositva.

    Visszaad: {qid: {"title":..., "help":..., "options": {oid: {"label","sub"}}}}
    Ismeretlen id, hianyzo mezo, hibas JSON -> csendben kiesik (a hivo a
    valtozatlan rulesetet tartja meg).
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1] if "```" in raw[3:] else raw.strip("`")
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        data = json.loads(raw[i:j + 1])
    except Exception:  # noqa: BLE001
        return {}
    valid_q = {}
    for q in (cfg.get("questions") or []):
        if isinstance(q, dict) and q.get("id"):
            valid_q[str(q["id"])] = {str(o.get("id")) for o in (q.get("options") or [])
                                     if isinstance(o, dict) and o.get("id")}
    out = {}
    for q in (data.get("questions") or [])[:MAX_QUESTIONS]:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "")
        if qid not in valid_q:
            continue
        item = {}
        t = _s(q.get("title"), MAX_TITLE)
        if t:
            item["title"] = t
        h = _s(q.get("help"), MAX_HELP)
        if h:
            item["help"] = h
        opts = {}
        for o in (q.get("options") or []):
            if not isinstance(o, dict):
                continue
            oid = str(o.get("id") or "")
            if oid not in valid_q[qid]:
                continue
            rec = {}
            lb = _s(o.get("label"), MAX_LABEL)
            if lb:
                rec["label"] = lb
            sb = _s(o.get("sub"), MAX_SUB)
            if sb:
                rec["sub"] = sb
            if rec:
                opts[oid] = rec
        if opts:
            item["options"] = opts
        if item:
            out[qid] = item
    return out


def apply_texts(cfg, texts):
    """A szovegek beirasa a ruleset MASOLATABA (feltetelek erintetlenul)."""
    out = json.loads(json.dumps(cfg))  # mely masolat, stdlib-bol
    for q in (out.get("questions") or []):
        if not isinstance(q, dict):
            continue
        t = texts.get(str(q.get("id") or ""))
        if not t:
            continue
        if t.get("title"):
            q["title"] = t["title"]
        if t.get("help"):
            q["help"] = t["help"]
        for o in (q.get("options") or []):
            if not isinstance(o, dict):
                continue
            r = (t.get("options") or {}).get(str(o.get("id") or ""))
            if not r:
                continue
            if r.get("label"):
                o["label"] = r["label"]
            if r.get("sub"):
                o["sub"] = r["sub"]
    return out


async def generate(cfg, model=None):
    """(uj_cfg, hiba) — a ruleset szovegei ujrairva. Hibara (cfg, uzenet)."""
    if not isinstance(cfg, dict) or not (cfg.get("questions") or []):
        return cfg, "nincs kerdes a konfiguracioban"
    # SAJAT hivas, NEM a chat generate_reply-ja: a globalis max_tokens (2048) a
    # chat-valaszra van meretezve, es itt bizonyitottan felbevagta a JSON-t
    # (860 karakter utan, az elso kerdes kozepen).
    from anthropic import AsyncAnthropic   # lazy: a fajl-betoltos tesztek miatt

    from app.core.settings import get_settings

    st = get_settings()
    mdl = (model or "").strip() or st.chat_model
    try:
        resp = await AsyncAnthropic(api_key=st.anthropic_api_key).messages.create(
            model=mdl,
            max_tokens=MAX_OUT_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": build_user_prompt(cfg)}],
        )
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", None) == "text")
        stop = getattr(resp, "stop_reason", None)
        if stop == "max_tokens":
            logger.warning("konftext: a valasz elerte a token-keretet (%s kerdes)",
                           len(cfg.get("questions") or []))
    except Exception as e:  # noqa: BLE001 — az admin sosem eshet el ettol
        logger.warning("konftext: LLM hiba: %s", e)
        return cfg, "a szoveggeneralas nem sikerult (%s)" % type(e).__name__
    texts = parse_result(text, cfg)
    if not texts:
        return cfg, "a valasz nem volt ertelmezheto - probald ujra"
    return apply_texts(cfg, texts), None

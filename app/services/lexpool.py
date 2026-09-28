"""m108: lexikai jelolt-pool az ar-szuperlativusz aghoz (CX Smart Search + tenant-szinonimak).

Kivalto eset (copygo, 2026-09-16/25/28, ugyanaz a kerdes 4x): "melyik a legolcsobb lezer
nyomtato?" -> a szuperlativusz-ag a TEMAT ('lezer nyomtato') dense-embedeli, es a vektor a
nevben "Laser" szot hordozo NEM nyomtatokat hozza (Logitech R400 Laser Pointer, egerek,
vonalkod-olvaso "LASER") -> a pool 0 nyomtatot tartalmaz, a bot "nem latok lezernyomtatot"-ot
mond, mikozben a katalogusban 72 raktaros lezernyomtato van (d28a_diag3).

A dense vektor a tobbszavas temanal a ritkabb/"erosebb" szora ugrik; a lexikai egyezes ezt nem
teszi. A CX Smart Search (app/services/searchq.py) szerver-oldali indexe (cx_search_<tenant>)
pontosan ezt tudja: token-prefix szures a nev+marka+KATEGORIA szovegen, a tenant admin-ban
szerkesztheto szinonima-szotaraval (search_config.synonyms / oneway). Ez a modul azt hasznalja
jelolt-forraskent -- igy EGY szotar javitja a keresot es a chatet.

HATOKOR (konzervativ):
  - csak ar-szuperlativusznal, csak ha a tenantnak van szerver-oldali kereso-profilja
    (search_config.enabled + server.enabled; ma: copygo, teslashop), kulonben None;
  - csak ha a dense pool elso 8 termekenek nevei ROSSZUL fedik a temat (< DENSE_COVER_MIN),
    igy ahol a dense ma jo, ott semmi nem valtozik;
  - csak "and" modu lexikai talalat (minden tema-token illeszkedik) szamit;
  - a kiegeszito-nevu tetelek (papir/toner/patron/tok/kabel...) kiesnek, HACSAK a tema maga
    nem kiegeszito ("legolcsobb toner" -> a toner a keresett termek);
  - >= MIN_HITS arazott, a chat-kollekcioban is megtalalt termek kell, kulonben None
    (a hivo a mai utat viszi tovabb).
A kimenet a chat-kollekcio (cx_chatbot_v2) SAJAT pontjai (cikkszam szerint visszakeresve),
tehat a prompt / link / keszlet-logika valtozatlanul mukodik rajtuk.
"""
from __future__ import annotations

import logging
import os
import time

try:
    from app.search import qtext
except Exception:  # file-load teszt / fake `app`
    import importlib.util as _ilu
    _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "search", "qtext.py")
    _s = _ilu.spec_from_file_location("lexpool_dep_qtext", _p)
    qtext = _ilu.module_from_spec(_s)
    _s.loader.exec_module(qtext)

logger = logging.getLogger("cx.lexpool")

LEX_LIMIT = 100         # lexikai relevancia-jeloltek (a Smart Search rel-rangsorabol, max 100)
PRICE_PAGES = 3         # az ar szerinti veg ennyi LEX_LIMIT-es lapja (kiegeszitok utan is maradjon gep)
MIN_HITS = 3            # ennyi arazott, visszakeresett termek alatt nincs csere
DENSE_TOP = 8           # a dense pool ennyi elso termeket nezzuk a fedeshez
DENSE_COVER_MIN = 2     # ha ennyi vagy tobb dense-termek fedi a temat -> a dense jo, nincs csere
CFG_TTL = 300.0

# kiegeszito-szavak (foldolt). ACC_PREFIXES: a szoban BARHOL (osszetett szo: lezertoner);
# ACC_WORDS: csak egesz szokent (a rovid szavak kulonben hamis talalatot adnanak:
# tok -> tokeletes, tinta -> tintasugaras).
ACC_PREFIXES = (
    "taska", "hatizsak", "sleeve", "egerpad", "dokkolo", "allvany", "kabel", "adapter",
    "tolto", "patron", "tintapatron", "toner", "folia", "papir", "fotopapir", "festek",
    "dobegyseg", "kellek", "hulladek", "karbantarto", "fixalo", "kazetta",
    "utangyartott", "tartozek", "alkatresz", "tisztito",
)
ACC_WORDS = frozenset(("tok", "tokok", "huzat", "tinta", "tintak", "drum", "szalag"))

_cfg_cache: dict[str, tuple[float, dict]] = {}


def _joined(s: str) -> str:
    return "".join(qtext.words(s))


def topic_groups(topic: str, syn: dict | None = None, ow: dict | None = None) -> list[list[str]]:
    """A tema tokenjei szinonima-alternativakkal (a Smart Search logical_groups parja)."""
    syn, ow = syn or {}, ow or {}
    out = []
    for t in qtext.tokens(topic):
        if syn.get(t):
            out.append(list(syn[t]))
        elif ow.get(t):
            out.append([t] + list(ow[t]))
        else:
            out.append([t])
    return out


def query_variants(topic: str) -> list[str]:
    """A tema + (2-3 tokennel) az OSSZEIRT alakja. A Smart Search token-PREFIX egyezest
    csinal: a 'lezer nyomtato' ES-szurese nem talalja a 'Lezernyomtato HL-1110E'-t (a
    'nyomtato' nem szo-eleje), az osszeirt 'lezernyomtato' viszont igen -- es forditva
    (sweep d28a_m108f: a legolcsobb valodi gep csak az egyik alakban jott elo)."""
    toks = qtext.tokens(topic)
    out = [topic]
    if 2 <= len(toks) <= 3:
        j = "".join(toks)
        if j not in out:
            out.append(j)
    return out


SPLIT_MIN = 8   # ennyi karaktertol probaljuk az osszetett tema-szot ket (>=4 betus) reszre bontani


def _alt_in(a: str, j: str) -> bool:
    """`a` benne van-e a szokoz nelkuli nevben; hosszu osszetett szonal ket darabban is
    ('lezernyomtato' ~ '... lezer ... nyomtato': 'HP LaserJet mono lezer egyfunkcios nyomtato')."""
    if not a:
        return False
    if a in j:
        return True
    if len(a) >= SPLIT_MIN:
        for i in range(4, len(a) - 3):
            if a[:i] in j and a[i:] in j:
                return True
    return False


def covers(name: str, groups: list[list[str]]) -> bool:
    """A nev (szokoz nelkul, foldolva) minden token-csoportbol tartalmaz-e egy alternativat.
    Szokoz nelkul: 'lezer'+'nyomtato' fedi a 'lezernyomtato'-t es forditva is."""
    if not groups:
        return False
    j = _joined(name)
    return all(any(_alt_in(a, j) for a in g) for g in groups)


def is_accessory(name: str, topic: str) -> bool:
    """A nevben kiegeszito-szo van, ami a temaban NINCS (a tema maga is lehet kiegeszito).
    A hosszabb kiegeszito-szavak osszetett szo BELSEJEBEN is szamitanak
    ('lezertoner', 'masolopapir', 'monitorallvany' -- sweep d28a_m108d)."""
    tj = _joined(topic)
    for w in qtext.words(name):
        if w in ACC_WORDS and w not in tj:
            return True
        for a in ACC_PREFIXES:
            if a in w and a not in tj:
                return True
    return False


def dense_cover(hits: list[dict], groups: list[list[str]], top: int = DENSE_TOP) -> int:
    """Hany TERMEK fedi a temat a dense pool elso `top` termeke kozul."""
    n = 0
    k = 0
    for h in hits or []:
        p = h.get("payload", h) if isinstance(h, dict) else {}
        if str(p.get("type") or "").lower() != "product" and not str(p.get("sku") or "").strip():
            continue
        k += 1
        if covers(str(p.get("name") or ""), groups):
            n += 1
        if k >= top:
            break
    return n


def pick_rows(rows: list[dict], topic: str, groups: list[list[str]]) -> list[dict]:
    """Smart Search rekordok (n,k,p,...) -> arazott, a temat a NEVBEN fedo, nem-kiegeszito
    tetelek, sorrendtartoan, cikkszam szerint egyedien.

    A nev-fedes kapu kell, mert a Smart Search szuro a KATEGORIA-szoveget is nezi, es a
    gyujto-kategoriak ('... okosora kiegeszitok') kabelt / telefont is behoznak
    (sweep d28a_m108f: 'okosora' -> 2888 talalat, a legolcsobbak USB-kabelek)."""
    out = []
    seen = set()
    for r in rows or []:
        k = str(r.get("k") or "").strip()
        if not k or k in seen:
            continue
        try:
            if float(r.get("p") or 0) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        name = str(r.get("n") or "")
        if not covers(name, groups):
            continue
        if is_accessory(name, topic):
            continue
        seen.add(k)
        out.append(r)
    return out


def server_enabled(cfg: dict) -> bool:
    s = cfg.get("server") if isinstance(cfg, dict) else None
    return bool(cfg.get("enabled")) and isinstance(s, dict) and bool(s.get("enabled"))


async def _tenant_cfg(client_id: str) -> dict:
    now = time.monotonic()
    hit = _cfg_cache.get(client_id)
    if hit and now - hit[0] < CFG_TTL:
        return hit[1]
    from app.api.search import get_config
    from app.core.db import SessionLocal
    async with SessionLocal() as session:
        cfg = await get_config(session, client_id)
    cfg = cfg if isinstance(cfg, dict) else {}
    _cfg_cache[client_id] = (now, cfg)
    return cfg


async def _fetch_chat_points(client_id: str, skus: list[str]) -> dict[str, dict]:
    """A chat-kollekcio termek-pontjai cikkszam szerint (sku -> {'id','payload'})."""
    from app.api.search import qdrant_client
    from app.core.qdrant import get_qdrant
    col = getattr(get_qdrant(), "collection", None) or "cx_chatbot_v2"
    body = {
        "filter": {"must": [
            {"key": "client_id", "match": {"value": client_id}},
            {"key": "sku", "match": {"any": skus}},
        ]},
        "limit": len(skus) * 3, "with_payload": True, "with_vector": False,
    }
    r = await qdrant_client().post(f"/collections/{col}/points/scroll", json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"chat scroll {r.status_code}")
    out: dict[str, dict] = {}
    for p in (r.json().get("result") or {}).get("points") or []:
        pl = p.get("payload") or {}
        if str(pl.get("type") or "").lower() != "product":
            continue
        out.setdefault(str(pl.get("sku") or ""), {"id": p.get("id"), "payload": pl})
    return out


async def superlative_lex_pool(
    client_id: str, topic: str, dense_hits: list[dict], direction: str = "asc",
    *, cfg: dict | None = None, search_fn=None, fetch_fn=None,
) -> list[dict] | None:
    """A szuperlativusz-ag uj jelolt-poolja (chat-hit alaku) vagy None.

    Jeloltek (a tema minden query_variants alakjara, csak "and" modu talalat): a lexikai
    relevancia-rangsor eleje (LEX_LIMIT) + az AR szerinti veg (direction szerint,
    PRICE_PAGES x LEX_LIMIT) -- a relevancia-plafon kulonben kivaghatja epp a legolcsobb
    valodi termeket (sweep d28a_m108d: a HL-1110E kimaradt a rel-100-bol).
    None = nincs valtozas (nincs profil / a dense jo / keves lexikai talalat). Kivetelt a
    hivo nyel el (fail-safe).
    """
    topic = " ".join(str(topic or "").split())
    if len(topic) < 3:
        return None
    if cfg is None:
        cfg = await _tenant_cfg(client_id)
    if not server_enabled(cfg):
        return None
    if search_fn is None:
        from app.api.search import qdrant_client
        from app.services import searchq as _sq

        async def search_fn(q, sort="rel", offset=0):  # noqa: ANN001
            return await _sq.search(qdrant_client(), cfg, client_id, q, limit=LEX_LIMIT,
                                    offset=offset, sort=sort)
        syn, ow = _sq.synonyms(cfg), _sq.oneway(cfg)
    else:
        syn, ow = {}, {}
    groups = topic_groups(topic, syn, ow)
    if not groups:
        return None
    dc = dense_cover(dense_hits, groups)
    if dc >= DENSE_COVER_MIN:
        logger.info("m108 lex pool: skip dense_cover=%d topic=%r client=%s", dc, topic, client_id)
        return None
    raw: list[dict] = []
    totals = []
    psort = "pd" if direction == "desc" else "pa"
    for qv in query_variants(topic):
        res = await search_fn(qv, "rel", 0) or {}
        if str(res.get("mode") or "") != "and":
            continue  # csak a teljes (minden tokenes) egyezes szamit
        total = int(res.get("total") or 0)
        totals.append(total)
        raw.extend(res.get("hits") or [])
        for page in range(PRICE_PAGES):
            off = page * LEX_LIMIT
            if off >= total:
                break
            pr = await search_fn(qv, psort, off) or {}
            raw.extend(pr.get("hits") or [])
    rows = pick_rows(raw, topic, groups)
    if len(rows) < MIN_HITS:
        logger.info("m108 lex pool: no-go totals=%s kept=%d dense_cover=%d topic=%r client=%s",
                    totals, len(rows), dc, topic, client_id)
        return None
    if fetch_fn is None:
        fetch_fn = _fetch_chat_points
    pts = await fetch_fn(client_id, [str(r.get("k")) for r in rows])
    out = []
    n = len(rows)
    for i, r in enumerate(rows):
        pt = pts.get(str(r.get("k")))
        if not pt:
            continue
        # lexikai rang -> score (a m40 price_context 'tema-relevancia' fele es a m61 ar-padlo ezt nezi)
        out.append({"id": pt.get("id"), "score": round(1.0 - i / (n + 1), 4), "payload": pt["payload"]})
    if len(out) < MIN_HITS:
        logger.info("m108 lex pool: no-go mapped=%d/%d topic=%r client=%s", len(out), len(rows), topic, client_id)
        return None
    logger.info("m108 lex pool: USED topic=%r dense_cover=%d totals=%s kept=%d mapped=%d client=%s",
                topic, dc, totals, len(rows), len(out), client_id)
    return out

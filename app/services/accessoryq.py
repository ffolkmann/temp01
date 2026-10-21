"""m127/c (K2, d21c): kiegeszito-kerdes a megnyitott termekhez.

Lelet (30 napos korpusz, hamis "nincs" valaszok termekoldalon): "Hol talalok hozza uj tonert?",
"Ehhez a gephez milyen toltot tudok nalatok venni?", "arulnak-e hozza ontapados cimket?",
"ajanlj egy USB kabelt hozza", "Base Station satorhoz teli takarot keresek". A chat.py embed_inputja
termekoldalon = termeknev + uzenet -> a dense pool a termek SAJAT testvereit (masik nyomtato,
masik notebook) hozza, a kiegeszito nincs a kontextusban, a bot "nem latok ilyet"-et mond.

Meres (d21c/k2_accsim2.py, 16 kezi eset, elo Qdrant, LLM nelkul): a mai pool 8/16 esetben
tartalmaz kiegeszitot; masodik kereses marka + uzenet embeddel 11/16, CSAK a kerdes tartalmas
szavaival 12/16 - a marka az embedben a termek testvereit hozza vissza (Brother -> cimkenyomtatok,
Lenovo -> notebookok). Ezert: az embed a tartalmas szavakbol all, a marka csak a jeloltek
SORRENDJET adja (azonos marka elore).

Mukodes (fail-safe, a hivo try-ban hivja): ha az uzenet a termekre VISSZAUTAL (hozza, ehhez,
-hoz/-hez, valo, kompatibilis, illik...) es van tartalmas szava, masodik dense kereses a tartalmas
szavakbol, csak termekek, hide_oos -> csak raktaros; a rerank utan legfeljebb MAX_ADD uj termek a
pool VEGERE (a nezett termek es a mar bent levok nem).
"""
import re
import unicodedata

MAX_ADD = 3
POOL = 24

_REF = re.compile(
    r"\b(hozza|hozzavalo|ehhez|ehez|ahhoz|ennek|ezhez|ra|erre|valo|valot|kompatibilis|illik|illo|passzol|"
    r"tartozek|tartozekot|kiegeszito|kiegeszitot|alkatresz|alkatreszt|potalkatresz)\b"
    r"|[a-z]{3,}(hoz|hez|hoz)\b")
# a kerdes-keretbol az embedbe NEM kerulo szavak (a lexmatch STOP mellett)
_FRAME = set("""hozza hozzavalo ehhez ehez ahhoz ennek ezhez erre valo valot kompatibilis illik illo passzol
kell kellene tudok tudnek nalatok nallatok venni vasarolni arulnak arultok keresek keresnek ajanlj ajanlasz
ajanlani milyen mlyen melyik van hol talalok talalom kulon egy meterig termekhez gephez lenne szukseg
szuksegem rendelni kapni""".split())


def _fold(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def content_words(message):
    """A kerdes tartalmas szavai a visszautalo / keret-szavak nelkul (ezekbol lesz az embed)."""
    try:
        from app.services.lexmatch import query_tokens
        toks = query_tokens(message)
    except Exception:  # noqa: BLE001
        toks = re.findall(r"[a-z0-9]{3,}", _fold(message))
    out = []
    for t in toks:
        if "~" in t or t in _FRAME or _REF.fullmatch(t):
            continue
        out.append(t)
    return out


def is_accessory_query(message):
    """A termekre visszautalo kiegeszito-kerdes (a hivo csak termekoldalon kerdezi)."""
    f = _fold(message)
    if not _REF.search(f):
        return False
    try:
        from app.services.lexmatch import _skip
        if _skip(message):  # bolti tema / meta / szabalyzat / ar-szuperlativusz: nem kiegeszito-kereses
            return False
    except Exception:  # noqa: BLE001
        pass
    return bool(content_words(message))


def _cur_url(current):
    pl = getattr(current, "payload", None) or {}
    return str(pl.get("url") or "").strip()


async def accessory_hits(hits, message, client_id, current, hide_oos=False, limit=MAX_ADD):
    """-> (hozzaadott darab, uj hits). Hiba / nem kell -> (0, hits valtozatlanul)."""
    hits = list(hits or [])
    if not is_accessory_query(message):
        return 0, hits
    from app.core.embeddings import embed_query
    from app.core.qdrant import get_qdrant
    from app.services.rerank import rerank
    words = content_words(message)
    if not words:
        return 0, hits
    # az eredeti (ekezetes) szavak az embedbe (az embed ekezet nelkul gyengebb - m85 tanulsag)
    ein = " ".join(words)
    try:
        raw_words = re.findall(r"[^\W_]+", str(message or ""), flags=re.UNICODE)
        keep = [w for w in raw_words if _fold(w) in words]
        if keep:
            ein = " ".join(keep)
    except Exception:  # noqa: BLE001
        pass
    vec = await embed_query(ein)
    qd = get_qdrant()
    pool = await qd.search(vector=vec, client_id=client_id, limit=POOL, product_only=True,
                           available_only=bool(hide_oos))
    if not pool and hide_oos:
        pool = await qd.search(vector=vec, client_id=client_id, limit=POOL, product_only=True)
    if not pool:
        return 0, hits
    have = {str(h.get("id")) for h in hits if isinstance(h, dict)}
    cur = _cur_url(current)
    brand = _fold(((getattr(current, "payload", None) or {}).get("brand") or "")).strip()
    cand = []
    for h in rerank(message, pool, top_n=limit * 3):
        if not isinstance(h, dict) or str(h.get("id")) in have:
            continue
        pl = h.get("payload") or {}
        if str(pl.get("type") or "") != "product":
            continue
        if cur and str(pl.get("url") or "").strip() == cur:
            continue
        cand.append(h)
    if brand:  # azonos marka elore (stabil rendezes: a relevancia-sorrend megmarad)
        cand.sort(key=lambda h: 0 if brand in _fold((h.get("payload") or {}).get("brand") or
                                                      (h.get("payload") or {}).get("name")) else 1)
    add = []
    for h in cand[:limit]:
        h2 = dict(h)
        h2["m127"] = True
        add.append(h2)
    if not add:
        return 0, hits
    return len(add), hits + add

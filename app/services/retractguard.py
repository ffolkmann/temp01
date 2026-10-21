# -*- coding: utf-8 -*-
"""m125 (K1): a bot ne vonja vissza a sajat, korabban helyes valaszat.

Lelet (d21a audit + d21b meres, 2026-10-21): a kovetkezo korben a modell csak a korabbi
valaszai SZOVEGET latja, az akkori # TUDASBAZIS-t nem. A m33 teny-korlat ("osszeget csak a
kapott adatokbol") es a m77 jegyzet ("roviden jelezd, hogy pontositod a korabbi informaciot",
ami az oos_guard modban szinte minden follow-upra rakerult) miatt a mostani kontextusban nem
szereplo sajat allitasat "nem megerositheto"-nek nyilvanitja es visszavonja (fizetesi mod,
szallitasi dij, uzletcim, mar linkelt termek). Napi arany ~2% -> ~10% a 10-12-i Sonnet 5.5
valtas utan (53 eset 10 nap alatt). Harom reteg:
  1) az elozo kor adat-blokkjai (AKTUALIS TERMEK / TUDASBAZIS / WEBSHOP KERESO / ELO AR)
     Redisben a sessionhoz; a kovetkezo korben # ELOZO KOR ADATAI blokkban visszakerulnek;
  2) rendszer-teny (NOTE): korabbi valaszt csak akkor javits, ha a mostani adat ellentmond;
  3) kod-orseg: ha a kimenet megis visszavonast tartalmaz (es a latogato nem jelezte, hogy
     valami nem stimmel) -> egyszeri regen HINT-tel.
A m77 'pontositod' mondat csak az ar-szuperlativusz modokban marad (oos_guard-ban nem).
Stdlib-only (a redis-kliens parameterkent jon) -> tesztelheto.
"""
import re

# a visszavonas-minta (a d21b meres UGYANEZT a mintat hasznalja elotte/utana)
RX = re.compile(
    r"(pontos[ií]tanom kell|helyesb[ií]t|t[eé]vesen (írtam|irtam|mondtam|adtam|jeleztem)"
    r"|korábbi (válaszom|üzenetem|információm)|el[őo]z[őo] (válaszom|üzenetem)"
    r"|ne vedd figyelembe|f[eé]lrevezet[őo] volt|visszavonom|t[eé]vedtem"
    r"|hib[aá]san (írtam|adtam|jeleztem))",
    re.I,
)

# a latogato maga jelzi, hogy valami nem stimmel -> a javitas legitim, az orseg nem lep kozbe
_DISPUTE = re.compile(
    r"(nem igaz|nem j[oó]\b|nem stimmel|t[eé]vedsz|t[eé]vedt[eé]l|rosszul|rossz\b|hib[aá]s"
    r"|nincs ott|nem (ez|az)\b|nem ezt|nem azt|ellentmond|m[aá]st [ií]rt)",
    re.I,
)

_DATA_SECTIONS = ("# AKTUALIS TERMEK", "# TUDASBAZIS", "# WEBSHOP KERESO TALALATAI", "# ELO, FRISS AR")
_EMPTY_KB = "(nincs talalat a tudasbazisban)"
MAX_CHARS = 12000  # ~3,5k token; d21b replay: elozo kor adata atlag ~15k kar
TTL_SECONDS = 6 * 3600

# m77 eredeti szovege (chat.py-bol athozva, valtozatlanul)
_M77 = (
    " FIGYELEM: ha a beszelgetes korabbi valaszaiban mas termeket neveztel a"
    " legolcsobbnak/legjobbnak, az a valasz ELAVULT. Kizarolag a MOSTANI"
    " # TUDASBAZIS talalataibol valassz, akkor is, ha ez ellentmond a korabbi"
    " valaszodnak, es roviden jelezd, hogy pontositod a korabbi informaciot."
)

NOTE = (
    "\n\n# KORABBI VALASZAID (rendszer-teny, igaz)\n"
    "A beszelgetes korabbi valaszait a bolt akkori, ellenorzott adataibol irtad. Ne vond vissza, "
    "ne 'pontositsd' es ne nyilvanitsd bizonytalannak oket csak azert, mert a mostani "
    "# TUDASBAZIS-ban nem latod oket: a kontextus minden korben a kinalat mas szeletet mutatja. "
    "Ne kezdd a valaszt a korabbi valasz helyesbitesevel, es ne irj olyat, hogy \"ne vedd "
    "figyelembe\" vagy \"nem tudom megerositeni, amit korabban irtam\". Korabbi allitast csak akkor "
    "javits, ha a MOSTANI adatok szo szerint mast mondanak (pl. mas ar vagy dij), vagy a latogato "
    "jelzi, hogy valami nem stimmel; ilyenkor egy mondatban, konkretan (mi volt, mi a helyes)."
)

HINT = (
    "\n\n# GUARD - KORABBI VALASZ (determinisztikus szabaly)\n"
    "A valaszvazlatod visszavont vagy 'pontositott' egy korabbi valaszt. Ezt ne tedd: valaszolj a "
    "latogato MOSTANI uzenetere ugy, hogy a korabbi valaszaidat nem minosited, nem vonod vissza es "
    "nem helyesbited. Kivetel: ha a # TUDASBAZIS, az # AKTUALIS TERMEK vagy az # ELOZO KOR ADATAI "
    "szo szerint mas erteket ad (ar, dij), azt egy mondatban, konkretan javitsd. Udvariassagi "
    "uzenetre (koszonom, rendben) roviden reagalj."
)


def is_retraction(text) -> bool:
    return bool(RX.search(str(text or "")))


def user_disputes(message) -> bool:
    return bool(_DISPUTE.search(str(message or "")))


def _role(h):
    v = getattr(h, "role", None)
    if v is None and isinstance(h, dict):
        v = h.get("role")
    return str(v or "")


def has_assistant(history) -> bool:
    return any(_role(h) == "assistant" for h in (history or []))


def extract_data(dynamic) -> str:
    """A dinamikus system-reszbol az adat-blokkok (termek, tudasbazis, kereso, elo ar)."""
    parts = re.split(r"\n\n(?=# )", str(dynamic or ""))
    keep = []
    for p in parts:
        s = p.strip()
        if s.startswith(_DATA_SECTIONS) and _EMPTY_KB not in s:
            keep.append(s)
    return "\n\n".join(keep)


def merge(cur: str, prev: str, limit: int = MAX_CHARS) -> str:
    """Gordulo tar: a mostani kor adata elol, mogotte a korabbi (ha nem azonos), limitre vagva."""
    cur = str(cur or "").strip()
    prev = str(prev or "").strip()
    out = cur
    if prev and prev != cur and prev not in cur:
        out = (cur + "\n\n" + prev) if cur else prev
    return out[:limit]


def _key(client_id, session_id) -> str:
    return "cx:m125:prev:%s:%s" % (client_id, session_id)


async def load_prev(redis, client_id, session_id) -> str:
    if not session_id or redis is None:
        return ""
    try:
        v = await redis.get(_key(client_id, session_id))
        return str(v or "")
    except Exception:  # noqa: BLE001 - a Redis-hiba ne torje a chatet
        return ""


async def save(redis, client_id, session_id, cur: str, prev: str) -> None:
    if not session_id or redis is None:
        return
    val = merge(cur, prev)
    if not val:
        return
    try:
        await redis.set(_key(client_id, session_id), val, ex=TTL_SECONDS)
    except Exception:  # noqa: BLE001
        pass


def prev_block(prev) -> str:
    prev = str(prev or "").strip()
    if not prev:
        return ""
    return (
        "\n\n# ELOZO KOR ADATAI (rendszer-teny)\n"
        "Az alabbi adatokat a beszelgetes korabbi koreiben kaptad a bolt rendszerebol; a korabbi "
        "valaszaid ezekre epultek. Ha a latogato korabban emlitett termekre vagy adatra hivatkozik "
        "(\"az elso\", \"ez\", ar, dij, fizetesi mod, cim), ezekbol is valaszolhatsz. Ha egy termek "
        "a mostani # TUDASBAZIS-ban vagy # AKTUALIS TERMEK-ben is szerepel, ar es keszlet "
        "tekinteteben a mostani adat az elsobb.\n" + prev
    )


def retrieval_note(rmode, note, has_history) -> str:
    """m77 mondat csak az ar-szuperlativusz modokban (oos_guard-ban nem)."""
    note = note or ""
    if has_history and note and str(rmode or "") != "oos_guard":
        return note + _M77
    return note

"""Policy-témájú lekérdezés felismerése + a termék-zaj kiszűrése (m34). PURE modul.

Probléma: garancia/szállítás/elállás-kérdésnél a Qdrant a 12 800 termék közül is
behoz olyanokat, amelyek NEVÉBEN ott a "3 ev garancia" — a modell ezekből a
terméknevekből általánosít a boltra ("a Dell-gepek 3 ev garanciaval jonnek"),
hiaba tiltja a factuality-blokk. Egy LLM nem tud legyozni egy ugyben jelenlevo
adatmintat pusztan utasitassal.

Megoldas: ha a kerdes POLICY-temaju (altalanos bolti feltetel) ES van eleg
NEM-termek (doksi/KB) talalat, akkor a rerank utan eldobjuk a termek-chunkokat.
Igy a modell csak a hivatalos KB-szoveget latja, a termekneveket nem.

Ha nincs policy-talalat (a tenant nem toltott fel ilyen doksit), a termekeket
MEGTARTJUK — jobb valami kontextus, mint semmi, es a factuality-blokk ugyis tiltja
a talalgatast.
"""

import re
import unicodedata

# Policy-kulcsszavak (ekezet-mentesitett alakon). Ezek a bolt ALTALANOS felteteleire
# vonatkoznak — nem egy konkret termek tulajdonsagara.
_POLICY_RE = re.compile(
    r"garanci|jotall|szavatoss|szallit|kiszallit|hazhozszallit|futar|foxpost|csomagpont|"
    r"elall|visszakuld|visszaterit|penzvisszafizet|csere\b|reklamaci|panasz|"
    r"fizet|utanvet|atutalas|bankkartya|reszletfizet|torlesztes|"
    r"aszf|vasarlasi feltetel|szallitasi hatarido|szallitasi dij|adatkezel|adatvedelem"
)


def fold(s: str) -> str:
    s = str(s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def is_policy_query(message: str) -> bool:
    """A kerdes a bolt ALTALANOS felteteleire vonatkozik-e (nem egy termekre)."""
    return bool(_POLICY_RE.search(fold(message)))


# A beagyazando query dusitasa policy-kerdesnel. A rovid "garancia" query embeddingje a
# termeknevekhez ("...3 ev garancia...") huz; ezekkel a szavakkal a dense kereses a
# HIVATALOS KB-szoveg (ASZF/jotallas/elallas) fele billen. A prod meresen: "garancia" -> 0
# doksi a top-24-ben, "garancia jotallas elallas szallitas" -> 4 doksi jo score-ral.
_POLICY_EXPANSION = " garancia jotallas szavatossag elallas szallitas fizetes vasarlasi feltetelek aszf"


def policy_embed_input(message: str, embed_input: str) -> str:
    """Policy-kerdesnel a beagyazando szoveget policy-kulcsszavakkal dusitjuk. PURE.

    Nem policy-kerdes -> valtozatlan embed_input.
    """
    if not is_policy_query(message):
        return embed_input
    return (embed_input or message) + _POLICY_EXPANSION


def _is_product(hit: dict) -> bool:
    """Termek-e a talalat. A payload.type=='product', VAGY van nem-ures sku."""
    p = hit.get("payload", hit) if isinstance(hit, dict) else {}
    if str(p.get("type") or "").lower() == "product":
        return True
    return bool(str(p.get("sku") or "").strip())


def filter_for_policy(message: str, hits: list[dict], min_docs: int = 1) -> list[dict]:
    """Policy-kerdesnel a termek-chunkokat kiszurjuk, HA van eleg doksi-talalat.

    - nem policy-kerdes -> valtozatlan lista
    - policy-kerdes, 0 doksi -> valtozatlan (a tenant nem toltott KB-t; factuality tilt)
    - policy-kerdes, >= min_docs (alap 1) doksi -> CSAK a doksi-chunkok
    """
    if not is_policy_query(message):
        return hits
    docs = [h for h in hits if not _is_product(h)]
    if len(docs) < min_docs:
        return hits
    return docs

"""Ar-szuperlativusz kerdesek ("legolcsobb", "legdragabb") kezelese (m38). PURE modul.

A dense kereses TEMARA talal, de arat nem rendez: a modell a veletlenszeru top-8
legolcsobbjat mondja "a legolcsobbnak", es a kovetkezo korben (mas top-8) ellentmond
onmaganak (eles eset, notebookstore: 246 990 -> 144 990 "legolcsobb").

Szuperlativusz-kerdesnel ezert:
  1) SZELESEBB dense poolt kerunk (topikalisan relevans termekek),
  2) a rerank relevancia-sorrendje HELYETT determinisztikusan ar szerint rendezunk.

FONTOS: a nev-alapu szures NEM jo ut — a "notebook" nevre a 890 Ft-os NOTEBOOK
TAPKABEL lenne a "legolcsobb laptop". A dense pool viszont csak valodi gepeket hoz
(merve: mindket eles kor poolja 8/8 laptop volt).
"""

from __future__ import annotations

import re
import unicodedata

# szelesebb pool szuperlativusz-kerdesnel (a 24 helyett)
WIDE_LIMIT = 120

_ASC_RE = re.compile(r"legolcsobb|legkedvezobb\s+ar|legalacsonyabb\s+ar|legjobb\s+ar")
_DESC_RE = re.compile(r"legdragabb|legmagasabb\s+ar")


def fold(s: str) -> str:
    s = str(s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def detect_price_superlative(message: str) -> str | None:
    """'asc' (legolcsobb...) | 'desc' (legdragabb...) | None.

    A kozepfok ("olcsobban", "dragabb-e") NEM szuperlativusz — arra a normal
    relevancia-rangsor a helyes.
    """
    a = fold(message)
    if _ASC_RE.search(a):
        return "asc"
    if _DESC_RE.search(a):
        return "desc"
    return None


def _is_product(hit: dict) -> bool:
    p = hit.get("payload", hit) if isinstance(hit, dict) else {}
    if str(p.get("type") or "").lower() == "product":
        return True
    return bool(str(p.get("sku") or "").strip())


def _price(hit: dict) -> float | None:
    p = hit.get("payload", hit) if isinstance(hit, dict) else {}
    raw = str(p.get("price") or "").replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def sort_by_price(hits: list[dict], direction: str, top_n: int) -> list[dict]:
    """A poolbol az arazott TERMEKEK ar szerint rendezve, top_n.

    Ha 3-nal kevesebb arazott termek van, ures listat adunk vissza — a hivo ilyenkor
    a normal rerank-agra esik vissza (nincs mibol megbizhatoan rendezni).
    """
    priced: list[tuple[float, dict]] = []
    for h in hits:
        if not _is_product(h):
            continue
        p = _price(h)
        if p is not None:
            priced.append((p, h))
    if len(priced) < 3:
        return []
    priced.sort(key=lambda t: t[0], reverse=(direction == "desc"))
    return [h for _, h in priced[:top_n]]

def price_context(hits: list[dict], direction: str, top_n: int) -> list[dict]:
    """m40: ar-szuperlativusz kontextus -- fele ar-veg, fele tema-relevancia.

    A tiszta ar-rendezes (sort_by_price) a topikalisan SZELES poolon a legolcsobb
    KIEGESZITOKET hozza (copygo eles eset, 2026-07-14: a "legolcsobb fotonyomtato"
    top-8-a 8/8 utangyartott tintapatron volt, egyetlen fotonyomtato sem -- a modell
    factuality-helyesen "nem tudom"-ot mondott). Score-floor nem valaszt szet
    (meres: Selphy CP1500 0.444 < MINOLTA toner 0.453), ezert a kontextus ket
    determinisztikus felbol all:
      1) az ar szerinti veg (asc/desc) -- a "legolcsobb/legdragabb" horgony,
      2) a tema legerosebb (score szerinti) termekei -- a valodi jeloltek.
    A modell a kerdezett termektipusra valaszol, a kiegeszitoket atugorja
    (m39 eles tapasztalat), HA a valodi jeloltek is a kontextusban vannak.

    3-nal kevesebb arazott termeknel tovabbra is ures lista -- a hivo a normal
    rerank-agra esik vissza.
    """
    priced: list[tuple[float, dict]] = []
    for h in hits:
        if not _is_product(h):
            continue
        p = _price(h)
        if p is not None:
            priced.append((p, h))
    if len(priced) < 3:
        return []
    by_price = [h for _, h in sorted(priced, key=lambda t: t[0], reverse=(direction == "desc"))]
    by_score = sorted(
        (h for _, h in priced), key=lambda h: float(h.get("score") or 0.0), reverse=True
    )

    def _key(h: dict):
        k = h.get("id")
        if k is not None:
            return ("id", str(k))
        pl = h.get("payload", {}) or {}
        return ("nu", str(pl.get("name") or ""), str(pl.get("url") or ""))

    n_price = max(1, (top_n + 1) // 2)
    out: list[dict] = []
    seen: set = set()
    for h in by_price[:n_price]:
        k = _key(h)
        if k not in seen:
            seen.add(k)
            out.append(h)
    for h in by_score:
        if len(out) >= top_n:
            break
        k = _key(h)
        if k not in seen:
            seen.add(k)
            out.append(h)
    for h in by_price[n_price:]:
        if len(out) >= top_n:
            break
        k = _key(h)
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out


_TOPIC_STOP = {
    "mennyi", "mennyibe", "melyik", "mi", "mik", "mit", "es", "a", "az", "ti",
    "nalatok", "nalunk", "most", "jelenleg", "van", "vane", "kaphato", "kerul",
    "ara", "aru", "arban", "arert",
}
_SUPER_RE = re.compile(r"legolcsobb|legdragabb|legkedvezobb|legalacsonyabb|legmagasabb|legjobb")


def topic_of(message: str) -> str:
    """A szuperlativusz-kerdes TEMAJA ('mennyi a legolcsobb laptop nalatok?' -> 'laptop').

    A tema-embed KOR-FUGGETLEN: az elso es a folytato kerdes ('es a legolcsobb laptop?')
    ugyanazt a vektort kapja -> ugyanaz a pool -> ugyanaz a legkedvezobb aru termek.
    Ures tema (pl. 'es a legolcsobb?') eseten a hivo a normal embed-utra esik vissza.
    """
    out: list[str] = []
    for tok in str(message or "").split():
        f = fold(tok).strip(".,;:!?()\"'")
        if not f or _SUPER_RE.search(f) or f in _TOPIC_STOP:
            continue
        if re.fullmatch(r"[\W_]+", f):
            continue
        out.append(tok.strip(".,;:!?()\"'"))
    return " ".join(out)

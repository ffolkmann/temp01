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

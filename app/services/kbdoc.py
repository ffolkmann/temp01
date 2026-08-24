"""m93: KB-dokumentum visszaolvasás letöltéshez.

Két forrás:
  1. az ingest által lemezre mentett EREDETI fájl (bitre pontos),
  2. ha az nincs (régi feltöltés), a Qdrant-chunkok összefűzése.

Stdlib-only és fájl-betölthető (spec_from_file_location), mert a suite más
tesztjei fake ``app.services`` csomagot hagynak a sys.modules-ben — kf/13,
m80b és m89 tanulsága.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any

CHUNK = 1000          # az ingest _CHUNK-jával AZONOS; ha ott változik, itt is kell
KB_DIR = "/app/data/kb"

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: Any) -> str:
    """Lemezre írható, útvonal-bejárás ellen védett név."""
    base = os.path.basename(str(name or "")).strip()
    base = base.replace("..", "_")
    base = _SAFE_RE.sub("_", base)
    base = base.strip("._-")
    return (base or "doc")[:120]


def disk_name(filename: Any) -> str:
    """A lemezen használt fájlnév.

    A ``safe_name`` az ékezeteket aláhúzásra cseréli, ezért két különböző
    dokumentum ("árazás.txt" és "arazas.txt") ugyanarra a névre esne, és az
    egyik felülírná a másikat. Ezért az EREDETI név hash-e is bekerül a
    névbe: ütközésmentes, determinisztikus, és olvasható marad.
    """
    raw = str(filename or "")
    h = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:12]
    return h + "__" + safe_name(raw)


def original_path(client_id: Any, filename: Any, base: str = KB_DIR) -> str:
    return os.path.join(base, safe_name(client_id), disk_name(filename))


def write_original(client_id: Any, filename: Any, raw: bytes, base: str = KB_DIR) -> str:
    """Az eredeti feltöltött fájl elmentése. Hibát dob, a hívó nyeli le."""
    d = os.path.join(base, safe_name(client_id))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, disk_name(filename))
    with open(p, "wb") as fh:
        fh.write(raw)
    return p


def read_original(client_id: Any, filename: Any, base: str = KB_DIR) -> str | None:
    """Az elmentett eredeti szövege, vagy None, ha nincs ilyen fájl."""
    try:
        with open(original_path(client_id, filename, base), "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    for enc in ("utf-8", "cp1250", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def delete_original(client_id: Any, filename: Any, base: str = KB_DIR) -> bool:
    try:
        os.remove(original_path(client_id, filename, base))
        return True
    except OSError:
        return False


def join_chunks(points: Any, chunk: int = CHUNK) -> str:
    """Qdrant chunk-pontokból (payload: idx, text) visszaállított szöveg.

    Az ingest minden `chunk` hosszú szeletre ``.strip()``-et hív, ezért a
    szelet-határokon elveszhet egy-egy szóköz vagy sortörés. Ezt a HOSSZBÓL
    következtetjük ki: egy PONTOSAN `chunk` hosszú szeletről a strip semmit
    nem vágott le, tehát ott nem hiányzik elválasztó. Ha bármelyik oldal
    rövidebb, egy "\\n"-t teszünk vissza.

    A szabály iránya tudatos: így soha nem ragasztunk össze két szót
    (az néma hiba lenne), legrosszabb esetben egy fölösleges sortörés kerül
    a szövegbe — az látszik, és szerkesztéskor egy mozdulat javítani.
    """
    rows: list[tuple[int, str]] = []
    for p in points or []:
        if not isinstance(p, dict):
            continue
        pay = p.get("payload") or {}
        if not isinstance(pay, dict):
            continue
        txt = pay.get("text")
        if not isinstance(txt, str) or not txt:
            continue
        try:
            idx = int(pay.get("idx"))
        except (TypeError, ValueError):
            idx = len(rows)
        rows.append((idx, txt))
    if not rows:
        return ""
    rows.sort(key=lambda r: r[0])
    texts = [t for _, t in rows]
    out: list[str] = [texts[0]]
    last = len(texts) - 1
    for i in range(1, len(texts)):
        prev, nxt = texts[i - 1], texts[i]
        need_sep = len(prev) < chunk or (i != last and len(nxt) < chunk)
        out.append("\n" if need_sep else "")
        out.append(nxt)
    return "".join(out)

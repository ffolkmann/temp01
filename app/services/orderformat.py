"""m128 (K4): rendelesszam-ALAK orseg a rendeles-lekeres elott.

Mert lelet (d21d, events.order_lookup, 90 nap): 535 lekeresbol 57 nem matched, es a nem
matched rendelesszamok ~60%-a mar ALAKRA sem rendelesszam a boltnal (4 jegyu / 7 jegyu
GLS-csomagszam / csonka "21196" / telefonszam-darab / "2018-2024" evszam / iranyitoszam) -
megis a "ha tartozik hozza rendeles, elkuldtuk" sablon ment ki, a vevo a postafiokjat
nezte, es volt, aki 3 sessionen at probalkozott ugyanazzal a rossz szammal.

A bolt rendelesszam-alakja TENANTONKENT stabil es az adatbol tanulhato (matched lekeresek
az events tablabol): copygo / fishingoutlet / nagyonallatshop 99999, kellegyszerszam
21196-999999 (Unas: bolt-azonosito + kotojel + sorszam), notebookstore 2026/9999999 vagy
#9999999. Nem kodolunk tenantot: a modul a tenant SAJAT matched rendelesszamaibol epit
alak-listat (>= _MIN_SAMPLES minta, 1 h cache, fail-open = nincs orseg).

Harom szabaly (pure, teszthelto):
  - OK:       a szam alakja (jegyszam + elvalasztok) egy ismert alak; VAGY csupa szam es
              PONTOSAN eggyel hosszabb egy ismert csupa-szam alaknal (a sorszam atlepheti a
              99999-et - kulonben az uj hosszt sosem tanulna meg, mert a lekeres elmaradna);
              a prefix (2026/, 21196-) itt NEM feltetel (evvaltas / bolt-azonosito).
  - FIX:      prefixes alak (21196-999999) es a vevo elvalaszto nelkul irta a teljes szamot
              ("21196123172") -> elvalasztos alak, a lekeres azzal megy.
  - MISMATCH: minden mas -> NINCS API-hivas, format-tipp a valaszban (pelda-alak, hol talalja).
A chat.py a 2. sikertelen probalkozasnal (rate-limit szamlalo) lead-ajanlatot fuz a
valaszhoz (action=collect_lead) - "ket sikertelen proba utan lead vagy atadas" (audit K4).
"""
from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger("cx.orderformat")

_MIN_SAMPLES = 5          # ennyi matched rendelesszam alatt nincs orseg
_MIN_SHAPE_SAMPLES = 3    # egy alak ennyi mintatol szamit ismertnek
_TTL = 3600.0
_cache: dict = {}         # client_id -> (monotonic, [(shape, prefix, n), ...])


def shape_of(order_id: str) -> str:
    """'21196-123172' -> '99999-999999'; '2026/0050954' -> '9999/9999999'; '#58344' -> '99999'."""
    s = str(order_id or "").strip().lstrip("#").strip()
    return re.sub(r"[0-9]", "9", s)


def _common_prefix(ids: list) -> str:
    if not ids:
        return ""
    p = ids[0]
    for s in ids[1:]:
        i = 0
        while i < min(len(p), len(s)) and p[i] == s[i]:
            i += 1
        p = p[:i]
        if not p:
            break
    return p


def learn_shapes(matched_ids: list) -> list:
    """Pure: a matched rendelesszamokbol [(shape, prefix, n), ...] - csak a >= _MIN_SHAPE_SAMPLES
    alakok; a prefix az alak mintainak kozos szam-elotagja, ha az pont az elvalaszto ELOTTI
    teljes szamcsoport (Unas '21196-', Webdoc '2026/'), kulonben ''. Gyakorisag szerint."""
    ids = [str(x or "").strip().lstrip("#").strip() for x in matched_ids or []]
    ids = [x for x in ids if x]
    if len(ids) < _MIN_SAMPLES:
        return []
    groups: dict = {}
    for x in ids:
        groups.setdefault(shape_of(x), []).append(x)
    out = []
    for sh, members in groups.items():
        if len(members) < _MIN_SHAPE_SAMPLES:
            continue
        prefix = ""
        m = re.match(r"^(9+)([-/])", sh)
        if m:
            cp = _common_prefix([x.split(m.group(2), 1)[0] for x in members])
            if cp and len(cp) == len(m.group(1)):
                prefix = cp
        out.append((sh, prefix, len(members)))
    out.sort(key=lambda t: -t[2])
    return out


def check(order_id: str, shapes: list, platform: str = "") -> tuple:
    """Pure: -> ('ok', id) | ('fix', javitott_id) | ('mismatch', id). shapes: learn_shapes() kimenete.
    Ures shapes vagy ures id -> 'ok' (fail-open). Webdoc: a rendeles-API a sorszambol szamol
    ('2026/0050954' es '#50954' is jo), ezert ott CSAK a <= 4 jegyu csupa szam (irsz, ev) rossz alak."""
    raw = str(order_id or "").strip().lstrip("#").strip()
    if not shapes or not raw:
        return "ok", raw
    if str(platform or "").strip().lower() == "webdoc":
        return ("mismatch", raw) if (raw.isdigit() and len(raw) <= 4) else ("ok", raw)
    sh = shape_of(raw)
    for s, _prefix, _n in shapes:
        if sh == s:
            return "ok", raw
        # a sorszam atlephet egy nagysagrendet (99999 -> 100000): +1 jegy meg atmegy az API-ra
        if raw.isdigit() and s.isdigit() and len(raw) == len(s) + 1:
            return "ok", raw
    if raw.isdigit():  # FIX: elvalaszto nelkul irt teljes szam egy elvalasztos alakhoz
        for s, prefix, _n in shapes:
            m = re.match(r"^(9+)([-/])(9+)$", s)
            if not m:
                continue
            a, sep, b = len(m.group(1)), m.group(2), len(m.group(3))
            if len(raw) == a + b and (not prefix or raw.startswith(prefix)):
                return "fix", raw[:a] + sep + raw[a:]
    return "mismatch", raw


def example(shapes: list) -> str:
    """A leggyakoribb alak pelda-formaban: '99999' -> 'xxxxx (5 számjegy)';
    ('99999-999999', '21196') -> '21196-xxxxxx'; ('9999/9999999', '2026') -> '2026/xxxxxxx'."""
    if not shapes:
        return ""
    sh, prefix, _n = shapes[0]
    ex = prefix + sh[len(prefix):].replace("9", "x")  # a prefix szamjegyei maradnak (21196-xxxxxx)
    if re.fullmatch(r"x+", ex):
        return "%s (%d számjegy)" % (ex, len(ex))
    return ex


def mismatch_reply(order_id: str, shapes: list) -> str:
    ex = example(shapes)
    oid = str(order_id or "").strip()
    head = ("A megadott szám (%s) nem a webáruházunk rendelésszám-alakja" % oid) if oid else \
        "A megadott szám nem a webáruházunk rendelésszám-alakja"
    hint = (" — nálunk a rendelésszám így néz ki: %s." % ex) if ex else "."
    return (head + hint +
            " A rendelésszámot a rendelés visszaigazoló e-mailjében találod (a tárgyban vagy a levél elején). "
            "Kérlek, add meg újra a rendelésszámot és a rendeléskor használt e-mail-címet.")


LEAD_OFFER = (
    " Ha így sem sikerül, ne akadj el ezen: add meg az elérhetőséged, és kollégánk "
    "megkeresi a rendelést és felveszi veled a kapcsolatot."
)


async def shapes_for(session, client_id: str) -> list:
    """A tenant matched rendelesszam-alakjai az events tablabol (180 nap, max 500), 1 h cache.
    Barmely hiba -> [] (fail-open, nincs orseg)."""
    hit = _cache.get(client_id)
    if hit and (time.monotonic() - hit[0]) < _TTL:
        return hit[1]
    shapes: list = []
    try:
        from sqlalchemy import text
        rows = (await session.execute(text(
            "SELECT meta->>'order_id' FROM events WHERE client_id = :c AND kind = 'order_lookup' "
            "AND (meta->>'matched') = 'true' AND created_at > now() - interval '180 days' "
            "ORDER BY created_at DESC LIMIT 500"), {"c": client_id})).scalars().all()
        shapes = learn_shapes([str(r) for r in rows if r])
    except Exception:  # noqa: BLE001 - az orseg hibaja sose torje a rendeles-agat
        logger.exception("m128 orderformat: alak-betoltes hiba client=%s", client_id)
        shapes = []
    _cache[client_id] = (time.monotonic(), shapes)
    return shapes

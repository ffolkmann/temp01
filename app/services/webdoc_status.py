"""Webdoc (WebDoc API v1.1) rendelés-státusz — kódszótár + pure segédek.

A WebDoc API kizárólag numerikus kódokat ad vissza (`status.id`, `shipping.id`,
`payment.id`), megnevezést nem. A neveket a tenant `order_status_map` JSONB-je
adja; ami ott nincs, arra a DEFAULT_STATUS_MAP ugrik be (a szállító OpenAPI
leírójából, 2026-07-09-i állapot).

Azonosítás — RENDELÉSSZÁM + IRÁNYÍTÓSZÁM:
A WebDoc API a `customer.email` és `customer.phone` mezőket üresen adja vissza,
így e-mailre nem lehet párosítani (a többi platformon az a guard). Helyette az
irányítószám a másodlagos titok. A szállítási cím irányítószáma 110 éles
rendelésből 75-ben van kitöltve (a többi személyes átvét / csomagpont), a
számlázási cím irányítószáma viszont 100%-ban — ezért BÁRMELYIK egyezése match.

Rendelésszám -> id:
A `number` formátuma `ÉÉÉÉ/0000000`, és az utolsó szegmens int-je pontosan az
API `id`-je (`2026/0047322` -> 47322). 110 éles rendelésen igazolva.

FIGYELEM — adat-minimalizálás:
A `/orders` válasz nevet, teljes címet, telefonszámot, adószámot és számlázási
nevet is tartalmaz. Ez a modul EZEKET SOHA nem olvassa ki és nem adja tovább;
az irányítószám is csak összehasonlításra szolgál, sosem kerül a válaszba.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from app.models.db_models import Tenant

# A szállító OpenAPI leírójából (api-v1.1.json, description mezők).
# A shipping 6/7/8 kódok ÉLESBEN előfordulnak, de a doksiban nincsenek — ezekre
# a bot nem mond szállítási módot (lásd pick_shipping); adminból pótolható.
DEFAULT_STATUS_MAP: dict[str, dict[str, str]] = {
    "status": {
        "1": "Rendelés megérkezett",
        "2": "Visszaigazolva",
        "3": "Feldolgozás alatt",
        "4": "Személyesen átvehető / Raktárról kiadva",
        "5": "Lezárva",
        "6": "Törölve",
    },
    "shipping": {
        "1": "Házhozszállítás",
        "2": "Személyes átvétel",
        "3": "Pick-Pack pont",
        "4": "FoxPost",
        "5": "GLS Csomagpont",
    },
    "payment": {
        "1": "Utánvét (készpénz)",
        "2": "Készpénz",
        "3": "Előre utalás",
        "4": "Bankkártya (online)",
        "5": "Utánvét (bankkártya)",
        "6": "Átutalás",
    },
    "payment_paid": {
        "0": "nincs fizetve",
        "1": "fizetve",
    },
}

_NUMBER_RE = re.compile(r"^\s*#?\s*(?:\d{4}\s*/\s*)?(\d{1,9})\s*$")
_ZIP_RE = re.compile(r"^\d{4}$")


def status_maps(tenant: "Tenant | None") -> dict[str, dict[str, str]]:
    """A tenant felülírásai a DEFAULT fölé (szekciónként merge-elve, nem cserélve).

    A tenant-map értékei nyernek; a hiányzó szekciók/kulcsok a defaultból jönnek.
    Bármely hibás alak (nem dict) -> a default marad. Nem dob.
    """
    out = {k: dict(v) for k, v in DEFAULT_STATUS_MAP.items()}
    raw = getattr(tenant, "order_status_map", None) if tenant is not None else None
    if not isinstance(raw, dict):
        return out
    for section, mapping in raw.items():
        if not isinstance(mapping, dict):
            continue
        dst = out.setdefault(str(section), {})
        for code, name in mapping.items():
            if isinstance(name, str) and name.strip():
                dst[str(code).strip()] = name.strip()
    return out


def parse_order_number(raw: str) -> int | None:
    """`2026/0047322` | `#47322` | `47322` -> 47322. Érvénytelen alak -> None.

    A `/` előtti év-szegmenst eldobjuk: az API `id`-je a mögötte álló sorszám.
    """
    m = _NUMBER_RE.match(str(raw or ""))
    if not m:
        return None
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 1_000_000_000 else None


def normalize_zip(raw: Any) -> str:
    """4 jegyű magyar irányítószám str-ként; minden más -> ''. (int és str is jöhet.)"""
    s = str(raw if raw is not None else "").strip()
    return s if _ZIP_RE.match(s) else ""


def _dig(o: Any, *keys: str) -> Any:
    cur = o
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def order_zips(order: dict) -> list[str]:
    """A rendeléshez tartozó elfogadható irányítószámok (szállítási + számlázási).

    Csak összehasonlításra! Az érték soha nem kerül a vásárlónak adott válaszba.
    """
    out: list[str] = []
    for path in (
        ("shipping", "delivery", "address", "zip"),
        ("payment", "billing", "address", "zip"),
    ):
        z = normalize_zip(_dig(order, *path))
        if z and z not in out:
            out.append(z)
    return out


def zip_matches(order: dict, want_zip: str) -> bool:
    """A megadott irsz egyezik-e a szállítási VAGY a számlázási irányítószámmal.

    Üres/érvénytelen bemenet -> False (fail-closed: inkább ne adjunk ki adatot).
    """
    want = normalize_zip(want_zip)
    if not want:
        return False
    return want in order_zips(order)


def _code(v: Any) -> str:
    """A kód str-alakja (`1` és `"1"` és `1.0` is `"1"`)."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    s = str(v if v is not None else "").strip()
    return s


def pick_status(order: dict, maps: dict) -> tuple[str, str]:
    """(státusznév, státusz-időpont). Ismeretlen kód -> ('', dt) — SOHA nem 'ismeretlen'.

    A hívó úgy dönt, mit mond, ha a név üres (a projekt szabálya: nyers kód és az
    'ismeretlen' szó sem mehet ki a vásárlónak).
    """
    code = _code(_dig(order, "status", "id"))
    name = (maps.get("status") or {}).get(code, "")
    dt = str(_dig(order, "status", "dateTime") or "").strip()
    return name, dt


def pick_shipping(order: dict, maps: dict) -> str:
    """Szállítási mód neve, vagy '' ha a kód nincs a szótárban (pl. a doksiból hiányzó 6/7/8)."""
    code = _code(_dig(order, "shipping", "id"))
    return (maps.get("shipping") or {}).get(code, "")


def pick_payment(order: dict, maps: dict) -> str:
    """`Bankkártya (online) – fizetve` alak; ismeretlen fizetési mód -> csak a fizetettség.

    Ha egyik sem ismert -> ''.
    """
    code = _code(_dig(order, "payment", "id"))
    mode = (maps.get("payment") or {}).get(code, "")
    paid_code = _code(_dig(order, "payment", "status"))
    paid = (maps.get("payment_paid") or {}).get(paid_code, "")
    if mode and paid:
        return f"{mode} – {paid}"
    return mode or paid or ""


def pick_items(order: dict) -> list[tuple[str, str]]:
    """items[] -> [(név, mennyiség)]. Csak a tétel NEVE és darabszáma — ár nem."""
    out: list[tuple[str, str]] = []
    items = order.get("items") if isinstance(order, dict) else None
    for it in (items or [])[:20]:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        out.append((name, _code(it.get("quantity"))))
    return out


def first_order(payload: Any) -> dict | None:
    """A `/orders?id=` válasza lehet lista vagy csupasz objektum — az elsőt adja.

    Üres lista / hibás alak -> None.
    """
    if isinstance(payload, dict):
        if payload.get("id") is not None:
            return payload
        for key in ("orders", "data", "items"):
            v = payload.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v[0]
            if isinstance(v, dict) and v.get("id") is not None:
                return v
        return None
    if isinstance(payload, list):
        for o in payload:
            if isinstance(o, dict) and o.get("id") is not None:
                return o
    return None

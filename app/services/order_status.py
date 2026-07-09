"""Rendelés-státusz ág — platform szerinti order-lekérés + semleges válasz + e-mail.

A prod Chat workflow "platform order-lekérés -> Verify Order -> Send Status Email"
ágának portja. Platformok: Sellvio (eredeti), Shoprenter, Unas, WooCommerce.
A közös auth/XML primitívek a platform_api.py-ben (live_product.py is osztja).

Adatvédelem: a /chat VÁLASZ matched ÉS nem-matched esetben is UGYANAZ a semleges
szöveg, hogy ne szivárogjon rendelési adat. A státusz csak e-mailben megy a
rendeléskor használt címre, háttérben (schedule_email). Bármely hiba -> semleges
válasz + log, SOHA nem dob a widget felé.

API-kontraktusok (VPS-en igazolt / web):
 - Sellvio:     OAuth, GET /api/v2/orders/ (locale=hu, lapozva a legfrissebbtől); nincs
                igazolt szerver-oldali id/email szűrő -> kliens-oldali match (id ÉS email),
                order_items + delivery_type/deliveries a tétel/szállítás jegyzethez.
 - WooCommerce: GET {base}/wp-json/wc/v3/orders/{id}, Basic (ck/cs), billing.email + status.
 - Shoprenter:  OAuth2, GET {api_base}/orders/{base64('order-order_id=<N>')}; az api2 csupasz
                top-level objektumot ad (email top-level); a status href-dict -> guard + generikus.
 - Unas:        login(ApiKey)->Token, POST /getOrder XML Bearer, Order <Status> + <Email> +
                Items/Item (Name/Quantity) + Delivery (tétel/szállítás jegyzethez).

A lookupok (bool matched, str status, str note) hármast adnak: a note a matched
chat-válaszba ÉS az e-mailbe kerül (Sellvio/Unas: tételek + szállítási mód; Shoprenter:
raktár-bontás külön; Woo: nincs). Raktár-bontás CSAK Shoprenternél van.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import httpx

from app.core.mailer import schedule_email
from app.services.webdoc_status import (
    first_order as _wd_first_order,
    parse_order_number as _wd_parse_number,
    pick_items as _wd_items,
    pick_payment as _wd_payment,
    pick_shipping as _wd_shipping,
    pick_status as _wd_status,
    status_maps as _wd_maps,
    zip_matches as _wd_zip_matches,
)
from app.services.platform_api import (
    UNAS_BASE,
    norm_email,
    sellvio_token,
    shoprenter_resource_id,
    shoprenter_shop,
    shoprenter_token,
    unas_login,
    xml_first_text,
    xml_root,
)

if TYPE_CHECKING:
    from app.models.db_models import Tenant
    from app.services.intent import OrderIntent

logger = logging.getLogger("cx.order")

# semleges válasz — NEM-matched (és hiba) esetben (adat-szivárgás ellen)
ORDER_STATUS_REPLY = (
    "Ha a megadott rendelésszámhoz és e-mail-címhez tartozik rendelés, a "
    "részleteket elküldtük arra az e-mail-címre. Kérlek, nézd meg a postafiókod "
    "(a spam mappát is)."
)


# Webdoc: a rendelés-API nem ad e-mail-címet, így levelet sem tudunk küldeni —
# a semleges válasz sem ígérhet e-mailt (m29).
ORDER_STATUS_REPLY_NO_EMAIL = (
    "Nem találtam a megadott rendelésszámhoz és irányítószámhoz tartozó rendelést. "
    "Kérlek, ellenőrizd az adatokat — az irányítószám a rendeléskor megadott szállítási "
    "vagy számlázási cím irányítószáma. Ha nem boldogulsz, ügyfélszolgálatunk segít."
)

# rate limit (m29): a Webdocnál a rendelés id-je a rendelésszámból kiszámolható,
# ezért a próbálkozásokat korlátozzuk (a hívó könyveli, lásd app/services/rate_limit.py)
ORDER_LOOKUP_BLOCKED_REPLY = (
    "Túl sok sikertelen próbálkozás történt. Biztonsági okból egy ideig nem tudok "
    "rendelést keresni ebben a beszélgetésben. Kérlek, fordulj ügyfélszolgálatunkhoz."
)


def _matched_reply(order_id: str, status: str, note: str = "", emailed: bool = True) -> str:
    """matched esetén a chat is kimondja a státuszt — a vevő igazolta magát
    (rendelésszám + e-mail; Webdocnál rendelésszám + irányítószám).
    'ismeretlen'/üres státusz SOHA nem megy ki.

    emailed=False (Webdoc): az API nem ad e-mail-címet, ne ígérjünk levelet.
    """
    mail = " A részleteket e-mailben is elküldtük a rendeléskor megadott címre." if emailed else ""
    if status and status != "ismeretlen":
        base = f"A(z) #{order_id} rendelésed állapota: {status}." + mail
    elif emailed:
        base = (
            f"A(z) #{order_id} rendelésedet megtaláltuk, a részleteket e-mailben "
            "elküldtük a rendeléskor megadott címre. Az aktuális állapotról "
            "ügyfélszolgálatunk tud pontos tájékoztatást adni."
        )
    else:
        base = (
            f"A(z) #{order_id} rendelésedet megtaláltuk. Az aktuális állapotról "
            "ügyfélszolgálatunk tud pontos tájékoztatást adni."
        )
    return base + (f" {note}" if note else "")


def _pick_status_name(j: dict) -> str:
    """A /orderStatuses/{id}?full=1 valaszabol a lokalizalt nev (pure, teszthelto).

    Alakok: {"name": "..."} top-level; VAGY orderStatusDescriptions list;
    VAGY {"orderStatusDescriptions": {"orderStatusDescription": [...]}} burkolt alak.
    """
    if not isinstance(j, dict):
        return ""
    o = j.get("orderStatus") if isinstance(j.get("orderStatus"), dict) else j
    v = o.get("name")
    if isinstance(v, str) and v.strip():
        return v.strip()
    descs = o.get("orderStatusDescriptions")
    if isinstance(descs, dict):
        descs = descs.get("orderStatusDescription") or descs.get("items") or []
    if isinstance(descs, list):
        for d in descs:
            if isinstance(d, dict) and isinstance(d.get("name"), str) and d["name"].strip():
                return d["name"].strip()
    return ""


async def _sr_status_name(client, api_base: str, token: str, status_obj) -> str:
    """Shoprenter orderStatus href -> lokalizalt statusznev (api2 + Bearer). Hiba -> ''.

    A href a regi api hostra mutat; csak az utolso path-szegmenst (b64 id) hasznaljuk
    az api_base-szel (m24/B — az 'ismeretlen' kiirtasa az e-mailbol).
    """
    try:
        href = str((status_obj or {}).get("href") or "") if isinstance(status_obj, dict) else ""
        b64 = href.rstrip("/").split("/")[-1] if href else ""
        if not b64:
            return ""
        r = await client.get(
            f"{api_base}/orderStatuses/{b64}",
            params={"full": "1"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        r.raise_for_status()
        j = r.json()
        name = _pick_status_name(j) if isinstance(j, dict) else ""
        if name:
            return name
        # api2: a full=1 sem agyazza be a leirasokat — az orderStatusDescriptions maga is
        # href -> masodik hop: GET /orderStatusDescriptions?orderStatusId={b64}
        o = j if isinstance(j, dict) else {}
        if isinstance(o.get("orderStatus"), dict):
            o = o["orderStatus"]
        d = o.get("orderStatusDescriptions")
        if isinstance(d, dict) and d.get("href"):
            r2 = await client.get(
                f"{api_base}/orderStatusDescriptions",
                params={"orderStatusId": b64, "full": "1"},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            r2.raise_for_status()
            j2 = r2.json()
            items = j2.get("items") if isinstance(j2, dict) else None
            if isinstance(items, dict):
                items = items.get("orderStatusDescription") or []
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and isinstance(it.get("name"), str) and it["name"].strip():
                        return it["name"].strip()
        return ""
    except Exception:  # noqa: BLE001 — nev-feloldasi hiba SOHA ne torje a lookupot
        return ""


def _format_wh_note(buckets: list[tuple[str, str, int]], skipped: int = 0) -> str:
    """Raktár-bontás szöveg (m24/C, pure). buckets: (név, szállítás, tételszám)."""
    if not buckets:
        return ""
    parts = []
    for name, delivery, cnt in buckets:
        p = f"{name}: {cnt} tétel"
        if delivery:
            p += f" (szállítás: {delivery})"
        parts.append(p)
    note = "Raktár szerinti bontás — " + "; ".join(parts) + "."
    if len(buckets) > 1:
        note += " A csomag szállítási ideje a leghosszabb szállítású tétel szerint alakul."
    return note


async def _sr_order_warehouse_note(tenant: "Tenant", order_id: str) -> str:
    """m24/C: a rendelés tételei raktár szerint (orderProducts.stock1..4 = raktár-foglalás).

    A tenant warehouse_config-ja (nevesített raktárak) szerint csoportosít; a nem
    konfigurált raktárból foglalt / foglalás nélküli tételek kimaradnak a bontásból.
    Bármely hiba -> "" (a rendelés-flow nem törhet).
    """
    cfg = getattr(tenant, "warehouse_config", None)
    ws = cfg.get("warehouses") if isinstance(cfg, dict) else None
    if not isinstance(ws, dict) or not ws:
        return ""
    try:
        api_base = str(tenant.api_base or "").strip().rstrip("/")
        shop = shoprenter_shop(api_base)
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            token = await shoprenter_token(
                client, shop,
                str(tenant.api_client_id or "").strip(),
                str(tenant.api_client_secret or "").strip(),
            )
            if not token:
                return ""
            r = await client.get(
                f"{api_base}/orderProducts",
                params={"orderId": shoprenter_resource_id("order", order_id), "full": "1", "limit": 50},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            r.raise_for_status()
            j = r.json()
        items = j.get("items") if isinstance(j, dict) else None
        if not isinstance(items, list):
            return ""
        counts: dict[int, int] = {}
        skipped = 0
        for it in items[:20]:
            if not isinstance(it, dict):
                continue
            placed = False
            for i in (1, 2, 3, 4):
                try:
                    q = float(it.get(f"stock{i}") or 0)
                except (TypeError, ValueError):
                    q = 0.0
                if q > 0:
                    if str(i) in ws:
                        counts[i] = counts.get(i, 0) + 1
                    else:
                        skipped += 1
                    placed = True
                    break
            if not placed:
                skipped += 1
        buckets = [
            (str((ws.get(str(i)) or {}).get("name") or f"raktár {i}").strip(),
             str((ws.get(str(i)) or {}).get("delivery") or "").strip(),
             counts[i])
            for i in sorted(counts)
        ]
        return _format_wh_note(buckets, skipped)
    except Exception:  # noqa: BLE001 — bontas-hiba SOHA ne torje az order-flow-t
        logger.exception("ORDER[%s] raktar-bontas hiba (id=%s)", tenant.client_id, order_id)
        return ""


def _safe_status(*candidates) -> str:
    """Az első str (nem dict/href/None) jelölt; különben generikus 'ismeretlen'.

    Védi az e-mailt attól, hogy egy href-dict ({'href': ...}) string-elve menjen ki.
    """
    for v in candidates:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "ismeretlen"


# --------------------------------------------------------------------------- #
# Közös: tétel + szállítási mód jegyzet (pure, teszthelto) — Sellvio + Unas
# Raktár-bontás NINCS (az CSAK Shoprenter, lásd _sr_order_warehouse_note).
# --------------------------------------------------------------------------- #
def _first_str(d: dict, *keys) -> str:
    """Az első nem-üres str/szám mező a kulcsok közül (str-re konvertálva)."""
    if not isinstance(d, dict):
        return ""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return str(v)
    return ""


def _fmt_qty(q) -> str:
    """Mennyiség megjelenítés: '2.0'/'2,0' -> '2'; nem-szám -> nyers str; üres -> ''."""
    s = str(q if q is not None else "").strip()
    if not s:
        return ""
    try:
        f = float(s.replace(",", "."))
    except (TypeError, ValueError):
        return s
    return str(int(f)) if f == int(f) else str(f)


def _format_order_note(items: list[tuple[str, str]], delivery: str) -> str:
    """Tétel + szállítás jegyzet (pure). 'Tételek: 2× X; Y.' [+ ' Szállítási mód: Z.']."""
    parts = []
    for name, qty in (items or [])[:20]:
        name = str(name or "").strip()
        if not name:
            continue
        q = _fmt_qty(qty)
        parts.append(f"{q}× {name}" if q else name)
    note = ("Tételek: " + "; ".join(parts) + ".") if parts else ""
    delivery = str(delivery or "").strip()
    if delivery:
        note += (" " if note else "") + f"Szállítási mód: {delivery}."
    return note


# --------------------------------------------------------------------------- #
# Sellvio — GET /api/v2/orders/ (list), kliens-oldali id+email match
# --------------------------------------------------------------------------- #
_SELLVIO_MAX_PAGES = 5  # a legfrissebb ~500 rendelésig scannelünk (limit=100)


def _sellvio_status(o: dict) -> str:
    """Rendelés-állapot: status{name}|status(str)|status_name|state; különben 'ismeretlen'.

    A payment_status SZÁNDÉKOSAN kimarad (az a fizetés, nem a teljesítés állapota).
    """
    st = o.get("status") if isinstance(o, dict) else None
    if isinstance(st, dict):
        n = st.get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()
    if isinstance(st, str) and st.strip():
        return st.strip()
    return _first_str(o, "status_name", "state") or "ismeretlen"


def _sellvio_items(o: dict) -> list[tuple[str, str]]:
    """order_items -> [(név, mennyiség)]."""
    out: list[tuple[str, str]] = []
    for it in (o.get("order_items") or []) if isinstance(o, dict) else []:
        if isinstance(it, dict):
            out.append(
                (_first_str(it, "name", "product_name", "title"),
                 _first_str(it, "quantity", "qty", "amount"))
            )
    return out


def _sellvio_delivery(o: dict) -> str:
    """delivery_type (str vagy {name}) -> szállítási mód; fallback: deliveries[].name."""
    if not isinstance(o, dict):
        return ""
    dt = o.get("delivery_type")
    if isinstance(dt, dict):
        n = _first_str(dt, "name", "title", "type")
        if n:
            return n
    elif isinstance(dt, str) and dt.strip():
        return dt.strip()
    for d in (o.get("deliveries") or []):
        if isinstance(d, dict):
            n = _first_str(d, "name", "title", "type")
            if n:
                return n
    return ""


def _sellvio_match(items: list, order_id: str, order_email: str) -> tuple[bool, dict | None]:
    """Adatvédelmi guard (a _verify_order mintát követi): CSAK ha az id ÉS az e-mail is egyezik.

    - id nem található az oldalon -> (False, None): lapozz tovább.
    - id egyezik, e-mail is egyezik -> (True, order).
    - id egyezik, e-mail NEM egyezik -> (False, order): NEM matched, és megállunk (az id egyedi).
    """
    want_id = str(order_id or "").strip()
    want_email = norm_email(order_email)
    for o in items or []:
        if not isinstance(o, dict):
            continue
        oid = o.get("id")
        if str(oid if oid is not None else "").strip() != want_id:
            continue
        oe = norm_email(o.get("email"))
        if oe and oe == want_email:
            return True, o
        return False, o  # id egyezik, e-mail nem -> adatvédelmi guard
    return False, None


async def _sellvio_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str, str]:
    api_base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    secret = str(tenant.api_client_secret or "").strip()
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        token = await sellvio_token(client, api_base, cid, secret)
        if not token:
            logger.warning("ORDER[%s] nincs Sellvio token", tenant.client_id)
            return False, "ismeretlen", ""
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        page = 1
        for _ in range(_SELLVIO_MAX_PAGES):
            resp = await client.get(
                f"{api_base}/api/v2/orders/",
                params={"locale": "hu", "page": page, "limit": 100},
                headers=headers,
            )
            resp.raise_for_status()
            body = resp.json()
            data = (body or {}).get("data") or {} if isinstance(body, dict) else {}
            items = [o for o in (data.get("items") or []) if isinstance(o, dict)]
            matched, o = _sellvio_match(items, order.order_id, order.order_email)
            if o is not None:  # id megvan ezen az oldalon (matched vagy e-mail-eltérés)
                if matched:
                    note = _format_order_note(_sellvio_items(o), _sellvio_delivery(o))
                    return True, _sellvio_status(o), note
                return False, _sellvio_status(o), ""
            last_page = data.get("last_page") or page
            if data.get("next_page_url") is None or page >= int(last_page):
                break
            page += 1
    logger.info("ORDER[%s] Sellvio: id=%s nem található az első %s oldalon",
                tenant.client_id, order.order_id, _SELLVIO_MAX_PAGES)
    return False, "ismeretlen", ""


# --------------------------------------------------------------------------- #
# WooCommerce — GET /wp-json/wc/v3/orders/{id}, Basic auth (consumer key/secret)
# --------------------------------------------------------------------------- #
async def _woo_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str, str]:
    base = str(tenant.api_base or "").strip().rstrip("/")
    ck = str(tenant.api_client_id or "").strip()        # ck_...
    cs = str(tenant.api_client_secret or "").strip()    # cs_...
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(
            f"{base}/wp-json/wc/v3/orders/{order.order_id}",
            auth=(ck, cs),
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, dict) or not data.get("id"):
        return False, "ismeretlen", ""
    status = str(data.get("status") or "ismeretlen")
    billing = data.get("billing") if isinstance(data.get("billing"), dict) else {}
    email = norm_email((billing or {}).get("email"))
    if not email or email != norm_email(order.order_email):
        return False, status, ""
    return True, status, ""


# --------------------------------------------------------------------------- #
# Shoprenter — OAuth2 (Basic deprecated->403); base64 order id
# --------------------------------------------------------------------------- #
async def _shoprenter_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str, str]:
    api_base = str(tenant.api_base or "").strip().rstrip("/")
    cid = str(tenant.api_client_id or "").strip()
    secret = str(tenant.api_client_secret or "").strip()
    shop = shoprenter_shop(api_base)
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        token = await shoprenter_token(client, shop, cid, secret)
        if not token:
            logger.warning("ORDER[%s] nincs Shoprenter token", tenant.client_id)
            return False, "ismeretlen", ""
        resp = await client.get(
            f"{api_base}/orders/{shoprenter_resource_id('order', order.order_id)}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return False, "ismeretlen", ""
        # az api2 single GET csupasz top-level objektumot ad (nincs response/order burkoló),
        # az email top-level mező — a match-logika HELYES, ne nyúlj hozzá.
        o = data.get("order") if isinstance(data.get("order"), dict) else data
        if not o or not (o.get("id") or o.get("innerId") or o.get("orderNumber")):
            return False, "ismeretlen", ""
        # a valós orderStatus href-dict ({'href': '.../orderStatuses/<b64>'}) -> NEM stringeljük;
        # str státusz híján a nevet a /orderStatuses végpontról oldjuk fel (m24/B).
        status = _safe_status(o.get("statusName"), o.get("orderStatus"), o.get("status"))
        if status == "ismeretlen":
            name = await _sr_status_name(client, api_base, token, o.get("orderStatus"))
            if name:
                status = name
    email = norm_email(o.get("email") or o.get("customerEmail"))
    if not email or email != norm_email(order.order_email):
        return False, status, ""
    # a raktár-bontás jegyzet a handle_order_status-ban készül (külön orderProducts-hívás).
    return True, status, ""


# --------------------------------------------------------------------------- #
# Unas — login(ApiKey)->Token, POST /getOrder XML, Bearer
# --------------------------------------------------------------------------- #
def _local_tag(el) -> str:
    """namespace-független, kisbetűs helyi tagnév (a xml_first_text mintáját követi)."""
    return el.tag.split("}")[-1].lower()


def _iter_local(el, name: str) -> list:
    """Az összes leszármazott elem, aminek a helyi tagje illik (namespace nélkül)."""
    low = name.lower()
    return [sub for sub in el.iter() if _local_tag(sub) == low]


def _unas_order_status(order_el) -> str:
    """Rendelés-SZINTŰ státusz: az Order KÖZVETLEN <Status>/<StatusName> gyereke.

    A közvetlen-gyerek szűrés SZÁNDÉKOS: az Items/Item-en belül is van <Status> (tétel-státusz),
    azt a xml_first_text descendant-bejárása tévesen elkapná. Ha a <Status> nem szöveges, hanem
    burkolt (<Status><Name>..</Name></Status>), a Name-et olvassuk.
    """
    for ch in list(order_el):
        if _local_tag(ch) in ("status", "statusname"):
            if ch.text and ch.text.strip():
                return ch.text.strip()
            n = xml_first_text(ch, "Name", "Text")
            if n:
                return n
    return "ismeretlen"


def _unas_items(order_el) -> list[tuple[str, str]]:
    """Items/Item -> [(Name, Quantity)]."""
    return [
        (xml_first_text(item, "Name"), xml_first_text(item, "Quantity"))
        for item in _iter_local(order_el, "Item")
    ]


def _unas_delivery(order_el) -> str:
    """A <Delivery> blokk szállítási módja, PRIORITÁS-sorrendben: Mode -> Name -> Type.

    A xml_first_text a DOKUMENTUM-sorrend szerinti első illeszkedőt adja (nem a paraméter-
    sorrend szerintit), ezért tag-enként, prioritással kell kérdezni.
    """
    for d in _iter_local(order_el, "Delivery"):
        for tag in ("Mode", "Name", "Type"):
            v = xml_first_text(d, tag)
            if v:
                return v
    return ""


async def _unas_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str, str]:
    api_key = str(tenant.api_client_secret or "").strip() or str(tenant.api_client_id or "").strip()
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        token = await unas_login(client, api_key)
        if not token:
            logger.warning("ORDER[%s] nincs Unas token", tenant.client_id)
            return False, "ismeretlen", ""
        # Contents nélkül is teljes a válasz (smartzillán élesben igazolva); a full param nem igazolt.
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<Params><Key>{escape(order.order_id)}</Key></Params>"
        )
        resp = await client.post(
            f"{UNAS_BASE}/getOrder",
            content=body.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/xml"},
        )
        resp.raise_for_status()
        root = xml_root(resp.text)
    if root is None:
        return False, "ismeretlen", ""
    order_el = root.find(".//Order")
    if order_el is None:
        return False, "ismeretlen", ""
    status = _unas_order_status(order_el)
    # adatvédelmi guard: a válaszban lévő e-mailnek egyeznie kell a megadottal (id+email együtt).
    email = norm_email(xml_first_text(order_el, "Email"))
    if not email or email != norm_email(order.order_email):
        return False, status, ""
    note = _format_order_note(_unas_items(order_el), _unas_delivery(order_el))
    return True, status, note


# --------------------------------------------------------------------------- #
# Webdoc — GET {public_url}/services/api/orders?id=<id>, Basic auth (m29)
# Azonositas: rendelesszam + iranyitoszam (az API a customer.email-t uresen adja).
# Adat-minimalizalas: nev/cim/telefon/adoszam SOHA nem hagyja el ezt a fuggvenyt.
# --------------------------------------------------------------------------- #
_WEBDOC_API_PATH = "/services/api/orders"


def _webdoc_json(text: str):
    """A szallito helyenkent trailing commat ad (a sajat OpenAPI leiroja is hibas) — toleraljuk."""
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


async def _webdoc_lookup(tenant: "Tenant", order: "OrderIntent") -> tuple[bool, str, str]:
    oid = _wd_parse_number(order.order_id)
    if oid is None:
        return False, "", ""
    base = str(tenant.public_url or "").strip().rstrip("/")
    user = str(tenant.api_client_id or "").strip()
    pw = str(tenant.api_client_secret or "").strip()
    if not base or not user or not pw:
        logger.warning("ORDER[%s] hianyzo Webdoc API cred / public_url", tenant.client_id)
        return False, "", ""

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(
            f"{base}{_WEBDOC_API_PATH}",
            params={"id": oid},
            auth=(user, pw),
            headers={"Accept": "application/json", "User-Agent": "curl/8.5.0"},
        )
        resp.raise_for_status()
        payload = _webdoc_json(resp.text)

    o = _wd_first_order(payload)
    if not o:
        return False, "", ""
    # adatvedelmi guard: a rendelesszam mellett az iranyitoszamnak is egyeznie kell
    # (szallitasi VAGY szamlazasi) — kulonben semleges valasz, enumeracio-vedelem.
    if not _wd_zip_matches(o, order.order_zip):
        logger.info("ORDER[%s] Webdoc: id=%s megvan, irsz nem egyezik", tenant.client_id, oid)
        return False, "", ""

    maps = _wd_maps(tenant)
    name, dt = _wd_status(o, maps)
    status = f"{name} ({dt[:16]})" if (name and dt) else name
    note = _format_order_note(_wd_items(o), _wd_shipping(o, maps))
    pay = _wd_payment(o, maps)
    if pay:
        note = (note + " " if note else "") + f"Fizetés: {pay}."
    return True, status, note


# --------------------------------------------------------------------------- #
# Dispatch + e-mail
# --------------------------------------------------------------------------- #
_LOOKUPS = {
    "sellvio": _sellvio_lookup,
    "woocommerce": _woo_lookup,
    "shoprenter": _shoprenter_lookup,
    "unas": _unas_lookup,
    "webdoc": _webdoc_lookup,
}


def _send_status_email(tenant: "Tenant", order: "OrderIntent", status: str, note: str = "") -> None:
    bot = str(tenant.bot_name or "").strip() or tenant.client_id
    subject = f"Rendelésed állapota – #{order.order_id}"
    if status and status != "ismeretlen":
        body = f"A(z) #{order.order_id} számú rendelésed állapota: {status}"
    else:
        # m24/B: 'ismeretlen' SOHA nem megy ki — generikus, de korrekt szöveg
        body = (
            f"A(z) #{order.order_id} számú rendelésedet megtaláltuk a rendszerünkben. "
            "Az aktuális állapotról ügyfélszolgálatunk tud pontos tájékoztatást adni."
        )
    if note:
        body += f"\n\n{note}"
    text = (
        "Kedves Vásárlónk!\n\n"
        f"{body}\n\n"
        f"Üdvözlettel,\n{bot}"
    )
    logger.info(
        "ORDER[%s] matched id=%s -> e-mail to=%s", tenant.client_id, order.order_id, order.order_email
    )
    schedule_email(order.order_email, subject, text)


def _neutral_reply(platform: str) -> str:
    """Semleges válasz — Webdocnál nem ígérhetünk e-mailt (nincs cím az API-ban)."""
    return ORDER_STATUS_REPLY_NO_EMAIL if platform == "webdoc" else ORDER_STATUS_REPLY


async def handle_order_status_ex(tenant: "Tenant", order: "OrderIntent") -> tuple[str, bool]:
    """(válasz, matched). Platform szerinti order-lekérés. Matched esetén a státuszt a
    chatben is kimondja (m24/A), és — ha ismerjük a vevő e-mail-címét — háttérben levelet
    ütemez. Nem-matched / hiba / ismeretlen platform -> semleges válasz; logol, nem dob.

    A `matched` flag a hívónak kell a rate-limit könyveléshez (m29).
    """
    platform = str(tenant.platform or "").strip().lower()
    lookup = _LOOKUPS.get(platform)
    if lookup is None:
        logger.info("ORDER[%s] platform=%s nincs portolva — semleges válasz", tenant.client_id, platform)
        return _neutral_reply(platform), False

    try:
        matched, status, note = await lookup(tenant, order)
    except Exception:  # noqa: BLE001 — platform-hiba SOHA ne törje meg a /chat-et
        logger.exception(
            "ORDER[%s] %s hívás hiba (id=%s)", tenant.client_id, platform, order.order_id
        )
        return _neutral_reply(platform), False

    if matched:
        # Sellvio/Unas: a note = tételek + szállítási mód (a lookup adja).
        # Shoprenter: raktár-bontás (külön orderProducts-hívás). Raktár-bontás CSAK itt.
        # Webdoc: tételek + szállítási mód + fizetés (a lookup adja).
        if platform == "shoprenter":
            note = await _sr_order_warehouse_note(tenant, order.order_id)
        emailed = bool(str(getattr(order, "order_email", "") or "").strip())
        if emailed:
            _send_status_email(tenant, order, status, note)
        return _matched_reply(order.order_id, status, note, emailed=emailed), True
    logger.info(
        "ORDER[%s] nem matched id=%s (%s) — semleges válasz, nincs e-mail",
        tenant.client_id, order.order_id, platform,
    )
    return _neutral_reply(platform), False


async def handle_order_status(tenant: "Tenant", order: "OrderIntent") -> str:
    """Visszafelé kompatibilis burkoló (a régi hívók/tesztek str-t várnak)."""
    reply, _matched = await handle_order_status_ex(tenant, order)
    return reply

"""Normalizált forrás-termék + Qdrant payload-építés (a chat által olvasott séma).

A payload-kulcsoknak EGYEZNIÜK kell azzal, amit a chat olvas (retrieval.py / current_product.py /
prompt.py): client_id, type="product", sku, name, text, url, price, brand, content_hash, ps_hash,
filename, related_similar, related_additional + platform-azonosító + (ha van) stock/available.

A `text` (embeddelt chunk) és a content_hash mező-összetétele a retrieval-paritás KULCSA — a pontos
n8n-egyezéshez a Sync workflow "Build Product Points" Code node a referencia (kérendő a VPS-től).
Az alábbi összetétel ésszerű alapértelmezés; a `build_text`/`content_hash` egy helyen állítható.
"""

from dataclasses import dataclass

from app.sync.hashing import content_hash, ps_hash


@dataclass
class SourceProduct:
    sku: str
    name: str = ""
    url: str = ""
    price: str = ""                 # synced ár (string, ahogy a platform/normalizálás adja)
    brand: str = ""
    category: str = ""
    description: str = ""
    params: str = ""
    stock: int | None = None
    available: bool | None = None
    related_similar: str = ""
    related_additional: str = ""
    platform_id_field: str = ""     # "sellvio_id" | "wc_id" | "webdoc_id" | "" (SR/Unas: nincs)
    platform_id_value: str = ""


def scalar_price(v) -> str:
    """Ár -> string; dict esetén brutto_price/netto_price (Sellvio), majd gross/amount/value."""
    if isinstance(v, dict):
        for k in ("brutto_price", "netto_price", "gross", "amount", "value", "price"):
            inner = v.get(k)
            if isinstance(inner, (str, int, float)):
                return str(inner)
        return ""
    if isinstance(v, (str, int, float)):
        return str(v)
    return ""


def build_text(p: SourceProduct) -> str:
    """Az embeddelt chunk szövege (termékenként 1 chunk). Lásd a modul-docstring paritás-jegyzetét."""
    lines = [p.name]
    if p.brand:
        lines.append(f"Márka: {p.brand}")
    if p.category:
        lines.append(f"Kategória: {p.category}")
    if p.price:
        lines.append(f"Ár: {p.price}")
    if p.description:
        lines.append(p.description)
    if p.params:
        lines.append(p.params)
    if p.url:
        lines.append(p.url)
    return "\n".join(x for x in lines if x).strip()


def compute_content_hash(p: SourceProduct) -> str:
    """Szemantikus hash (ár/készlet NÉLKÜL): név|márka|kategória|leírás|paraméterek|url."""
    return content_hash(p.name, p.brand, p.category, p.description, p.params, p.url)


def compute_ps_hash(p: SourceProduct) -> str:
    return ps_hash(p.price, p.stock, p.available)


def build_payload(client_id: str, p: SourceProduct, filename: str, text: str, ch: str, ph: str) -> dict:
    """A chat által olvasott TELJES payload (+ platform-id + synced stock/available, ha van)."""
    payload: dict = {
        "client_id": client_id,
        "type": "product",
        "sku": p.sku,
        "name": p.name,
        "text": text,
        "url": p.url,
        "price": p.price,
        "brand": p.brand,
        "content_hash": ch,
        "ps_hash": ph,
        "filename": filename,
        "related_similar": p.related_similar,
        "related_additional": p.related_additional,
    }
    if p.platform_id_field and p.platform_id_value:
        payload[p.platform_id_field] = p.platform_id_value
    if p.stock is not None:
        payload["stock"] = p.stock
    if p.available is not None:
        payload["available"] = p.available
    return payload


def ps_payload(p: SourceProduct, ph: str) -> dict:
    """A csak-ár/készlet frissítéskor (set_payload) felülírt mezők — a vektor/szemantika érintetlen."""
    sub: dict = {"price": p.price, "ps_hash": ph}
    if p.stock is not None:
        sub["stock"] = p.stock
    if p.available is not None:
        sub["available"] = p.available
    return sub

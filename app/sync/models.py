"""Normalizált forrás-termék + Qdrant payload-építés (a chat által olvasott séma).

A `text` (embeddelt chunk) és a payload-kulcsok a reference/n8n-sync/ Code node-jaival
byte-paritásban (lásd app/sync/builders.py). A content_hash / point_id a v2 SAJÁT sémája
(content-only hash; külön kollekció, csak önmagával konzisztens).
"""

from dataclasses import dataclass

try:  # m79c
    from app.services.paramextract import extract_params
except Exception:  # fajl-betoltos tesztek (sync parity/delta) app-csomag nelkul
    import importlib.util as _ilu
    import pathlib as _pl
    _pp = _pl.Path(__file__).resolve().parents[1] / "services" / "paramextract.py"
    _sp = _ilu.spec_from_file_location("paramextract_m79c_fb", _pp)
    _pm = _ilu.module_from_spec(_sp)
    _sp.loader.exec_module(_pm)
    extract_params = _pm.extract_params


@dataclass
class SourceProduct:
    id_key: str                  # stabil egyedi azonosító a point_id-hoz (sellvio_id/wc_id/sku||url||name)
    sku: str = ""
    name: str = ""
    url: str = ""
    price: str = ""              # synced ár string (payload)
    brand: str = ""
    stock_str: str = ""          # synced készlet string a payloadba (SR/Unas), különben ""
    related_similar: str = ""
    related_additional: str = ""
    text: str = ""               # az embeddelt chunk (byte-match a node-dal)
    content_hash: str = ""       # content-only hash (v2 saját)
    platform_id_field: str = ""  # "sellvio_id" | "wc_id" | "webdoc_id" | "" (SR/Unas: nincs)
    platform_id_value: str = ""
    filename: str = ""
    available: bool | None = None  # webdoc: synced készlet-bool a payloadba
    ps_hash_str: str = ""          # webdoc: ár/készlet ujjlenyomat (a külön PriceStock Fast-hez)


def build_payload(client_id: str, p: SourceProduct) -> dict:
    """A chat által olvasott payload + platform-specifikus mezők (a node-okkal egyezve).

    Sellvio/Woo: platform-id (sellvio_id/wc_id), stock NINCS. Shoprenter/Unas: stock VAN, platform-id nincs.
    """
    payload: dict = {
        "client_id": client_id,
        "filename": p.filename,
        "type": "product",
        "text": p.text,
        "name": p.name,
        "price": p.price,
        "url": p.url,
        "sku": p.sku,
        "brand": p.brand,
        "related_similar": p.related_similar,
        "related_additional": p.related_additional,
        "content_hash": p.content_hash,
    }
    if p.platform_id_field and p.platform_id_value:
        payload[p.platform_id_field] = p.platform_id_value
    if p.stock_str != "":
        payload["stock"] = p.stock_str
    if p.available is not None:          # webdoc: synced készlet-bool
        payload["available"] = p.available
    if p.ps_hash_str:                    # webdoc: ár/készlet ujjlenyomat
        payload["ps_hash"] = p.ps_hash_str
    payload.update(extract_params(p.name, p.text))  # m79c: parameter-mezok (csak kinyert kulcsok)
    return payload

"""Determinisztikus point-ID + tartalom/ár-készlet hash a sync delta-logikához.

- point_id: uuid5(NS, f"{client_id}:{sku}:{chunk_idx}") -> idempotens upsert, újrafuttatás konvergál.
- content_hash: FNV-1a 32-bit a SZEMANTIKUS mezőkről (név|márka|kategória|leírás|paraméterek|url)
  -> a változatlan tartalmat NEM embeddeljük újra.
- ps_hash: FNV-1a az ÁR+KÉSZLET-ről -> csak payload-frissítés (set_payload), nincs embed.

Az n8n sync FNV content-hasht használ; a v2 kollekcióban a hash ÖNKONZISZTENS (a delta a saját
korábbi hash-ével vet össze), ezért nem kell n8n-bájtpontosság a működéshez. (A retrieval-paritáshoz
a `text` összetétele számít — lásd app/sync/models.py — ahhoz a Sync workflow JSON a referencia.)
"""

import uuid

# fix, app-specifikus uuid5 namespace (determinisztikus)
_NS = uuid.uuid5(uuid.NAMESPACE_URL, "codexpress.cloud/chatbot")


def fnv1a_32(s: str) -> str:
    """FNV-1a 32-bit hex."""
    h = 0x811C9DC5
    for b in (s or "").encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def point_id(client_id: str, sku: str, chunk_idx: int = 0) -> str:
    return str(uuid.uuid5(_NS, f"{client_id}:{sku}:{chunk_idx}"))


def content_hash(*parts: str) -> str:
    """Szemantikus ujjlenyomat — ár/készlet NINCS benne (azt a ps_hash figyeli)."""
    return fnv1a_32("|".join((p or "").strip() for p in parts))


def ps_hash(price: str, stock, available) -> str:
    """Ár + készlet ujjlenyomat — a csak-ár/készlet változás detektálására."""
    return fnv1a_32(f"{price}|{stock}|{available}")

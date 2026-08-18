"""m92: kikapcsolt (active=false) tenant kapuja.

Lelet 2026-08-18: a `tenants.active` mező EDDIG CSAK a syncet szűrte
(`app/sync/__main__.py`: `select(Tenant).where(Tenant.active.is_(True))`) — a
`/chat` végpont és a widget-config semmit nem nézett belőle. Vagyis egy távozó
ügyfél boltjában a bot a „lekapcsolás" után is válaszolt volna, csak az adatai
nem frissültek volna tovább. Ez a modul adja a hiányzó kaput, egy helyen, hogy
a chat-ág és a widget-config ne drifteljen szét.
"""


def is_disabled(tenant) -> bool:
    """True, ha a tenant LÉTEZIK, de ki van kapcsolva.

    Ismeretlen tenant (None) NEM „disabled" — arra a hívóknak külön (régebbi)
    ága van, és a widget-config alapértelmezett törzset ad vissza.
    """
    if tenant is None:
        return False
    return not bool(getattr(tenant, "active", True))

"""Platform API közös primitívek (auth/token, XML, e-mail-normalizálás).

Az order-status (order_status.py) ÉS az élő ár/készlet (live_product.py) ág is ezt
osztja — az auth EGY helyen él, hogy ne drifteljen szét. A platform-specifikus
lekérdező-logika a hívó modulokban marad.
"""

import base64
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import httpx

UNAS_BASE = "https://api.unas.eu/shop"


def norm_email(s: str | None) -> str:
    return str(s or "").strip().lower()


# --- Sellvio ----------------------------------------------------------------
async def sellvio_token(
    client: httpx.AsyncClient, api_base: str, client_id: str, client_secret: str
) -> str:
    """OAuth client_credentials -> access_token (üres string, ha nincs)."""
    resp = await client.post(
        f"{api_base}/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    return str((resp.json() or {}).get("access_token") or "")


# --- Shoprenter (OAuth2; Basic deprecated -> 403) ---------------------------
def shoprenter_shop(api_base: str) -> str:
    """{shop}.api2.myshoprenter.hu/api/ -> shop"""
    host = urlsplit(api_base).hostname or ""
    return host.split(".")[0] if host else ""


def shoprenter_resource_id(entity: str, value: str) -> str:
    """A Shoprenter resource-id base64('<entity>-<entity>_id=<value>') sémát követ."""
    return base64.b64encode(f"{entity}-{entity}_id={value}".encode()).decode()


async def shoprenter_token(
    client: httpx.AsyncClient, shop: str, client_id: str, client_secret: str
) -> str:
    resp = await client.post(
        f"https://oauth.app.shoprenter.net/{shop}/app/token",
        json={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
    )
    resp.raise_for_status()
    return str((resp.json() or {}).get("access_token") or "")


# --- Unas (login -> token; XML) ---------------------------------------------
def xml_root(text: str) -> ET.Element | None:
    try:
        return ET.fromstring(text or "")
    except ET.ParseError:
        return None


def xml_first_text(el: ET.Element, *local_names: str) -> str:
    """Az első leszármazott elem szövege, aminek a (namespace nélküli) tagje illik."""
    wanted = {n.lower() for n in local_names}
    for sub in el.iter():
        if sub.tag.split("}")[-1].lower() in wanted and sub.text and sub.text.strip():
            return sub.text.strip()
    return ""


async def unas_login(client: httpx.AsyncClient, api_key: str) -> str:
    from xml.sax.saxutils import escape

    body = f'<?xml version="1.0" encoding="UTF-8"?>\n<Params><ApiKey>{escape(api_key)}</ApiKey></Params>'
    resp = await client.post(
        f"{UNAS_BASE}/login",
        content=body.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    resp.raise_for_status()
    root = xml_root(resp.text)
    return xml_first_text(root, "Token") if root is not None else ""

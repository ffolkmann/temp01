"""Aktuális termék injektálás — a prod `Get Current Product` (Qdrant scroll) + a Build Prompt
current-product kicsomagolásának portja (lásd seed/prod_chat_logic.txt, 2. blokk).

A scroll szűr: client_id + type=product + url = page_url_norm. Az első type=='product'
&& text találat adja a currentProductText-et és a kapcsolódó termék (related_*) nyersanyagot.
"""

from dataclasses import dataclass

from app.core.qdrant import get_qdrant


def normalize_url(url: str | None) -> str:
    """page_url_norm: hash/query/trailing-slash strip — prod Normalize Input."""
    u = str(url or "")
    u = u.split("#", 1)[0].split("?", 1)[0]
    return u.rstrip("/")


@dataclass
class CurrentProduct:
    text: str
    related_similar: str = ""
    related_additional: str = ""


async def get_current_product(client_id: str, page_url_norm: str) -> CurrentProduct | None:
    """Ha a látogató egy termékoldalon van, a megnyitott termék adatlapja a page_url_norm alapján."""
    if not page_url_norm:
        return None
    qdrant = get_qdrant()
    point = await qdrant.find_by_url(client_id, page_url_norm)
    if not point:
        return None
    p = point.get("payload", {}) or {}
    if p.get("type") != "product" or not p.get("text"):
        return None
    return CurrentProduct(
        text=str(p.get("text") or ""),
        related_similar=str(p.get("related_similar") or ""),
        related_additional=str(p.get("related_additional") or ""),
    )

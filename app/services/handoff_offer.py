"""Élő átadás felajánlása (m32) — PURE modul, nincs app-függősége.

Miért kell:
  - a `detect_handoff` csak akkor kapcsol, ha a látogató MAGA kéri az embert
    (`ugyintezo/kollega/munkatars` + ige). Ha a bot ajánlja fel az átadást és a
    látogató annyit ír: „igen", az a régi mintákra NEM illeszkedik -> zsákutca.
  - a statikus tenant-prompt nem tudhatja, hogy ÉPP van-e online ügyintéző,
    ezért a felajánlást a kód fűzi a promptba, futásidőben.

A kör bezárása: a `prompt_block()` PONTOSAN azt a mondatot íratja a bottal, amit
az `OFFER_RE` felismer. A két oldalt teszt köti össze (round-trip), hogy a mondat
átfogalmazása ne törje csendben az átadást.
"""

import re
import unicodedata

# A bot pontosan ezt a mondatot kapja utasításba (tegező / magázó változat).
OFFER_SENTENCE_INFORMAL = "Szeretnéd, hogy átadjam egy élő munkatársnak?"
OFFER_SENTENCE_FORMAL = "Szeretné, hogy átadjam egy élő munkatársnak?"

# A felajánlás felismerése a bot ELŐZŐ üzenetében (ékezet-mentesített alakon).
OFFER_RE = re.compile(r"atadjam egy elo munkatars")

# Rábólintás a látogatótól. Az üzenet ELEJÉN kell állnia, hogy a
# „nem szeretnék ügyintézőt" ne csússzon át.
AFFIRM_RE = re.compile(
    r"^\s*(igen|ja|persze|rendben|ok|oke|okay|jo|jol van|hogyne|kerem|kerlek|"
    r"szeretnem|szeretnek|csinald|add at|kapcsolj|legyen|mehet)\b"
)


def fold(s: str) -> str:
    """lowercase + ékezet-strip (NFD). Ugyanaz, mint az intent._ascii_fold."""
    s = str(s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _turn(h) -> tuple[str, str]:
    """History-elem -> (role, content). Pydantic-objektum és dict is jöhet."""
    role = getattr(h, "role", None)
    content = getattr(h, "content", None)
    if role is None and isinstance(h, dict):
        role = h.get("role")
        content = h.get("content")
    return str(role or ""), str(content or "")


def bot_offered_handoff(history) -> bool:
    """A bot LEGUTÓBBI üzenete felajánlotta-e az élő átadást?

    Csak a legutolsó assistant-fordulót nézzük: egy három körrel korábbi
    felajánlásra adott „igen" már másra vonatkozik.
    """
    for h in reversed(list(history or [])):
        role, content = _turn(h)
        if role == "assistant":
            return bool(OFFER_RE.search(fold(content)))
    return False


def is_affirmative(message: str) -> bool:
    """Rábólintás-e ("igen", "rendben", "kérem szépen"...)."""
    return bool(AFFIRM_RE.match(fold(message)))


def accepted_offer(message: str, history) -> bool:
    """A látogató igent mondott egy FELAJÁNLOTT élő átadásra."""
    return bot_offered_handoff(history) and is_affirmative(message)


def prompt_block(informal: bool = True) -> str:
    """A promptba fűzött blokk — CSAK akkor, ha épp van online ügyintéző."""
    sentence = OFFER_SENTENCE_INFORMAL if informal else OFFER_SENTENCE_FORMAL
    return (
        "\n\n# ELO UGYINTEZO\n"
        "Most van elerheto elo munkatars. Ha nem tudsz pontos valaszt adni, vagy a latogato "
        "panaszt, reklamaciot, surgos vagy egyedi ugyet jelez: NE e-mail-cimet kerj, hanem "
        "ajanld fel az elo atadast. A felajanlas ZARO mondata pontosan ez legyen, szo szerint:\n"
        f'"{sentence}"\n'
        "Ilyenkor a collect_lead legyen false. Ha a latogato igennel valaszol, a rendszer "
        "automatikusan atadja egy munkatarsnak — neked semmi tovabbi teendod nincs."
    )

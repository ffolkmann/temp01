"""Operátor-nyitvatartás + elérhetőség-gating (m28 fázis6).

Az élő operátor-átvétel csak akkor aktiválódik, ha (a) van beállított Telegram-címzett
ÉS (b) épp nyitvatartási időben vagyunk. Egyébként a régi e-mailes handoffra esünk vissza,
hogy a látogató ne várjon hiába egy operátorra, aki nincs ott / nem is kap értesítést.

operator_hours JSONB séma (az admin állítja):
  {"tz": "Europe/Budapest",
   "mon": ["09:00", "17:00"], "tue": [...], ..., "sat": null, "sun": null}

Szabályok:
- Nincs operator_hours (üres/None)                         -> 24/7 nyitva (True).
- Rossz top-szintű formátum (nem dict)                     -> nem blokkolunk (True).
- Az aznapi kulcs null / hiányzik / nem [nyit, zár] lista  -> aznap zárva (False).
- Az intervallum idő-formátuma hibás (nem HH:MM)           -> nem blokkolunk (True).
- Ismeretlen tz / hiányzó tzdata                           -> UTC-re esünk vissza (warning).
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("cx.operator_hours")

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # datetime.weekday(): mon=0
_DEFAULT_TZ = "Europe/Budapest"


def _now_in_tz(tz: str, now: datetime | None) -> datetime:
    if now is not None:
        return now
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz or _DEFAULT_TZ))
    except Exception:  # noqa: BLE001 — ismeretlen tz / hiányzó tzdata
        logger.warning("operator_hours: ismeretlen tz=%r, UTC-re esünk vissza", tz)
        return datetime.now(timezone.utc)


def _minutes(hhmm) -> int | None:
    try:
        h, m = str(hhmm).strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:  # noqa: BLE001
        return None


def is_open(operator_hours, now: datetime | None = None) -> bool:
    """Nyitvatartásban vagyunk-e MOST. Nincs beállítva -> True (24/7)."""
    if not operator_hours:
        return True
    if isinstance(operator_hours, str):
        try:
            operator_hours = json.loads(operator_hours) if operator_hours.strip() else None
        except Exception:  # noqa: BLE001
            return True
    if not isinstance(operator_hours, dict) or not operator_hours:
        return True
    tz = operator_hours.get("tz") or _DEFAULT_TZ
    n = _now_in_tz(tz, now)
    interval = operator_hours.get(_DAYS[n.weekday()])
    if not isinstance(interval, (list, tuple)) or len(interval) != 2:
        return False  # aznap zárva (null / hiányzó / rossz típus)
    o = _minutes(interval[0])
    c = _minutes(interval[1])
    if o is None or c is None:
        return True  # hibás idő-formátum -> ne blokkoljunk
    cur = n.hour * 60 + n.minute
    if c <= o:
        # éjfélen átnyúló vagy elrontott intervallum -> nyitva a nap végéig
        return cur >= o
    return o <= cur < c


def _has_telegram(tenant) -> bool:
    raw = getattr(tenant, "operator_telegram_chat_id", None)
    return bool(raw and str(raw).strip())


def operators_available(tenant, now: datetime | None = None) -> bool:
    """Élő átvétel felkínálható-e MOST: van Telegram-címzett ÉS nyitvatartásban vagyunk.

    0 címzett -> False (senki sem kapna értesítést -> ne nyeljük el a vevőt élőben).
    Fail-safe: kivételt nem dob.
    """
    if not _has_telegram(tenant):
        return False
    return is_open(getattr(tenant, "operator_hours", None), now)

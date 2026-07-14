"""Operátor-nyitvatartás (app/services/operator_hours.py) — izolátor tesztek.

A modul csak stdlib-et importál (nincs app-függőség), ezért fájlból töltjük, stubok
nélkül. Fix `now`-t adunk -> determinisztikus és tzdata-független (a ZoneInfo nem hívódik).
"""

import importlib.util
import json
import pathlib
from datetime import datetime
from types import SimpleNamespace

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "operator_hours_uut", _ROOT / "app" / "services" / "operator_hours.py"
)
oh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oh)

WED_15 = datetime(2026, 7, 8, 15, 0)    # szerda 15:00
WED_20 = datetime(2026, 7, 8, 20, 0)    # szerda 20:00
WED_0830 = datetime(2026, 7, 8, 8, 30)  # szerda 08:30 (nyitás előtt)
SAT_12 = datetime(2026, 7, 11, 12, 0)   # szombat 12:00

HOURS = {
    "tz": "Europe/Budapest",
    "mon": ["09:00", "17:00"], "tue": ["09:00", "17:00"], "wed": ["09:00", "17:00"],
    "thu": ["09:00", "17:00"], "fri": ["09:00", "17:00"], "sat": None, "sun": None,
}


# --------------------------------------------------------------------------- #
# is_open
# --------------------------------------------------------------------------- #
def test_no_hours_24_7():
    assert oh.is_open(None) is True
    assert oh.is_open({}) is True
    assert oh.is_open("") is True


def test_open_within():
    assert oh.is_open(HOURS, WED_15) is True


def test_closed_after():
    assert oh.is_open(HOURS, WED_20) is False


def test_closed_before_open():
    assert oh.is_open(HOURS, WED_0830) is False


def test_closed_day():
    assert oh.is_open(HOURS, SAT_12) is False


def test_json_string_input():
    assert oh.is_open(json.dumps(HOURS), WED_15) is True


def test_bad_toplevel_not_blocking():
    assert oh.is_open("nem-json{", WED_15) is True  # rossz JSON -> ne blokkolj


def test_missing_day_closed():
    assert oh.is_open({"tz": "Europe/Budapest"}, WED_15) is False  # nincs 'wed' -> zárva


def test_bad_interval_time_not_blocking():
    assert oh.is_open({"wed": ["9am", "5pm"]}, WED_15) is True  # rossz idő -> ne blokkolj


def test_boundary_open_close():
    assert oh.is_open(HOURS, datetime(2026, 7, 8, 9, 0)) is True     # 09:00 nyit -> benne
    assert oh.is_open(HOURS, datetime(2026, 7, 8, 17, 0)) is False   # 17:00 zár -> kint


# --------------------------------------------------------------------------- #
# operators_available (Telegram-címzett + nyitvatartás)
# --------------------------------------------------------------------------- #
def test_avail_no_telegram_still_available():
    # m42: a Telegram-cimzett nem feltetel -- ures chat_id-val is elerheto az elo atvetel
    t = SimpleNamespace(operator_telegram_chat_id="", operator_hours=None)
    assert oh.operators_available(t, WED_15) is True


def test_avail_no_telegram_closed_hours_blocks():
    # a nyitvatartas tovabbra is kapu marad
    t = SimpleNamespace(operator_telegram_chat_id="", operator_hours=HOURS)
    assert oh.operators_available(t, WED_20) is False


def test_avail_telegram_open():
    t = SimpleNamespace(operator_telegram_chat_id="123", operator_hours=HOURS)
    assert oh.operators_available(t, WED_15) is True


def test_avail_telegram_closed():
    t = SimpleNamespace(operator_telegram_chat_id="123", operator_hours=HOURS)
    assert oh.operators_available(t, WED_20) is False


def test_avail_telegram_no_hours_24_7():
    t = SimpleNamespace(operator_telegram_chat_id="123", operator_hours=None)
    assert oh.operators_available(t, WED_20) is True  # nincs hours -> 24/7

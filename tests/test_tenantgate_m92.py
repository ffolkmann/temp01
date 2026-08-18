"""m92: a kikapcsolt tenant kapuja (active=false -> a bot nem valaszol, a widget nem jelenik meg)."""
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = os.environ.get("CHATBOT_ROOT") or str(Path(__file__).resolve().parents[1])
for n in ("app", "app.sync"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


gate = _load("tenantgate_m92", f"{ROOT}/app/services/tenantgate.py")


class _T:
    def __init__(self, active=True):
        self.active = active


def test_aktiv_tenant_nincs_kapuzva():
    assert gate.is_disabled(_T(True)) is False


def test_kikapcsolt_tenant_kapuzva():
    assert gate.is_disabled(_T(False)) is True


def test_ismeretlen_tenant_nem_disabled():
    """None-ra a regi ag el (widget-config alapertelmezett torzs) — nem valtozik a viselkedes."""
    assert gate.is_disabled(None) is False


def test_hianyzo_mezo_eseten_aktivnak_szamit():
    """Fail-safe: ha egy objektumon nincs `active`, NEM kapcsoljuk le."""
    assert gate.is_disabled(object()) is False


def test_nem_bool_ertekek():
    assert gate.is_disabled(_T(0)) is True
    assert gate.is_disabled(_T(None)) is True
    assert gate.is_disabled(_T(1)) is False

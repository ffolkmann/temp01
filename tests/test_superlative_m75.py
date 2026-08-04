"""m80b: accessory_filter monitor/projektor-zaj esetek (m75 szuro bovites).

Dual-import (m79c minta): app-import ha eleg a suite kornyezete, kulonben
fajl-betoltes -- igy fake-app-os suite-sorrendben is fut.
"""


def _load_accessory_filter():
    try:
        from app.services.superlative import accessory_filter
        return accessory_filter
    except Exception:
        import importlib.util
        import pathlib

        p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "superlative.py"
        spec = importlib.util.spec_from_file_location("sup_m75_fileload", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.accessory_filter


accessory_filter = _load_accessory_filter()


def test_accessory_filter_monitor_zaj_m80b():
    # notebook-temanal az Acer monitor kiszurodik a poolbol
    hits = [
        {"payload": {"name": "Acer Nitro VG240Y Monitor 23.8\" IPS", "type": "product"}},
        {"payload": {"name": "Acer Aspire 3 Notebook 15.6\" Ryzen 5", "type": "product"}},
    ]
    out = accessory_filter(hits, "legolcsobb acer notebook")
    assert len(out) == 1 and "Aspire" in out[0]["payload"]["name"]


def test_accessory_filter_monitor_tema_nem_szur_m80b():
    # ha a tema MAGA a monitor, nem szurunk (a _DEVICE_RE nem matchel)
    hits = [{"payload": {"name": "Acer Nitro VG240Y Monitor", "type": "product"}}]
    out = accessory_filter(hits, "legolcsobb monitor")
    assert len(out) == 1


def test_accessory_filter_projektor_zaj_m80b():
    hits = [
        {"payload": {"name": "Epson EB-X06 projektor XGA", "type": "product"}},
        {"payload": {"name": "HP 250 G10 Notebook 15.6\"", "type": "product"}},
    ]
    out = accessory_filter(hits, "legolcsobb laptop")
    assert len(out) == 1 and "250" in out[0]["payload"]["name"]

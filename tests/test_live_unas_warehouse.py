"""Unas raktarankenti keszlet-note (m26) — eles XML-mintakbol."""
import xml.etree.ElementTree as ET

from app.services.live_product import _unas_wh_note

_PROD_XML = """<Product><Id>1138305179</Id><Sku>731717</Sku><Stocks>
<Stock><Qty>3</Qty><Price>2143</Price></Stock>
<Stock><WarehouseId>5865434</WarehouseId><IsActive>yes</IsActive><Qty>7</Qty></Stock>
<Stock><WarehouseId>5647099</WarehouseId><IsActive>no</IsActive><Qty>43</Qty></Stock>
<Stock><WarehouseId>6160206</WarehouseId><IsActive>yes</IsActive><Qty>0</Qty></Stock>
</Stocks></Product>"""

_WHMAP = {
    "5865434": ("Központi raktár (2 munkanap)", "feladás 2 munkanap"),
    "6160206": ("Beszállítói raktár", "4-6 munkanap"),
}


def _prod():
    return ET.fromstring(_PROD_XML)


def test_aktiv_qty_raktar_bekerul():
    note = _unas_wh_note(_prod(), _WHMAP, None)
    assert "Központi raktár (2 munkanap): 7 db" in note


def test_inaktiv_stock_szurve():
    note = _unas_wh_note(_prod(), _WHMAP, None)
    assert "43" not in note


def test_nulla_keszlet_szurve():
    note = _unas_wh_note(_prod(), _WHMAP, None)
    assert "Beszállítói" not in note


def test_ismeretlen_raktar_szurve():
    note = _unas_wh_note(_prod(), {"6160206": ("X", "")}, None)
    assert note == ""


def test_feluliro_nev():
    note = _unas_wh_note(_prod(), _WHMAP, {"5865434": {"name": "Saját raktár", "delivery": "1 munkanap"}})
    assert "Saját raktár: 7 db (1 munkanap)" in note


def test_info_nem_duplazodik_ha_nevben():
    note = _unas_wh_note(_prod(), {"5865434": ("Központi raktár (feladás 2 munkanap)", "feladás 2 munkanap")}, None)
    assert note.count("feladás 2 munkanap") == 1

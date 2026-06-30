"""build_text byte-paritás teszt — a reference/n8n-sync/ node-okkal ellenőrzött arany-stringek.
Futtatás: python tests/test_sync_parity.py

Az elvárt stringeket a Node node-ok produkálták (scratchpad/parity_node.js), itt golden-ként
rögzítve, hogy node nélkül is fusson. Ellenőrzi: entity-dekód, NBSP huf, em-dash, truncate, CSV.
"""
import importlib.util
import sys
import types

ROOT = "/home/folkm/chatbot"
for n in ("app", "app.sync"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


_load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
_load("app.sync.textutil", f"{ROOT}/app/sync/textutil.py")
_load("app.sync.models", f"{ROOT}/app/sync/models.py")
b = _load("app.sync.builders", f"{ROOT}/app/sync/builders.py")

NB = " "  # NBSP (hu-HU ezres-elválasztó)

SELLVIO_IN = [
    {"id": 123, "code": "TSL1", "name": "Teszt Termék <b>X</b>", "pretty_url": "https://shop.hu/p/1",
     "price": {"brutto_price": 80600}, "brand": {"name": "TESERY"},
     "categories": {"c1": {"name": "Felni"}, "c2": {"name": "Tartozék"}},
     "lead_text": "Rövid &amp; jó leírás", "description": "Hosszú leírás <p>html</p> &nbsp; vége", "is_visible": True},
    {"id": 7, "code": "A7", "name": "Olcsó cucc", "pretty_url": "", "price": {"brutto_price": 1235},
     "brand": None, "categories": {}, "lead_text": "", "description": "", "is_visible": True},
]
SELLVIO_GOLD = [
    f"Teszt Termék <b>X</b> — 80{NB}600 Ft. Márka: TESERY. Kategória: Felni, Tartozék. "
    "Rövid & jó leírás. Hosszú leírás html vége. Link: https://shop.hu/p/1",
    "Olcsó cucc — 1235 Ft",
]

WOO_IN = [
    {"id": 55, "sku": "W55", "name": "Woo Termék", "permalink": "https://woo.hu/t", "price": "12345",
     "on_sale": True, "sale_price": "9990", "brands": [{"name": "Acme"}],
     "categories": [{"id": 1, "name": "Kat1"}, {"id": 2, "name": "Kat2"}],
     "short_description": "Rövid <i>le</i>", "description": "Hosszú &amp; le",
     "attributes": [{"name": "Szín", "options": ["Piros", "Kék"]}], "manage_stock": True, "stock_quantity": 5},
    {"id": 56, "sku": "W56", "name": "Nincs ár", "permalink": "", "price": "", "brands": [], "categories": [],
     "short_description": "", "description": "", "attributes": [], "stock_status": "outofstock"},
]
WOO_GOLD = [
    "Woo Termék — 9990 Ft (készlet: 5 db). Márka: Acme. Kategória: Kat1, Kat2. "
    "Rövid le. Hosszú & le. Paraméterek: Szín: Piros, Kék. Link: https://woo.hu/t",
    "Nincs ár (jelenleg nincs raktáron)",
]

UNAS_CSV = (
    "Cikkszám;Termék Név;Bruttó Ár;Kategória;Rövid Leírás;Tulajdonságok;Termék link;Raktárkészlet;Gyártó\n"
    '169059;Unas Cucc;4 990;Kategória A;"Rövid &amp; le";Hosszú le;https://u.hu/x;10.000;UnasBrand\n'
    "X2;Másik;1235;;;;;;\n"
)
UNAS_GOLD = [
    "Unas Cucc — 4990 Ft (Kategória A). Készlet: 10 db. Rövid & le. Hosszú le. Márka: UnasBrand",
    "Másik — 1235 Ft",
]


def check(label, products, gold):
    texts = [p.text for p in products]
    assert texts == gold, f"{label}:\n  GOT : {texts!r}\n  GOLD: {gold!r}"
    print(f"OK  {label} build_text byte-egyezés ({len(texts)} db)")


check("sellvio", b.build_sellvio(SELLVIO_IN, "c"), SELLVIO_GOLD)
check("woocommerce", b.build_woo(WOO_IN, "c"), WOO_GOLD)
check("unas", b.build_unas(UNAS_CSV, "c", ""), UNAS_GOLD)

# Sellvio kategória-SORREND: JS Object.keys (egész kulcsok növekvő numerikusan), NEM JSON-sorrend.
# Bizonyíték (prod 6769): kulcsok 1002,1176,1004,1367 -> JS: 1002,1004,1176,1367.
CATORDER_IN = [{
    "id": 6769, "code": "P6769", "name": "Kategoriás termék", "pretty_url": "https://shop.hu/p/6769",
    "price": {"brutto_price": 50000}, "brand": None, "lead_text": "", "description": "", "is_visible": True,
    "categories": {"1002": {"name": "C1002"}, "1176": {"name": "C1176"},
                   "1004": {"name": "C1004"}, "1367": {"name": "C1367"}},
}]
CATORDER_GOLD = [f"Kategoriás termék — 50{NB}000 Ft. Kategória: C1002, C1004, C1176, C1367. Link: https://shop.hu/p/6769"]
check("sellvio-catorder", b.build_sellvio(CATORDER_IN, "c"), CATORDER_GOLD)
assert b._js_key_order({"1002": 1, "1176": 1, "1004": 1, "1367": 1}) == ["1002", "1004", "1176", "1367"]
assert b._js_key_order({"b": 1, "10": 1, "2": 1, "a": 1}) == ["2", "10", "b", "a"]   # int-kulcsok elöl, többi insertion
print("OK  _js_key_order: egész-kulcsok numerikusan + string-kulcsok beillesztési sorrendben")

# payload-kulcsok + platform-specifikumok
sv = b.build_sellvio(SELLVIO_IN, "c")[0]
assert sv.platform_id_field == "sellvio_id" and sv.platform_id_value == "123"
assert sv.content_hash and sv.stock_str == ""           # Sellvio: nincs stock a payloadban
wo = b.build_woo(WOO_IN, "c")[0]
assert wo.platform_id_field == "wc_id" and wo.platform_id_value == "55"
un = b.build_unas(UNAS_CSV, "c", "")[0]
assert un.platform_id_field == "" and un.stock_str == "10"   # Unas: stock VAN, platform-id nincs
assert un.id_key == "169059"
print("OK  payload-specifikumok (Sellvio/Woo platform-id; Unas stock + id_key=sku)")

# huf: minimumGroupingDigits=2 (4 jegy nincs csoportosítva, 5+ NBSP)
from app.sync.textutil import huf  # noqa: E402
assert huf(1235) == "1235" and huf(12345) == f"12{NB}345" and huf(1000000) == f"1{NB}000{NB}000"
print("OK  huf NBSP + minimumGroupingDigits=2")

print("\nALL GOOD")

"""build_text byte-paritás teszt — a reference/n8n-sync/ node-okkal ellenőrzött arany-stringek.
Futtatás: python tests/test_sync_parity.py

Az elvárt stringeket a Node node-ok produkálták (scratchpad/parity_node.js), itt golden-ként
rögzítve, hogy node nélkül is fusson. Ellenőrzi: entity-dekód, NBSP huf, em-dash, truncate, CSV.
"""
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


_load("app.sync.hashing", f"{ROOT}/app/sync/hashing.py")
_load("app.sync.textutil", f"{ROOT}/app/sync/textutil.py")
models = _load("app.sync.models", f"{ROOT}/app/sync/models.py")
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
    # m22: on_sale terméknél AKCIÓS jelölés (a fixture-ben nincs regular_price -> nincs eredeti ár rész)
    "Woo Termék — 9990 Ft (AKCIÓS ár) (készlet: 5 db). Márka: Acme. Kategória: Kat1, Kat2. "
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

# m23: Sellvio AKCIOS - a brutto_price az akcios ar, a discount a kedvezmeny brutto
# osszege STRINGKENT (elo minta: plcomfort #3576, is_special=false mellett!).
SELLVIO_AKCIOS_IN = [{
    "id": 3576, "code": "AKC1", "name": "Akciós klíma", "pretty_url": "https://shop.hu/p/3576",
    "price": {"netto_price": 11331.5, "vat": 27, "brutto_price": 14391, "discount": "1599"},
    "brand": None, "categories": {}, "lead_text": "", "description": "", "is_visible": True,
}]
SELLVIO_AKCIOS_GOLD = [f"Akciós klíma — 14{NB}391 Ft (AKCIÓS ár, eredeti ár: 15{NB}990 Ft). Link: https://shop.hu/p/3576"]
check("sellvio-akcios", b.build_sellvio(SELLVIO_AKCIOS_IN, "c"), SELLVIO_AKCIOS_GOLD)
_ak = b.build_sellvio(SELLVIO_AKCIOS_IN, "c")[0]
_no = b.build_sellvio(SELLVIO_IN, "c")[0]
assert _ak.ps_hash_str == b.ps_hash(_ak.price, "", "1599"), "akciosnal a discount a ps_hash-ben"
assert _no.ps_hash_str == b.ps_hash(_no.price, "", ""), "nem-akciosnal a ps_hash VALTOZATLAN formula"
# m24: Sellvio pretty_url INSTABIL host (hol egyedi domain, hol <shop>.mysellvio.com) ->
# public_url-lel normalizalunk. Ket kulonbozo hostu bemenetnek AZONOS text/content_hash-t
# kell adnia; public_url nelkul a viselkedes byte-valtozatlan (parity-golds fent).
_UIN_A = [{"id": 9, "code": "U9", "name": "Url Termék", "pretty_url": "https://shop.mysellvio.com/hu/url-termek/termek/9",
           "price": {"brutto_price": 1000}, "brand": None, "categories": {}, "lead_text": "", "description": "", "is_visible": True}]
_UIN_B = [{**_UIN_A[0], "pretty_url": "https://shop.hu/hu/url-termek/termek/9"}]
_ua = b.build_sellvio(_UIN_A, "c", "https://shop.hu")[0]
_ub = b.build_sellvio(_UIN_B, "c", "https://shop.hu/")[0]
assert _ua.url == _ub.url == "https://shop.hu/hu/url-termek/termek/9", f"url norm: {_ua.url!r} / {_ub.url!r}"
assert _ua.text == _ub.text and _ua.content_hash == _ub.content_hash, "host-flip nem okozhat content-driftet"
assert b.build_sellvio(_UIN_A, "c")[0].url == "https://shop.mysellvio.com/hu/url-termek/termek/9", "public_url nelkul valtozatlan"
print("OK  sellvio-urlnorm: host-normalizálás public_url-re, hash stabil")

# m24: SR raktár-szemantika helper — (stock_str, note) a warehouse_config szerint
_WH = {"own": "2", "external": "3", "own_delivery": "2 munkanap", "external_delivery": "4-5 munkanap"}
_st, _nt = b.sr_warehouse_note({"stock1": "0", "stock2": "6", "stock3": "0", "stock4": "0"}, _WH)
assert (_st, _nt) == ("6", "saját raktáron: 6 db, szállítás: 2 munkanap"), (_st, _nt)
_st, _nt = b.sr_warehouse_note({"stock1": "1", "stock2": "2", "stock3": "4"}, _WH)
assert _st == "7" and _nt == "saját raktáron: 2 db, szállítás: 2 munkanap; külső raktáron: 4 db, szállítás: 4-5 munkanap; egyéb raktáron: 1 db", (_st, _nt)
_st, _nt = b.sr_warehouse_note({"stock1": "5"}, None)
assert (_st, _nt) == ("5", "")            # config nélkül: csak összeg, note nincs
_st, _nt = b.sr_warehouse_note({}, _WH)
assert (_st, _nt) == ("", "")             # nincs stock-mező: üres
print("OK  sr-warehouse-note: saját/külső/egyéb bontás + szállítási idő")
_WH2 = {"warehouses": {"2": {"name": "saját raktár", "delivery": "2 munkanap"},
                       "3": {"name": "külső raktár", "delivery": "4-5 munkanap"}}}
_st, _nt = b.sr_warehouse_note({"stock2": "6", "stock3": "2"}, _WH2)
assert (_st, _nt) == ("8", "saját raktár: 6 db, szállítás: 2 munkanap; külső raktár: 2 db, szállítás: 4-5 munkanap"), (_st, _nt)
_st, _nt = b.sr_warehouse_note({"stock1": "3", "stock4": "1"}, _WH2)
assert (_st, _nt) == ("4", "egyéb raktáron: 4 db"), (_st, _nt)   # be nem sorolt raktárak
_st, _nt = b.sr_warehouse_note({"stock2": "0", "stock3": "5"}, {"warehouses": {"3": {"name": "beszállítói raktár", "delivery": "1 hét"}}})
assert _nt == "beszállítói raktár: 5 db, szállítás: 1 hét", _nt
print("OK  sr-warehouse-note: nevesített (warehouses) séma + kompat")

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

# Webdoc — SPEC-golden (a reference node hiányában a megadott spec alapján kézzel számolva).
# FLAG: a feed MEZŐNEVEI feltételezések; egy valós notebookstore termékkel megerősítendők.
WEBDOC_IN = [
    {"id": 12691, "name": "Laptop X", "price_gross": 250000, "available": True, "brand": "Asus",
     "category_path": "Számítástechnika>Laptop>Gamer", "description": "Erős <b>gép</b> &amp; jó",
     "parameters": [{"name": "RAM", "value": "16GB"}, {"name": "Nyelv", "value": ["Magyar", "Angol"]}],
     "url": "https://notebookstore.hu/p/12691", "sku": "NB12691"},
    {"id": 99, "name": "Kábel", "price_gross": 1990, "available": False, "brand": "",
     "category": "Tartozék", "description": "", "parameters": [], "url": "", "sku": "NB99"},
]
WEBDOC_GOLD = [
    f"Laptop X — 250{NB}000 Ft (raktáron). Márka: Asus. Kategória: Számítástechnika > Laptop > Gamer. "
    "Erős gép & jó. Paraméterek: RAM: 16GB; Nyelv: Magyar,Angol. Link: https://notebookstore.hu/p/12691",
    "Kábel — 1990 Ft (jelenleg nincs raktáron). Kategória: Tartozék",
]
# rendezés id szerint: 99 elöl, 12691 utána; price_gross; parameters[].value lista -> 'Magyar,Angol'
wd = b.build_webdoc(WEBDOC_IN, "c")
assert [p.id_key for p in wd] == ["99", "12691"], [p.id_key for p in wd]
assert [p.text for p in wd] == [WEBDOC_GOLD[1], WEBDOC_GOLD[0]], [p.text for p in wd]
# payload-extra: webdoc_id, available, ps_hash; price = price_gross
plw = models.build_payload("c", [p for p in wd if p.id_key == "12691"][0])
assert plw["webdoc_id"] == "12691" and plw["available"] is True and plw["ps_hash"] and plw["price"] == "250000"
assert plw["filename"] == "__webdoc_products__" and "stock" not in plw
# strict available (===true): a truthy non-bool 1 NEM raktáron
strict = b.build_webdoc([{"id": "1", "name": "X", "price_gross": 100, "available": 1}], "c")[0]
assert "jelenleg nincs raktáron" in strict.text and strict.available is False
# _js_str: lista -> vesszős JS-coercion, NEM Python repr
assert b._js_str(["a", "b"]) == "a,b" and b._js_str(True) == "true" and b._js_str(2.0) == "2"
print("OK  webdoc: price_gross + parameters JS-coercion + strict available + payload-extra (node-igazolt)")

# Webdoc entity-dekód (csak a description megy strip_webdoc-on át; name/brand/category/params NYERS,
# ahogy a node is hagyja). Numerikus &#225;/&#x151;, magyar named entity, ismeretlen &unknownx; marad.
ENT_IN = [{
    "id": "1", "name": "&aacute;rva &oacute;l&oacute;m &hellip;", "price_gross": 12345, "available": True,
    "brand": "K&amp;M", "category_path": "El&eacute;ktro &gt; Akkuk",
    "description": "&Aacute;tl&aacute;tsz&oacute; h&#225;z &#x151; &amp; <b>v&eacute;ge</b> &unknownx;",
    "parameters": [{"name": "Sz&iacute;n", "value": ["Piros", "K&eacute;k"]}], "url": "https://x.hu/1", "sku": "S1",
}]
ENT_GOLD = [
    f"&aacute;rva &oacute;l&oacute;m &hellip; — 12{NB}345 Ft (raktáron). Márka: K&amp;M. "
    "Kategória: El&eacute;ktro &gt; Akkuk. Átlátszó ház ő & vége &unknownx;. "
    "Paraméterek: Sz&iacute;n: Piros,K&eacute;k. Link: https://x.hu/1"
]
check("webdoc-entities", b.build_webdoc(ENT_IN, "c"), ENT_GOLD)
# a richer dec a description-re hat (Átlátszó/ő/&), de név/márka/kategória/param NYERS marad
from app.sync.textutil import dec_webdoc, strip_full  # noqa: E402
assert dec_webdoc("&#225; &#x151; &amp; &unknownx;") == "á ő & &unknownx;"
assert strip_full("&#8217;") == "'"        # Sellvio/Woo dec VÁLTOZATLAN (nem ’)
print("OK  webdoc entity-dekód (numerikus+named, ismeretlen marad); a többi platform dec érintetlen")

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

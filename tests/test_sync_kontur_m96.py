"""m96: Kontúr Reklám sync-builder — feed (1 termék = 1 rekord, beágyazott variánsok) ->
SourceProduct + payload.

Amit rögzít:
  (1) text-alak: név — nettó X Ft-tól (raktáron). Márka. Kategória: A > B. leírás. Paraméterek. Link
  (2) a paramextract kinyeri a category/cat_tags payloadot ebből az alakból (m86 kapu él)
  (3) available = van raktáros variáns; stock = variánsok készlet-összege; price = min nettó ár
  (4) kifutó: termék-szintű -> "KIFUTÓ termék"; variáns-szintű -> "Kifutó színek: ..."; a kifutó
      variáns készlete BENT marad (a feed szerint 99%-uknak van készlete, rendelhetők)
  (5) content_hash NEM változik ár/készlet/kifutó váltásnál, a ps_hash IGEN (payload-merge,
      nincs újra-embedding)
  (6) kategória ' / ' szeparátor: a 'Pólók/T-Shirt' belső perjele nem bontja
  (7) sku vagy név nélkül / active=false kimarad; kontur_products a gyökér-alakokat kezeli

A m90-teszt mintájára fájl-betöltéssel (a suite más tesztjei fake app.sync-et hagyhatnak).
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
builders = _load("app.sync.builders", f"{ROOT}/app/sync/builders.py")

CID = "konturreklam"


def _n(s: str) -> str:
    """NBSP (huf ezres-elválasztó, csak 5 jegytől) -> szóköz, hogy az assert olvasható maradjon."""
    return s.replace("\xa0", " ")


def _var(color, size, price=1047, stock=100, disc=False, group="Piros"):
    return {"variant_sku": f"U gi5000{color[:3].lower()}-{size.lower()}", "color": color, "size": size,
            "price_net": price, "stock": stock, "discontinued": disc, "color_group": group}


def _prod(**kw):
    p = {
        "sku": "U GI5000",
        "name": "HEAVY COTTON™ FELNŐTT PÓLÓ",
        "url": "https://www.konturreklam.hu/textil-termekek/polok-t-shirt/heavy-cotton-felnott-polo-gi5000",
        "active": True,
        "price_net_from": 858,
        "variants": [
            _var("Antique Cherry Red", "S", 1047, 509),
            _var("Antique Cherry Red", "3XL", 1536, 30),
            _var("White", "S", 858, 2000, group="Fehér"),
            _var("White", "M", 858, 0, group="Fehér"),
        ],
        "category": "Textil termékek / Pólók/T-Shirt",
        "brand": "Gildan",
        "description": "100% amerikai pamut, 180 g/m². A Heavy Cotton széles színválasztékot kínál.",
        "image_url": "https://www.konturreklam.hu/upload/pics/products/utt-0/gi5000-4.jpg",
        "gender": "Unisex",
        "material": "100% Pamut, Pamut/Poliészter",
        "weight_gsm": 180,
        "origin": "Bangladesh, Honduras",
        "fit": "Körkötött",
        "discontinued": False,
        "sizes": ["S", "M", "3XL"],
        "colors": ["Antique Cherry Red", "White"],
        "updated_at": "2026-08-31T14:05:35+02:00",
    }
    p.update(kw)
    return p


def _one(p):
    out = builders.build_kontur([p], CID)
    assert len(out) == 1, out
    return out[0]


def test_text_shape_and_payload():
    sp = _one(_prod())
    t = _n(sp.text)
    assert t.startswith("HEAVY COTTON™ FELNŐTT PÓLÓ — nettó 858 Ft-tól (raktáron). Márka: Gildan. "
                        "Kategória: Textil termékek > Pólók/T-Shirt. 100% amerikai pamut"), t
    assert "Paraméterek: Nem: Unisex; Anyag: 100% Pamut, Pamut/Poliészter; Fazon: Körkötött; " \
           "Származási hely: Bangladesh, Honduras; Grammsúly: 180 g/m²; Méretek: S, M, 3XL; " \
           "Színek: Antique Cherry Red, White; Nettó ár: 858–1536 Ft; " \
           "Készlet: összesen 2539 db, 4 szín-méret variáns, ebből 3 raktáron" in t, t
    # a leírás záró pontja nem duplázódik a szegmens-elválasztóval
    assert "kínál. Paraméterek:" in t and ".. " not in t
    assert t.endswith(". Link: https://www.konturreklam.hu/textil-termekek/polok-t-shirt/"
                      "heavy-cotton-felnott-polo-gi5000"), t
    assert "KIFUTÓ" not in t and "Kifutó" not in t
    assert sp.id_key == "U GI5000" and sp.sku == "U GI5000"
    assert sp.price == "858" and sp.stock_str == "2539" and sp.available is True
    assert sp.brand == "Gildan" and sp.filename == "__kontur_products__"
    assert sp.platform_id_field == "" and sp.content_hash and sp.ps_hash_str
    pl = models.build_payload(CID, sp)
    assert pl["type"] == "product" and pl["available"] is True and pl["stock"] == "2539"
    assert pl["price"] == "858" and pl["ps_hash"] == sp.ps_hash_str
    # (2) m86 kategória-kapu adata a paramextractból
    assert pl.get("category") == "Textil termékek > Pólók/T-Shirt", pl.get("category")
    assert "cat_tags" in pl and any("Textil" in x or "T-Shirt" in x or "Pólók" in x for x in pl["cat_tags"]), pl["cat_tags"]


def test_category_gate_without_brand():
    sp = _one(_prod(brand=""))
    pl = models.build_payload(CID, sp)
    assert ". Márka:" not in sp.text
    assert pl.get("category") == "Textil termékek > Pólók/T-Shirt"


def test_all_zero_stock_is_unavailable():
    p = _prod(variants=[_var("White", "S", 858, 0), _var("White", "M", 858, 0)])
    sp = _one(p)
    assert sp.available is False and sp.stock_str == "0"
    assert "(jelenleg nincs raktáron)" in sp.text
    assert models.build_payload(CID, sp)["available"] is False


def test_discontinued_product_and_variants():
    # termék-szintű kifutó: minden variáns kifutó -> KIFUTÓ termék, a készlet MARAD
    p = _prod(discontinued=True, variants=[_var("Navy", "S", 900, 50, disc=True),
                                           _var("Navy", "M", 900, 60, disc=True)])
    sp = _one(p)
    assert "KIFUTÓ termék — csak a készlet erejéig rendelhető" in sp.text
    assert sp.available is True and sp.stock_str == "110"
    # variáns-szintű: csak a színek
    p2 = _prod(variants=[_var("Navy", "S", 900, 50, disc=True), _var("Navy", "M", 900, 5, disc=True),
                         _var("White", "S", 858, 10)])
    sp2 = _one(p2)
    assert "Kifutó színek (csak a készlet erejéig): Navy" in sp2.text
    assert "KIFUTÓ termék" not in sp2.text


def test_hash_split_static_vs_dynamic():
    a = _one(_prod())
    # készlet/ár/kifutó változás -> content_hash AZONOS, ps_hash MÁS
    b = _one(_prod(variants=[_var("White", "S", 858, 1)]))
    assert a.content_hash == b.content_hash
    assert a.ps_hash_str != b.ps_hash_str
    c = _one(_prod(discontinued=True))
    assert a.content_hash == c.content_hash and a.ps_hash_str != c.ps_hash_str
    # leírás változás -> content_hash MÁS
    d = _one(_prod(description="Más leírás."))
    assert a.content_hash != d.content_hash


def test_skip_and_root_shapes():
    assert builders.build_kontur([_prod(sku="")], CID) == []
    assert builders.build_kontur([_prod(name="")], CID) == []
    assert builders.build_kontur([_prod(active=False)], CID) == []
    root = {"generated_at": "x", "price_type": "net", "products": [_prod(), "junk"]}
    assert len(builders.kontur_products(root)) == 1
    assert len(builders.kontur_products([_prod(), _prod(sku="B")])) == 2
    assert builders.kontur_products({"data": []}) == [] and builders.kontur_products(None) == []
    # sku szerinti determinisztikus sorrend
    out = builders.build_kontur([_prod(sku="ZZ"), _prod(sku="AA")], CID)
    assert [o.sku for o in out] == ["AA", "ZZ"]


def test_price_fallback_and_long_colors():
    # variáns-ár nélkül a price_net_from a padló
    p = _prod(variants=[{"variant_sku": "x", "color": "Kék", "size": "S", "stock": 3}])
    sp = _one(p)
    assert sp.price == "858" and "nettó 858 Ft-tól" in sp.text
    # hosszú színlista levágva, a text nem nő a plafon fölé
    p2 = _prod(colors=[f"Szín {i}" for i in range(400)])
    sp2 = _one(p2)
    assert len(sp2.text) < 9100 and "Színek: Szín 0, " in sp2.text and sp2.text.count("Szín 399") == 0

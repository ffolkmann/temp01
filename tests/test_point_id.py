"""ShoprenterBuilder pont-ID teszt — id_key prioritizálás (sku > url > name).
Futtatás: python tests/test_point_id.py
"""
import base64
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
_load("app.sync.models", f"{ROOT}/app/sync/models.py")
builders = _load("app.sync.builders", f"{ROOT}/app/sync/builders.py")


def _sr_desc(name):
    return [{"id": base64.b64encode(b"product_description-language_id=1").decode(),
             "name": name, "shortDescription": "", "description": "", "parameters": ""}]


def sr_prod(sku="", url_alias="test", name="TestProduct"):
    return {
        "innerId": "42",
        "productDescriptions": _sr_desc(name),
        "urlAliases": [{"urlAlias": url_alias}] if url_alias else [],
        "status": "1",
        "orderable": "1",
        "productPrices": [{"gross": 100}],
        "stock1": "5",
        "sku": sku,
    }


def build_one(p):
    b = builders.ShoprenterBuilder("c", "https://shop.hu/")
    b.index([p])
    out = b.build([p])
    assert len(out) == 1, f"expected 1, got {len(out)}"
    return out[0]


def main():
    ok = []

    # sku prioritizált
    p_sku = build_one(sr_prod(sku="4711"))
    assert p_sku.id_key == "4711", f"got {p_sku.id_key!r}"
    ok.append("sku prioritizált: id_key == '4711'")

    # url fallback (nincs sku)
    p_url = build_one(sr_prod(sku="", url_alias="tablet-teszt"))
    assert p_url.id_key == "https://shop.hu/tablet-teszt", f"got {p_url.id_key!r}"
    ok.append("url fallback: id_key == url")

    # name fallback (nincs sku, nincs urlAlias)
    p_name = build_one(sr_prod(sku="", url_alias="", name="NameOnly"))
    assert p_name.id_key == "NameOnly", f"got {p_name.id_key!r}"
    ok.append("name fallback: id_key == name")

    for l in ok: print("OK ", l)
    print("\nALL GOOD")


main()

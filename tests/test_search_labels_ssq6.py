"""ssq/6: parameter-cimkek - indexcore params.json labels, qdrantout manifest labels,
shoprenter clean_label/merge_labels/fetch_attr_labels (fake klienssel). Fajlbol toltve."""
import asyncio
import importlib.util
import json
import os
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ic = _load("app/search/indexcore.py", "ssq6_indexcore")


def _prods():
    return [{"id": 1, "sku": "A", "name": "Termek A", "brand": "B", "category": "C", "price_gross": 10,
             "available": True, "url": "https://x.hu/a", "image_url": "", "created_day": 20000,
             "parameters": [{"name": "garancia", "value": "12"}, {"name": "technologia", "value": "Lezer"}]}]


def test_indexcore_params_labels_only_used_names():
    with tempfile.TemporaryDirectory() as tmp:
        ic.build_index("t", _prods(), tmp, "https://x.hu/", "", labels={"garancia": "Garancia", "nincs": "X"})
        p = json.load(open(os.path.join(tmp, "params.json"), encoding="utf-8"))
        assert p["labels"] == {"garancia": "Garancia"}
    with tempfile.TemporaryDirectory() as tmp:
        ic.build_index("t", _prods(), tmp, "https://x.hu/", "")
        p = json.load(open(os.path.join(tmp, "params.json"), encoding="utf-8"))
        assert "labels" not in p                       # cimke nelkul bitre a regi alak


SR = None
try:
    SR = _load("app/search/shoprenter.py", "ssq6_shoprenter")
except Exception:  # sandboxban nincs platform_api - a konteneres suite-ban van
    SR = None


def test_shoprenter_clean_and_merge_labels():
    if SR is None:
        return
    assert SR.clean_label("garido", "garido") is None
    assert SR.clean_label("garancia", "") is None
    assert SR.clean_label("garancia", "Garancia") == "Garancia"
    assert SR.clean_label("funkciok", "FUNKCI\u00d3K") == "Funkci\u00f3k"
    assert SR.clean_label("kellekanyagtipus", " Kell\u00e9kanyag  t\u00edpus ") == "Kell\u00e9kanyag t\u00edpus"
    m = SR.merge_labels({"garancia": "Garancia", "technologia": "Bolti"}, [{"name": "printer"}])
    assert m["garancia"] == "Garancia" and m["technologia"] == "Technol\u00f3gia"   # a profil cimkeje nyer
    assert SR.merge_labels({}, []) == {}


def test_shoprenter_fetch_attr_labels_fake_client():
    if SR is None:
        return
    import base64

    def b64(s):
        return base64.b64encode(s.encode()).decode()

    class _R:
        def __init__(self, body):
            self.status_code, self._b = 200, body

        def raise_for_status(self):
            pass

        def json(self):
            return self._b

    class _C:
        async def get(self, url, params=None, headers=None):
            if url.endswith("/listAttributes"):
                return _R({"items": [{"id": b64("listAttribute-attribute_id=61"), "name": "garancia"},
                                     {"id": b64("listAttribute-attribute_id=314"), "name": "garido"}]})
            return _R({"items": [
                {"name": "Garancia", "attribute": {"href": "https://x/listAttributes/" + b64("listAttribute-attribute_id=61")}},
                {"name": "garido", "attribute": {"href": "https://x/listAttributes/" + b64("listAttribute-attribute_id=314")}},
            ]})

    out = asyncio.run(SR.fetch_attr_labels("https://x", {}, _C()))
    assert out == {"garancia": "Garancia"}            # a garido (cimke == slug) kimarad

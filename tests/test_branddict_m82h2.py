"""m82h/2: a valodi Qdrant brand-ertekekbol epulo markaszotar tesztjei.

Fajl-betoltes (importlib), NEM app-import: a suite mas tesztjei fake app/
starlette modulokat hagyhatnak a sys.modules-ben (m73/m80b tanulsag).
"""
import importlib.util
import json
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bd = _load("cx_branddict_t", "app/services/branddict.py")
px = _load("cx_paramextract_t", "app/services/paramextract.py")

MAP = {
    "client_id": "t1",
    "max_words": 4,
    "brands": {
        "hp": {"vals": ["HP"], "n": 10, "av": 5},
        "asus": {"vals": ["Asus"], "n": 10, "av": 5},
        "msi": {"vals": ["MSI (Micro-Star International)"], "n": 3, "av": 2},
        "tp link": {"vals": ["TP-Link"], "n": 4, "av": 4},
        "carp": {"vals": ["Carp"], "n": 2, "av": 1},
        "carp expert": {"vals": ["Carp Expert"], "n": 7, "av": 7},
        "xiaomi": {"vals": ["Xiaomi"], "n": 5, "av": 5},
    },
}


@pytest.fixture()
def mapdir(tmp_path, monkeypatch):
    (tmp_path / "brand_map_t1.json").write_text(json.dumps(MAP), encoding="utf-8")
    monkeypatch.setenv("FACET_MAP_DIR", str(tmp_path))
    bd._cache.clear()
    return tmp_path


def _det(msg, mapdir):
    return bd.detect_brand(msg, bd.load_map("t1", str(mapdir)))


# --- betoltes ---------------------------------------------------------------

def test_load_map_missing_file(mapdir):
    assert bd.load_map("nincs_ilyen_tenant", str(mapdir)) is None


def test_load_map_ok(mapdir):
    m = bd.load_map("t1", str(mapdir))
    assert m and m["client_id"] == "t1" and "asus" in m["brands"]


def test_load_map_env_dir(mapdir):
    # map_dir nelkul a FACET_MAP_DIR env dont
    assert bd.load_map("t1") is not None


# --- felismeres -------------------------------------------------------------

def test_detect_ekezetes_es_nagybetus(mapdir):
    key, vals = _det("Van ASUS notebookotok?", mapdir)
    assert key == "asus" and vals == ["Asus"]


def test_detect_leghosszabb_nyer(mapdir):
    key, _ = _det("Carp expert quick change bothoz keresek alkatreszt", mapdir)
    assert key == "carp expert"


def test_detect_payload_ertek_a_terkepbol(mapdir):
    # a kezi _BRAND_PAYLOAD_ALIASES helyett a VALODI payload-ertek jon
    key, vals = _det("Van MSI laptopotok?", mapdir)
    assert key == "msi" and vals == ["MSI (Micro-Star International)"]


def test_detect_nincs_reszszo_talalat(mapdir):
    assert _det("asuszal szeretnek dolgozni", mapdir)[0] == ""
    assert _det("hpx kabel kell", mapdir)[0] == ""


def test_detect_email_kivagva(mapdir):
    # H2': az e-mail cim NEM ad markat
    assert _det("Irjatok a hp@valami.hu cimre", mapdir)[0] == ""


def test_detect_url_host_kivagva_de_utvonal_marad(mapdir):
    # H2': a HOST ki, az UTVONAL marad -- a beillesztett termek-URL-ben ott a marka
    assert _det("Nezd meg a hp.hu oldalt", mapdir)[0] == ""
    key, _ = _det("https://copygo.hu/xiaomi-mesh-system-ax3000-3-db", mapdir)
    assert key == "xiaomi"


def test_detect_ures_terkep(mapdir):
    assert bd.detect_brand("Van Asus laptopotok?", None) == ("", [])
    assert bd.detect_brand("Van Asus laptopotok?", {"brands": {}}) == ("", [])


# --- paramextract-integracio ------------------------------------------------

def test_constraints_slug_alak_a_linkfacetnek(mapdir):
    cons = px.detect_constraints("Mikorra varhato a TP-Link ES208GP szallitasa?", "t1")
    # a linkfacet a crawl-terkep marka-slugjaval matchel -> kotojeles alak
    assert cons["brand"] == "tp-link"
    assert cons["brand_vals"] == ["TP-Link"]


def test_constraints_tobbszavas_marka(mapdir):
    cons = px.detect_constraints("Carp expert bot erdekelne", "t1")
    assert cons["brand"] == "carp-expert"


def test_filter_a_valodi_payload_ertekekkel(mapdir):
    cons = px.detect_constraints("Van MSI laptopotok?", "t1")
    must = px.build_filter_conditions(cons)
    assert {"key": "brand", "match": {"any": ["MSI (Micro-Star International)"]}} in must


def test_fallback_client_id_nelkul(mapdir):
    # nincs client_id -> a mai kezi _BRANDS lista (valtozatlan viselkedes)
    cons = px.detect_constraints("Van Asus laptopotok?")
    assert cons.get("brand") == "asus" and "brand_vals" not in cons
    must = px.build_filter_conditions(cons)
    assert must and must[0]["key"] == "brand" and "Asus" in must[0]["match"]["any"]


def test_fallback_ismeretlen_tenant(mapdir):
    # nincs terkep-fajl -> fail-safe a kezi listara
    cons = px.detect_constraints("Van Asus laptopotok?", "nincs_ilyen_tenant")
    assert cons.get("brand") == "asus" and "brand_vals" not in cons


def test_szotarban_nem_szereplo_marka_nem_szur(mapdir):
    # VAN terkep -> AZ dont: amit a bolt nem arul (Lenovo), arra nem szurunk,
    # es NEM esunk vissza a kezi _BRANDS listara (az 0 talalatot + fallbacket adna)
    cons = px.detect_constraints("Van Lenovo laptopotok?", "t1")
    assert "brand" not in cons
    assert px.build_filter_conditions(cons) == []

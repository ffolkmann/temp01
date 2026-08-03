"""m79b: linkfacet egyseg-tesztek (fajl-betoltes, app-import nelkul)."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "linkfacet.py"
_spec = importlib.util.spec_from_file_location("linkfacet_m79b", _p)
lf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lf)

BASE = "https://notebookstore.hu"
CAT_BAG = "Kieg\u00e9sz\u00edt\u0151k > Notebook t\u00e1ska, h\u00e1tizs\u00e1k"
FMAP = {
    "categories": {
        "notebook-taska-hatizsak": {
            "url": "/kiegeszitok/notebook-taska-hatizsak-c114",
            "facets": {
                "maximalis-notebook-meret": {"133": 1, "156": 48, "160": 49, "170": 8, "173": 6, "180": 1},
                "taska-tipusa": {"valltaskakezitaska": 66, "hatizsak": 60, "toksleeve": 19},
                "szin": {"fekete": 90, "szurke": 33, "kek": 14},
                "anyag": {"szovet": 70},
            },
        },
        "uj-notebook": {
            "url": "/laptop-notebook/uj-notebook-c100",
            "facets": {"kijelzo-meret": {"156": 206}},
        },
    }
}


def test_meret_exact_173():
    u = lf.facet_link(BASE, [CAT_BAG, CAT_BAG], {"p_max_meret_gte": 17.3}, FMAP)
    assert u == BASE + "/kiegeszitok/notebook-taska-hatizsak-c114/maximalis-notebook-meret:173"


def test_meret_17_egesz_a_170_szurot_kapja():
    u = lf.facet_link(BASE, [CAT_BAG], {"p_max_meret_gte": 17.0}, FMAP)
    assert u.endswith("/maximalis-notebook-meret:170")


def test_meret_felfele_kerekit_letezo_ertekre():
    # 14.5 nincs a terkepben -> a legkisebb letezo >= 14.5 a 15.6
    u = lf.facet_link(BASE, [CAT_BAG], {"p_max_meret_gte": 14.5}, FMAP)
    assert u.endswith("/maximalis-notebook-meret:156")


def test_meret_tul_nagy_tipusra_esik_at():
    # 19" folott nincs szuro-ertek; a tipus a kovetkezo prioritas
    u = lf.facet_link(BASE, [CAT_BAG], {"p_max_meret_gte": 19.0, "p_tipus": "hatizsak"}, FMAP)
    assert u.endswith("/taska-tipusa:hatizsak")


def test_tipus_valltaska_ertek_map():
    u = lf.facet_link(BASE, [CAT_BAG], {"p_tipus": "valltaska"}, FMAP)
    assert u.endswith("/taska-tipusa:valltaskakezitaska")


def test_szin_csak_ha_letezik():
    u = lf.facet_link(BASE, [CAT_BAG], {"p_szin": "fekete"}, FMAP)
    assert u.endswith("/szin:fekete")
    assert lf.facet_link(BASE, [CAT_BAG], {"p_szin": "bordo"}, FMAP) is None


def test_max_egy_szuro_meret_nyer():
    u = lf.facet_link(
        BASE, [CAT_BAG], {"p_max_meret_gte": 17.3, "p_tipus": "hatizsak", "p_szin": "fekete"}, FMAP
    )
    assert u.endswith("/maximalis-notebook-meret:173")
    assert "taska-tipusa" not in u and "szin:" not in u


def test_ismeretlen_kategoria_none():
    assert lf.facet_link(BASE, ["Nyomtat\u00f3 > Toner"], {"p_szin": "fekete"}, FMAP) is None


def test_ures_bemenetek_none():
    assert lf.facet_link(BASE, [], {"p_szin": "fekete"}, FMAP) is None
    assert lf.facet_link(BASE, [CAT_BAG], {}, FMAP) is None
    assert lf.facet_link("", [CAT_BAG], {"p_szin": "fekete"}, FMAP) is None
    assert lf.facet_link(BASE, [CAT_BAG], {"p_szin": "fekete"}, None) is None


def test_top_category_leggyakoribb():
    cats = [CAT_BAG, CAT_BAG, "Nyomtat\u00f3 > Toner", ""]
    assert lf.top_category(cats) == CAT_BAG


def test_load_map_hianyzo_fajl_none(tmp_path):
    assert lf.load_map("nincsilyen", map_dir=str(tmp_path)) is None


def test_load_map_es_link(tmp_path):
    import json as _json

    p = tmp_path / "facet_map_notebookstore.json"
    p.write_text(_json.dumps(FMAP), encoding="utf-8")
    m = lf.load_map("notebookstore", map_dir=str(tmp_path))
    assert m is not None and "_idx" in m
    u = lf.facet_link(BASE, [CAT_BAG], {"p_max_meret_gte": 17.3}, m)
    assert u.endswith(":173")

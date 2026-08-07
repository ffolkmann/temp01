"""m86: kategoria-kinyeres MINDEN platform valodi text-alakjara + `cat_tags` resz-nevek.

Fajl-betoltes (app-import nelkul), a test_paramextract_m79c mintajara -- a suite mas
tesztjei fake app.services-t hagyhatnak a sys.modules-ben.

A minta-textek VALODI Qdrant-payloadok (recon 2026-08-07, tools/m86_catprobe.py +
tools/m86_fpdiag.py).
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "paramextract.py"
_spec = importlib.util.spec_from_file_location("paramextract_m86", _p)
px = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(px)

WEBDOC = ("HP 312A Yellow (S\u00e1rga) LaserJet toner (CF382A) \u2014 56 090 Ft (rakt\u00e1ron). "
          "M\u00e1rka: HP. Kateg\u00f3ria: Nyomtat\u00f3 > Tintapatron, toner. HP 312A Yellow ...")
WEBDOC_OOS = ("Lenovo IdeaPad 3 Notebook (82RQ0085HV) \u2014 282 990 Ft (jelenleg nincs rakt\u00e1ron). "
              "M\u00e1rka: Lenovo. Kateg\u00f3ria: Laptop, Notebook > \u00daJ Notebook. Lenovo IdeaPad ...")
SELLVIO = ("TESERY karbon sz\u00e1las h\u00e1ts\u00f3 szpoiler Tesla Model Y - matt \u2014 176 700 Ft. "
           "M\u00e1rka: TESERY. Kateg\u00f3ria: Model Y (2020-2025), Model Y, Karbonsz\u00e1las. TESERY ...")
SELLVIO_NOBRAND = ("Eloszt\u00f3 doboz 9x\u00d850 \u2014 45 522 Ft. Kateg\u00f3ria: TQD Invent Mini. "
                   "TQDinvent mini eloszt\u00f3 doboz ...")
WOO = ("FELIX FANTASTIC - H\u00e1zias v\u00e1logat\u00e1s 12x85g \u2014 2990 Ft (k\u00e9szlet: 22 db). "
       "M\u00e1rka: Felix. Kateg\u00f3ria: Macska, Macska eledelek, Nedves eledelek, konzervek. A FELIX ...")
WOO_NOBRAND = ("Heves megye C\u00e9gadatb\u00e1zis \u2014 94 682 Ft (rakt\u00e1ron). "
               "Kateg\u00f3ria: Magyar c\u00e9gadatb\u00e1zis, V\u00e1rmegy\u00e9k. Heves V\u00e1rmegye ...")
UNAS = ("SPARTA 230xM14 gy\u00e9m\u00e1nt beton v\u00e1g\u00f3t\u00e1rcsa \u2014 3190 Ft "
        "(\u00c9pitkez\u00e9s/ fel\u00faj\u00edt\u00e1s |Elektromos k\u00e9ziszersz\u00e1m tartoz\u00e9kok| "
        "Sarokcsiszol\u00f3 gy\u00e9m\u00e1ntt\u00e1rcsa). K\u00e9szlet: 3 db. SPARTA EUROPA ...")
UNAS_1 = ("SMARTZILLA Rex okos\u00f3ra Fekete \u2014 29 990 Ft (Okos\u00f3r\u00e1k). K\u00e9szlet: 10 db. A Smartzilla ...")
SR = ("Kaisai kl\u00edma KCA4U-18HRG32X Kazett\u00e1s 5,3kW \u2014 426 275 Ft (rendelhet\u0151, k\u00e9szlet: 0 db). "
      "M\u00e1rka: Kaisai. Az \u00e1rak bel\u00e9p\u00e9s ut\u00e1n ...")
SR_WH = ("MTX 6x3,2mm popszegecs 50db DIN7337 \u2014 339 Ft (rendelhet\u0151, k\u00e9szlet: 372 db "
         "\u2014 k\u00fcls\u0151 rakt\u00e1r: 372 db, sz\u00e1ll\u00edt\u00e1s: 4-5 munkanap). M\u00e1rka: MTX. Az MTX ...")
SR_INACTIVE = ("Valami term\u00e9k \u2014 1000 Ft (inakt\u00edv). M\u00e1rka: X. Le\u00edr\u00e1s ...")

# m86 FP-ESETEK: a termek-LEIRASBAN allo spec-sor (valodi copygo / fishingoutlet /
# 4mfrigo textek -- ezeken a boltokon a builder EGYALTALAN nem ir kategoriat)
SR_SPEC_6A = ("DIGITUS CAT 6A NETWORK OUTLET CLASS EA FLUSH VERTIKAL \u2014 4890 Ft "
              "(rendelhet\u0151, k\u00e9szlet: 5 db \u2014 Rakt\u00e1r: 5 db, sz\u00e1ll\u00edt\u00e1s: 1-3 munkanap). "
              "M\u00e1rka: Assmann. V\u00e1laszd a(z) [CATEGORY] kateg\u00f3ria [PRODUCT] term\u00e9k\u00e9t "
              "k\u00edn\u00e1latunkb\u00f3l. Kateg\u00f3ria: 6a. Tov\u00e1bbi adatok ...")
SR_SPEC_WOBBLER = ("DAIWA STEEZ POPPER 60F SGBG \u2014 5590 Ft (rendelhet\u0151, k\u00e9szlet: 2 db). "
                   "M\u00e1rka: Daiwa. A Steez popper egy klasszikus csali. "
                   "Kateg\u00f3ria: popper; \u2022 Csalitest: egyr\u00e9szes; \u2022 Horog: 2 SaqSas")
SR_SPEC_NBSP = ("EPSON HIGH CABINET FOR WF-5000 \u2014 98 190 Ft (rendelhet\u0151, k\u00e9szlet: 1 db). "
                "M\u00e1rka: EPS BUS_IM. Le\u00edr\u00e1s sz\u00f6veg. Kateg\u00f3ria:&nbsp;Szekr\u00e9ny. Tov\u00e1bb ...")


# --- a MAI viselkedes valtozatlan (webdoc / Sellvio / Woo: 'Kategoria:' prefix) ---

def test_webdoc_category_valtozatlan():
    assert px.extract_params("", WEBDOC)["category"] == "Nyomtat\u00f3 > Tintapatron, toner"


def test_webdoc_a_zarojeles_ag_nem_veszi_at_a_prefixes_erteket():
    """A '(rakt\u00e1ron)' ugyanabban a pozicioban all, mint az Unas kategoria."""
    assert px.extract_params("", WEBDOC_OOS)["category"] == "Laptop, Notebook > \u00daJ Notebook"


def test_sellvio_lista_alak():
    p = px.extract_params("", SELLVIO)
    assert p["category"] == "Model Y (2020-2025), Model Y, Karbonsz\u00e1las"
    assert p["cat_tags"] == ["Model Y (2020-2025)", "Model Y", "Karbonsz\u00e1las"]


def test_sellvio_marka_nelkul_az_ar_utan():
    assert px.extract_params("", SELLVIO_NOBRAND)["category"] == "TQD Invent Mini"


def test_woo_lista_alak():
    p = px.extract_params("", WOO)
    assert p["cat_tags"] == ["Macska", "Macska eledelek", "Nedves eledelek", "konzervek"]


def test_woo_marka_nelkul_a_keszlet_zarojel_utan():
    assert px.extract_params("", WOO_NOBRAND)["category"] == "Magyar c\u00e9gadatb\u00e1zis, V\u00e1rmegy\u00e9k"


def test_szoveg_eleji_kategoria_megmarad():
    """m79c szintetikus alak: a text a 'Kateg\u00f3ria:'-val KEZDODIK."""
    t = "Kateg\u00f3ria: Kieg\u00e9sz\u00edt\u0151k > Notebook t\u00e1ska, h\u00e1tizs\u00e1k.\nLe\u00edr\u00e1s: ..."
    assert px.extract_params("", t)["category"] == "Kieg\u00e9sz\u00edt\u0151k > Notebook t\u00e1ska, h\u00e1tizs\u00e1k"


# --- m86: Unas zarojeles alak ---

def test_unas_zarojeles_ut():
    p = px.extract_params("", UNAS)
    assert p["category"] == ("\u00c9pitkez\u00e9s/ fel\u00faj\u00edt\u00e1s > Elektromos k\u00e9ziszersz\u00e1m "
                            "tartoz\u00e9kok > Sarokcsiszol\u00f3 gy\u00e9m\u00e1ntt\u00e1rcsa")
    assert p["cat_tags"] == ["\u00c9pitkez\u00e9s/ fel\u00faj\u00edt\u00e1s",
                             "Elektromos k\u00e9ziszersz\u00e1m tartoz\u00e9kok",
                             "Sarokcsiszol\u00f3 gy\u00e9m\u00e1ntt\u00e1rcsa"]


def test_unas_egyszintu():
    p = px.extract_params("", UNAS_1)
    assert p["category"] == "Okos\u00f3r\u00e1k" and p["cat_tags"] == ["Okos\u00f3r\u00e1k"]


# --- m86: a KESZLET-SZO kapu (Shoprenter/webdoc zarojel ugyanabban a pozicioban) ---

def test_shoprenter_nem_ad_kategoriat():
    for t in (SR, SR_WH, SR_INACTIVE):
        p = px.extract_params("", t)
        assert "category" not in p and "cat_tags" not in p, t[:40]


# --- m86: a LEIRAS-BELI spec-sor NEM kategoria (pozicio-kapu + ertek-higienia) ---

def test_leirasbeli_spec_sor_nem_kategoria():
    for t in (SR_SPEC_6A, SR_SPEC_WOBBLER, SR_SPEC_NBSP):
        p = px.extract_params("", t)
        assert "category" not in p and "cat_tags" not in p, t[:60]


def test_ertek_higienia_egysegben():
    assert not px._cat_ok("6a")                       # 2 karakter
    assert not px._cat_ok("popper; \u2022 Csalitest: egyr\u00e9szes")
    assert not px._cat_ok("&nbsp;Szekr\u00e9ny")
    assert not px._cat_ok("POS & Auto-ID \u2022 Alkateg\u00f3ria: Printing Media")
    assert px._cat_ok("Nyomtat\u00f3 > Tintapatron, toner")
    assert px._cat_ok("Model Y (2020-2025), Model Y")


def test_ures_text():
    assert px.extract_params("", "") == {}
    assert "category" not in px.extract_params("", "Nev \u2014 100 Ft. Le\u00edr\u00e1s.")


# --- category_tags egyseg ---

def test_category_tags_dedup_es_minhossz():
    # 'TV' (2 karakter) tul altalanos -> kiesik; az ismetlodo resz csak egyszer
    assert px.category_tags("Monitor, Projektor, TV > Monitor") == ["Monitor", "Projektor"]


def test_category_tags_hierarchia():
    assert px.category_tags("Nyomtat\u00f3 > Tintapatron, toner") == ["Nyomtat\u00f3", "Tintapatron", "toner"]


def test_category_tags_plafon():
    long = ", ".join("Kateg%02d" % i for i in range(30))
    assert len(px.category_tags(long)) == px._CAT_TAG_MAX


def test_category_tags_ures():
    assert px.category_tags("") == [] and px.category_tags(None) == []

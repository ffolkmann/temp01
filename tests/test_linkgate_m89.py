"""m89: a záró-link kapu tesztjei.

Fájl-betöltős import (spec_from_file_location), mert a suite más tesztjei fake
app.services-t hagynak a sys.modules-ben (kf/13 és m80b tanulsága).
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "linkgate.py"
_spec = importlib.util.spec_from_file_location("linkgate_m89", _p)
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

PROD = [{"payload": {"type": "product", "name": "Bosch fúró"}}]


def _ok(msg, hits=PROD, policy=False):
    return lg.should_offer_link(msg, hits, policy)[0]


# --- amit ENGEDNI kell (termék-irányú) ------------------------------------
def test_termek_kerdes_kap_linket():
    assert _ok("melyik a legolcsóbb notebook?")
    assert _ok("UV álló kötegelőt keresek")
    assert _ok("Milyen lézernyomtatóitok vannak?")
    assert _ok("Taurinos étrendkiegészítőt keresek cicáknak")


def test_akcios_es_kereso_jellegu_kerdes_marad():
    # a válasz ilyenkor gyakran nem linkel konkrét terméket -> ott a legértékesebb a kereső
    assert _ok("Vannak akciós termékek?")
    assert _ok("Windows 11-es laptopot keresek, mit ajánlasz?")


def test_tipuskod_es_meret_followup_TARTALMAS():
    """v1 shadow-lelet: a betű-alapú vizsgálat elvágta a típuskódos follow-upokat."""
    assert lg.is_contentful("GA605WI")
    assert lg.is_contentful("HP 135X")
    assert lg.is_contentful("S10+")
    assert lg.is_contentful("30 mm")
    assert lg.is_contentful("12x200 vagy 12x220 mm -es")
    assert lg.is_contentful("270H 40-120Gr")


def test_rendelni_ige_NEM_statusz():
    """A 'rendel' tő önmagában termék-szándék is lehet — nem szabad vágni."""
    assert not lg.non_product_intent("szeretnék rendelni egy fúrót")
    assert not lg.non_product_intent("hol tudom megrendelni ezt a bojlit?")


def test_szemelyesen_szuk_minta():
    """A szűk minta miatt a termék-kérdés megmarad, a bolt-info kérdés nem."""
    assert not lg.non_product_intent(
        "pontybölcsőt szeretnék vásárolni, de fontos, hogy személyesen akarom megvenni")
    assert lg.non_product_intent("Személyesen tudok ilyet venni?")
    assert lg.non_product_intent("Van e szemelyes átvétel")


# --- amit TILTANI kell ----------------------------------------------------
def test_policy_hard_stop():
    assert not _ok("Milyen fizetési módok vannak?", policy=True)
    assert not _ok("Mennyi a szállítási idő?", policy=True)


def test_koszones_es_nyugtazas():
    for m in ("Szia", "Üdv", "Köszönöm", "Ok.", "igen", "ya", "Csütörtök.", "Mi ez"):
        assert not _ok(m), m


def test_puszta_szam_nem_tartalmas():
    """Rendelés-/vevőszám — szemben a típuskóddal, itt NINCS betű."""
    for m in ("204110266", "2736", "54658"):
        assert not lg.is_contentful(m), m


def test_rendeles_statusz():
    for m in ("A rendelésem után érdeklődöm",
              "Rendelés 56145",
              "Az 56228 sz. rendelésemet szeretném + 1 tétellel kiegészíteni.",
              "merre jár",
              "utána tudsz nézni rendelésnek?",
              "ehhez a rendeléshez hozzá tudsz még tenni terméket?"):
        assert not _ok(m), m


def test_bolt_info_es_fiok():
    for m in ("Meddig van ma nyitva a Savoya parkban lévő üzletük?",
              "Nyitvatartási idö üzletben mettöl meddig van?",
              "Hirlevél hol lehet feliratkozni",
              "Jó napot! Az EU-s adószámot próbálom helyesen beírni, de nem fogadja el",
              "Miért nem enged vásárolni",
              "Nem sikerült utalni",
              "Továbbra is várom a hívást",
              "van termék összehasonlító lehetőség az oldalon?"):
        assert not _ok(m), m


# --- kontextus-réteg + fail-safe -----------------------------------------
def test_nincs_termek_a_kontextusban():
    assert not _ok("legolcsóbb notebook", hits=[])
    assert not _ok("legolcsóbb notebook", hits=None)
    assert not _ok("legolcsóbb notebook", hits=[{"payload": {"type": "doc", "name": "ÁSZF"}}])


def test_hibas_hits_nem_dob():
    assert lg.has_product_hit(["nem-dict", 42]) in (True, False)
    ok, why = lg.should_offer_link("fúró", ["nem-dict"], False)
    assert isinstance(ok, bool) and isinstance(why, str)


def test_indoklas_szoveg():
    assert lg.should_offer_link("akármi", PROD, True)[1] == "policy"
    assert lg.should_offer_link("Szia", PROD, False)[1] == "nincs tartalmas szo"
    assert lg.should_offer_link("A rendelésem után érdeklődöm", PROD, False)[1] == "nem-termek szandek"
    assert lg.should_offer_link("fúró", [], False)[1] == "nincs termek a kontextusban"
    assert lg.should_offer_link("fúró", PROD, False) == (True, "ok")

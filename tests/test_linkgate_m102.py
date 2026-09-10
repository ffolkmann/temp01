"""m102: bolti tema a zaro-link kapuban (shop_topic), termek-link or, LLM-link levetel.

Fajl-betoltos import (spec_from_file_location), mert a suite mas tesztjei fake
app.services-t hagynak a sys.modules-ben.
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "linkgate.py"
_spec = importlib.util.spec_from_file_location("linkgate_m102", _p)
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

PROD = [{"payload": {"type": "product", "name": "Bosch fúró", "url": "https://www.x.hu/termek/bosch-furo-1/"}}]
MORE = "[Tov\u00e1bbi tal\u00e1latok a web\u00e1ruh\u00e1zban](https://x.hu/kereses?keyword=kupon)"


# --- bolti tema: VAGNI kell (valodi korpusz-kerdesek) ----------------------
def test_shop_topic_valodi_bolti_kerdesek():
    for m in ("Kupon?", "Esetleg kupon kód most nincs?", "miért nem tudom a welcome10 kódom érvényesiteni?",
              "Első vásárló vagyok nálatok. Esetlegesen kedvezményt ilyenkor nem tudok nálatok kapni?",
              "Van esetleg aktuálisan valamilyen kedvezmény lehetőség?",
              "Hogy van nyitva az uzlet?", "Holnap nyitva vagytok?", "hello, működik a fizikai üzlet?",
              "Budapesti üzletetek van ?!", "Üdv, üzlet hol található?", "Szaküzlet hol van?", "Mi a bolt száma?",
              "Ha ma megrendelem holnap személyesen átvehetem?", "Debreceni boltba kérhetek személyes ávételt?",
              "Debreceni üzletben át lehet venni rendelést?", "Tehát a Soroksári úton átvehető ma is?",
              "Ha ma megrendelem, holnap átvehetem?", "Mikor lehet azt üzletben átvenni?",
              "Mikor jön meg", "Igen ez mit jelent? Mikor ér ide?", "hány nap alatt jön meg??",
              "ha most rendelek, holnapra van lehetőség biztosan megkapnom?",
              "Mennyi idő,ha házhoz kérem és mennyi,ha automatába?", "tegnap rendeltem. mikor lehet átvenni?",
              "Telefonszám", "Van másik telefon szám", "Most is hívhatom?", "fel tudom hívni?",
              "Hétfőn el tudlak érni telefonon", "ügyfélszolgálat csak hétköznapokon elérhető?",
              "Részletre lehet vásárolni?", "Igénybe lehet venni 0%-os hitelt nálatok?", "Árúhitelre szeretném meg veni",
              "Hová kell utalnom?", "Utalhatom?", "Bankszámla szám", "díjbekérőt lehet kérni rendelésre?",
              "Iskolatámogatási utalványt fel lehet majd használni?", "Megrendelés számláját keresem.",
              "Van valahol letölthető PDF számla?", "adó nélkül cégre lehet venni?",
              "nem tudok regisztrálni nálatok", "Elfelejtettem a jelszavam", "Nem kaptam visszaigazoló emailt"):
        assert lg.shop_topic(m), m


# --- termek-kerdes: NEM szabad bolti temanak venni --------------------------
def test_shop_topic_termek_kerdes_marad():
    for m in ("Vannak akciós termékek?", "akciós 390 cm machtbotot keresek", "Miert akcios",
              "Memória kártyat is tudsz ajánlani ebbe a kamerába", "150 ezerért a legcombosabb videokártyát mutasd",
              "SIM kártyás okosora erdekel", "Üzleti laptopot keresek hp",
              "BLACKBIRD hangszóró tudom mobiltelefonhoz csatlakoztatni?",
              "pontybölcsőt szeretnék venni, de személyesen akarom megvenni",
              "Etetőhajó z1 hátrakidobós van az üzletben?", "redmi buds 8 fülhallgató átvehető?",
              "hp 650 tintapatront szeretnék vásárolni a debreceni üzletben történő átvétellel",
              "Szeretnék vásárolni belőle 1 készletet házhoz szállítással",
              "Budapesten van olyan üzlet, ahol egy kárpitos tűzőgépet ki lehet próbálni?",
              "Miben nyilvanul meg hogy hitelesek vagytok?", "Egyedi méretben elérhető-e?",
              "Dugókulcs afapter", "A komplett mennyibe kerül?", "szeretnék rendelni egy fúrót"):
        assert not lg.shop_topic(m), m


# --- bucsuzo / lezaro uzenet: nincs tartalmas szo ---------------------------
def test_bucsuzo_formula_nem_tartalmas():
    for m in ("Szép napot", "Szèp napot", "Nagyon szép köszönöm", "Jó napot kívánok", "oké szép estét",
              "Köszönöm szépen. Most csak ezt kerestem."):
        assert lg.should_offer_link(m, PROD, False) == (False, "nincs tartalmas szo"), m
    # a "szep" csak formulakent nem tartalmas: SZEP-kartya, termeknev marad
    assert lg.is_contentful("Szép kártyával fizethetek?")
    assert lg.is_contentful("szép piros kerti szék")


# --- termek-link or ---------------------------------------------------------
def test_reply_has_product_link():
    assert lg.reply_has_product_link("Nézd: [Bosch](https://x.hu/termek/bosch-furo-1)", PROD)
    assert lg.reply_has_product_link("[Bosch](/termek/bosch-furo-1/)", PROD)
    assert not lg.reply_has_product_link("[Más](https://x.hu/termek/mas-2)", PROD)
    assert not lg.reply_has_product_link(MORE, PROD)
    assert lg.reply_has_product_link("[B](https://x.hu/b)", None, [{"name": "B", "url": "https://x.hu/b"}])
    assert not lg.reply_has_product_link("[B](https://x.hu/b)", [], None)
    assert not lg.reply_has_product_link("nincs link", PROD)
    assert not lg.reply_has_product_link("[doc](https://x.hu/aszf)",
                                         [{"payload": {"type": "doc", "url": "https://x.hu/aszf"}}])


def test_reply_has_product_link_hiba_eseten_marad_a_link():
    assert lg.reply_has_product_link("[B](https://x.hu/b)", 5) is True


# --- LLM-irta zaro-link levetele -------------------------------------------
def test_strip_more_link():
    r = "Kuponról nincs adatom.\n\n" + MORE
    assert lg.strip_more_link(r) == "Kuponról nincs adatom."
    assert lg.strip_more_link("abc") == "abc"
    keep = "[Bosch](https://x.hu/termek/bosch-furo-1)"
    assert lg.strip_more_link(keep + "\n\n" + MORE) == keep


# --- a regi (m89) kapu valtozatlan -----------------------------------------
def test_m89_kapu_valtozatlan():
    assert lg.should_offer_link("melyik a legolcsóbb notebook?", PROD, False) == (True, "ok")
    assert lg.should_offer_link("Kupon?", PROD, False) == (True, "ok")  # a m102 a chat.py-ban vag
    assert lg.should_offer_link("Szia", PROD, False)[1] == "nincs tartalmas szo"

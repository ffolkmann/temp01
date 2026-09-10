"""m89: ZÁRÓ-LINK KAPU — a "További találatok a webáruházban" link csak akkor,
ha a beszélgetés TERMÉKRE irányul.

Kiváltó eset (Fecó, 2026-08-15): a chat minden beszélgetés végén kereső-linket
dobott, akkor is, ha a kérdés a fizetési módokról / szállításról / egy rendelés
állapotáról szólt. Mérés a valódi korpuszon (3526 tárolt válasz, 12 tenant):
1826 válaszban volt záró-link (51,8%), ebből 258 policy-kérdésre (14,1%) —
a notebookstore-on 96 policy-kérdésből 89.

TERVEZÉSI DÖNTÉS. Kézenfekvő lett volna a linket ahhoz kötni, hogy a modell
linkelt-e terméket a válaszban (ez a korpuszon 52%-ot vág), DE az elvágná a
valódi termék-kérdéseket is, ahol a bot nem talált pontosat ("Windows 11-es
laptopot keresek", "akciós notebook") — épp ott a leghasznosabb a kereső.
Ezért a kapu KÉRDÉS-OLDALI hard-stopokból áll + egy kontextus-fail-safe-ből;
a bizonytalan eset a LINK JAVÁRA dől el (nem veszítünk termék-linket).

MÉRT LELET (v1 shadow, ezért van a _ALNUM/_NUMUNIT ág): a tisztán betű-alapú
tartalmasság-vizsgálat elvágta a TÍPUSKÓDOS follow-upokat ("GA605WI", "HP 135X",
"S10+", "30 mm", "12x200 vagy 12x220 mm -es") — azok termék-beszélgetés közepén
állnak. A vegyes betű+szám token és a szám+mértékegység ezért tartalmasnak
számít; a TISZTÁN számos üzenet ("204110266", "2736", "54658") nem — az
rendelés-/vevőszám.

PURE, stdlib-only modul: a hívó adja be a policy-flaget és a találatokat, így
a tesztből közvetlenül fájl-betölthető (a suite más tesztjei fake app.services-t
hagynak a sys.modules-ben).
"""

import re
import unicodedata


def fold(s: str) -> str:
    s = str(s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


# --- 1. RENDELÉS-ÁLLAPOT ---------------------------------------------------
# Szándékosan NEM a puszta "rendel" tő: a "szeretnék rendelni egy fúrót" TERMÉK-
# kérdés. Csak a birtokos alak, a rendelésszám és a státusz-fordulatok fognak.
_ORDER = re.compile(
    r"\brendelesem|\brendelesemet|\brendelesemre|\brendelesemhez|\brendeleshez|"
    r"\bmegrendelesem|"
    r"\brendeles\w*\s*(sz\.?|szamu|szam)?\s*\d{3,}|\d{4,}\s*(sz\.?|szamu)?\s*\brendeles|"
    r"merre jar|hol tart a csomag|hol van a csomag|nyomkovet|\bcsomagom|szallitmanyom|"
    r"meg mindig nem (szallit|erkez|kapt)|nem erkezett meg|nem kaptam visszaigazolas|"
    r"utana tudsz nezni|utananezel|rendeles utan erdeklod|rendelesem utan erdeklod"
)

# --- 2. BOLT-INFO / ÜGYINTÉZÉS / FIÓK -------------------------------------
# A "személyesen" MINTÁK SZŰKEK: a "pontybölcsőt szeretnék venni, de személyesen
# akarom megvenni" TERMÉK-kérdés, azt nem szabad elvágni.
_SHOPINFO = re.compile(
    r"nyitvatart|nyitva tart|meddig.{0,15}nyitva|mikor.{0,15}nyitva|hany oraig|"
    r"szemelyes atvetel|szemelyesen tudok|szemelyesen lehet|internetes rendeles nelkul|"
    r"hirlevel|feliratkoz|leiratkoz|"
    r"adoszam|szamlazasi cim|szamlat kert|szamla modosit|"
    r"bejelentkez|belepni|belepes|regisztraci|jelszo|fiokom|"
    r"nem enged vasarolni|nem sikerult utalni|nem mukodik az oldal|hibauzenet|"
    r"nem veszik fel a telefont|nem kaptam valaszt|ugyintezo|operator|"
    r"varom a hivast|visszahiv|irtam.{0,20}mail|"
    r"elo szemely|munkatars|osszehasonlito lehetoseg|osszehasonlito funkcio"
)

# --- 3. TARTALMATLAN ÜZENET (köszönés, nyugtázás, puszta szám) -------------
_GREET = {
    "szia", "sziasztok", "helo", "hello", "hali", "udv", "udvozlom", "udvozletem",
    "napot", "reggelt", "estet", "viszlat", "koszonom", "koszonjuk", "koszi",
    "rendben", "oke", "okay", "persze", "ertem", "vilagos",
    "igen", "nem", "aha", "jol", "szuper", "remek", "tokeletes", "kesz",
    # egyszavas nyugtázó válaszok a beszélgetés közepén
    "hetfo", "kedd", "szerda", "csutortok", "pentek", "szombat", "vasarnap",
    # m102: bucsuzo formulak ("Szep napot", "Nagyon szep koszonom", "Szep hetveget")
    "szep", "kivanok", "delutant", "hetveget",
}
_FILLER = {
    "van", "vannak", "volt", "lesz", "lehet", "kell", "kene", "szeretnek",
    "szeretnem", "erdeklodnek", "erdeklodom", "kerdes", "kerdesem", "kerem",
    "milyen", "mennyi", "mennyibe", "mikor", "hogyan", "hogy", "hol", "melyik",
    "akkor", "csak", "ott", "itt", "ezt", "azt", "ezek", "azok", "meg", "mar",
    "tudsz", "tudna", "tudnal", "tudnatok", "segit", "segiteni", "segitseg",
    "jo", "nagyon", "szepen", "elore", "is", "es", "de", "vagy", "majd",
    # m102
    "most", "kerestem", "ennyi", "mindent", "megvan", "ugye",
}

# --- 2b. m95: INFO-/ÜGYMENET-KÉRÉS ----------------------------------------
# Mért lelet (2026-08-26, 2260 linkes tárolt válasz): a záró kereső-link kiment
# számla-kérésre, használati-utasítás-kérésre, "hol a bolt / mikor kapom meg /
# hogyan rendeljem / csak MPL?" kérdésekre is. A minták a valódi korpuszból
# jönnek; sweep: 41 vágás, 0 termék-kereső veszteség (d26d_m95sweep).
_INFOREQ = re.compile(
    r"afas szaml|szamlat tud|szamlat kap|szamlat ker|szamlat szeretn|szamlaz|ceges szaml|"
    r"(hasznalati|kezelesi|mukodesi|uzembe\w*|uzemeltetesi|szerelesi|osszeszerel\w*|beuzemel\w*)"
    r"[^.,;!?]{0,25}(utasitas|utmutato|leiras)|"
    r"kezikonyv|gepkonyv|megfelelosegi nyilatkozat|garancialevel|"
    r"hol (van|vannak|talalhato\w*)[^.,;!?]{0,20}(ceg\w*|uzlet|bolt\w*|telephely|atveteli)|"
    r"hol tudom atvenni|hol vehetem at|hol lehet atvenni|"
    r"mikor kapom (meg|kezhez)|mikorra kapom|mikor erkezik|mikorra erkezik|"
    r"(ma|holnap|mikor) (feladjak|feladjatok|adjak fel|adjatok fel)|"
    r"mikor lesz kiszallitva|mikorra er ide|mikor szallitj|"
    r"hogy(an)? tud(om|ok|nam|nank)( meg)? ?rendelni|hogy(an)? rendel(jem|hetek|hetem|het\b)|"
    r"kosarban van|kosarba (tettem|raktam)|nem tudom megrendelni|nem enged megrendelni|"
    r"le akarom mondani|le szeretnem mondani|lemondanam|sztorno|\bstorno|"
    r"telefonszamot (kaphatnek|kerhetek|kerek|kernek|adna|tudna)|"
    r"csomagpont|csomagautomata|\bgls\b|\bfoxpost\b|\bmpl\b|packeta|futarszolgalat|\bfutar\b|\bfutarral\b"
)

# vegyes betű+szám token = típus-/cikkszám (GA605WI, S10, 270H, BQ2345, 135x)
_ALNUM = re.compile(r"\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*[0-9])[a-z0-9]{3,}\b")
# szám + mértékegység (30 mm, 14kg, 512gb) ill. méret-jelölés (12x200)
_NUMUNIT = re.compile(
    r"\b\d+[\s-]*(mm|cm|dm|kg|dkg|gr|ml|db|kw|ah|mah|gb|tb|col|coll|literes|kilos|"
    r"colos|hüvelyk|huvelyk|w|v|l)\b")
_DIM = re.compile(r"\b\d+\s*[x×]\s*\d+")


def is_contentful(message: str) -> bool:
    """Van-e legalább egy tartalmas jel a kérdésben (szó, típuskód vagy méret)."""
    f = fold(message)
    for tok in re.findall(r"[a-z]{3,}", f):
        if tok not in _GREET and tok not in _FILLER:
            return True
    return bool(_ALNUM.search(f) or _NUMUNIT.search(f) or _DIM.search(f))


def non_product_intent(message: str) -> bool:
    """A kérdés egyértelműen NEM termékre irányul (rendelés-állapot, bolt-info, fiók)."""
    f = fold(message)
    return bool(_ORDER.search(f) or _SHOPINFO.search(f) or _INFOREQ.search(f))


def has_product_hit(hits) -> bool:
    """Van-e termék-találat a kontextusban (fail-safe: ha nincs, nincs mit keresni)."""
    try:
        for h in hits or []:
            p = (h.get("payload", {}) or {}) if isinstance(h, dict) else {}
            if str(p.get("type") or "") == "product" and p.get("name"):
                return True
    except Exception:  # noqa: BLE001 — a kapu hibája sose törje a választ
        return True
    return False


# --- 4. m102: BOLTI TEMA ----------------------------------------------------
# Mert lelet (d10c, 2026-09-10, 1886 valasz 08-27 ota): a zaro kereso-link ~100
# valodi bolti kerdes ala is kiment (kupon, nyitvatartas, szemelyes atvetel,
# "mikor jon meg", telefon/ugyfelszolgalat, reszlet/hitel/utalas, szamla,
# regisztracio) - a _SHOPINFO / _INFOREQ ezeket a fordulatokat nem ismerte.
# Az "akcio" SZANDEKOSAN nincs benne ("Vannak akcios termekek?", "akcios
# notebook" termek-kereses - ott a link a leghasznosabb), ahogy a puszta
# "telefon", "kartya", "hazhoz" sem (copygo telefonbolt, memoria-/videokartya,
# "vasarolnek belole hazhoz szallitassal").
# A hivo (chat.py) CSAK akkor vag, ha a valaszban nincs termek-link
# (reply_has_product_link) - vegyes kerdesnel ("Laptop taskat szeretnek, az
# uzletben is at lehet venni?") a link marad.
_SHOPTOPIC = re.compile(
    # kupon / kedvezmenykod
    r"\bkupon|kedvezmeny ?kod|\bwelcome ?\d{0,2}\b|kodom\w* (erveny|bevalt|nem mukodik)|"
    r"kedvezmeny\w*[^.?!]{0,30}\bkap|kedvezmeny\w* lehetoseg|valami(lyen)? kedvezmeny|"
    r"(elso|uj|visszatero) (vasarlo|vasarlas|regisztral)\w*[^.?!]{0,40}kedvezmeny|"
    r"kedvezmeny\w*[^.?!]{0,40}(visszatero|elso|uj) (vasarl|regisztral)|"
    # nyitvatartas, fizikai uzlet
    r"\bnyitva\b|fizikai uzlet|(van|mukodik)( a| az)? (uzlet|bolt)(etek|otok|juk|uk|unk)?\b|"
    r"\b(uzlet|bolt)(etek|otok|uk|jaitok|eitek)\b|"
    r"(uzlet|bolt|szakuzlet)\w* hol (van|talalhato|lehet)|(bolt|uzlet)\w* (telefon)?szama|"
    # szemelyes atvetel
    r"szemelyes(en)? (atvet|avet|atveh|atvenn|elhoz)|szemelyesen at( \w+)? venni|"
    r"(at lehet venni|atveheto|atvehet\w*|atvenni)[^.?!]{0,30}(szemelyesen|uzlet|bolt)|"
    r"(uzlet|bolt)\w*[^.?!]{0,30}(at lehet venni|atveheto|atvehet|atvenni)|"
    r"hol (lehet|tudom|tudok|lehetne)( \w+)? atvenni|mikor (lehet|tudom)( \w+)? atvenni|"
    r"\batveheto ma\b|ma is atveheto|\b(ma|holnap)( \w+)? atvehet|"
    # szallitasi ido / mod
    r"mikor (jon|er|erkezne|erne|jonne) (meg|ide)\b|mikor er ide|mikorra (jon|er|kapnam)|"
    r"hany nap (alatt|mulva|mire)|holnapra[^.?!]{0,30}kap|megkapnom|"
    r"hazhoz (kerem|kerne\w*|rendel\w*)|(hozzak|hoznak|hozna\w*|kihoz\w*) hazhoz|\bautomataba\b|"
    # rendeles utani erdeklodes (idohatarozoval: a puszta "rendeltem" termek-follow-up is lehet)
    r"\b(tegnap|ma|mar|mult heten|hetfon|kedden|szerdan|csutortokon|penteken|szombaton|vasarnap)"
    r"( \w+)? meg ?rendeltem|\b(tegnap|ma|mult heten)( \w+)? rendeltem|"
    # telefon, ugyfelszolgalat
    r"telefon ?szam|\bhivhat\w*|fel ?tudom hivni|felhivhat\w*|\bhivtam\b|ugyfelszolg\w*|"
    r"(erni|erlek|egyeztetni) telefonon|telefonon (nem |is )?(lehet|tudok|el)|munkaidoben|"
    # fizetes (a policy_filter fizet/utanvet/reszletfizet mintai mellett)
    r"\breszletre\b|kamatmentes|\bhitel(re|t|lel)\b|aruhitel|\butalhat\w*|\b(el)?utaltam\b|"
    r"hova (kell )?utal|bankszamla ?szam|dijbekero|elolegbekero|\butalvany|bevaltan|"
    # szamla, ceges vasarlas
    r"szamlaj\w*|pdf szamla|letoltheto\w* szamla|\bcegre( nem)? (lehet|vasarol|venni|rendel|vonatkoz)|"
    # fiok
    r"regisztral|jelszav|visszaigazolo e-?mail"
)


def shop_topic(message: str) -> bool:
    """m102: a kerdes bolti temara (kupon, nyitvatartas, atvetel, szallitasi ido,
    telefon, fizetes, szamla, fiok) iranyul-e."""
    return bool(_SHOPTOPIC.search(fold(message)))


# --- 5. m102/3: IDENTITAS- / META-KERDES -----------------------------------
# Mert lelet (d10d, 30 nap, 3341 valodi kerdes): a botnak szolo kerdesek ala is
# kiment a zaro kereso-link, a kerdes szavaibol epitett, ertelmetlen termmel
# ("Miert nem Zolinak hivnak?" -> search=Miert+nem, "Te vagy az Sanyi?" ->
# search=vagy+Sanyi, "Mesterseges inteligencia vagy?" -> keyword=..., "jo bena
# robot vagy" -> k=bena+robot); E2E-ben mind az 5 nevkerdes keyword=hivnak
# linket kapott. Sweep: 6 talalat / 3341, mind valodi, mind linkes, 0 FP.
# CSAPDAK (ezert a lookahead-ek): "Fekete vagy acelszurke?" (a "te vagy" csak
# szohatarral), "robot vagy kezi funyiro?" / "buta vagy okostelefon?" (termek-
# alternativa: az "X vagy" csak kerdes-/mondatvegen), "ki vagy bekapcsolhato"
# (a "ki vagy" csak mondatvegen), "ember vagyok" (a vagy utan szohatar),
# "ha te vagy a helyemben" (termek-tanacskeres). A "hivjak" SZANDEKOSAN nincs
# benne ("hogy hivjak azt a szerszamot..." termek-kerdes).
_META = re.compile(
    r"\bhivnak\b|\bneved\b|hogy szolithatlak|"
    r"\bki vagy\s*(te\b)?\s*(?=[?!.,;]|$)|"
    r"\bkivel (beszelek|beszelgetek|chatelek|levelezek|irok|irogatok)\b|"
    r"\bte vagy (az?|egy) (?!helyem)|\bte vagy \w+( \w+)?\s*(?=[?!.]|$)|"
    r"\bte (egy )?(robot|bot|chatbot|gep|ember|ai)\b|"
    r"\b(robot|bot|chatbot|gep|ai|mesterseges\s+intel+\w*|ember|elo ember|valodi ember|"
    r"igazi ember|elo szemely)\s+vagy\s*(te\s*)?(?=[?!.,;]|$|\s+vagy\b)|"
    r"\b(buta|hulye|bena|haszontalan|ertelmetlen)\s+(vagy|bot|robot|gep)\s*(te\s*)?(?=[?!.,;]|$)|"
    r"\b(hogy(an)?|mire|mivel) akarsz segiteni"
)


def meta_topic(message: str) -> bool:
    """m102/3: a kerdes a botnak szol (neve, kiletele, "robot vagy?", minosites),
    nem termekre - ala nem kell kereso-link."""
    return bool(_META.search(fold(message)))


_MDURL = re.compile(r"\]\(((?:https?://|/)[^)\s]+)\)")


def _ukey(u) -> str:
    u = str(u or "").strip().split("#", 1)[0]
    if "://" in u:
        u = u.split("://", 1)[1]
        u = "/" + u.split("/", 1)[1] if "/" in u else "/"
    return u.rstrip("/").lower()


def reply_has_product_link(reply, hits=None, shop_hits=None) -> bool:
    """m102: a valasz linkel-e a kontextus (Qdrant-hits / bolti kereso) valamelyik
    termekere. Az URL-t utvonal+query szerint vetjuk ossze (domain, zaro / nelkul).
    Hiba eseten True (= a link marad, a mai viselkedes)."""
    try:
        known = set()
        for h in hits or []:
            if not isinstance(h, dict):
                continue
            p = h.get("payload") or {}
            if str(p.get("type") or "") == "product" and p.get("url"):
                known.add(_ukey(p.get("url")))
        for h in shop_hits or []:
            if isinstance(h, dict) and h.get("url"):
                known.add(_ukey(h.get("url")))
        known.discard("")
        if not known:
            return False
        return any(_ukey(u) in known for u in _MDURL.findall(str(reply or "")))
    except Exception:  # noqa: BLE001 - az or hibaja sose vigye el a linket
        return True


_MORELINK = re.compile(u"\\s*\\[Tov\u00e1bbi tal\u00e1latok a web\u00e1ruh\u00e1zban\\]\\([^)\\s]*\\)[ \\t]*")


def strip_more_link(reply: str) -> str:
    """m102: az LLM altal (a m25 prompt-utasitasra) beirt "Tovabbi talalatok a
    webaruhazban" linket leveszi, ha a kapu a zaro-linket nem engedte."""
    r = str(reply or "")
    out = _MORELINK.sub("", r)
    return out.rstrip() if out != r else r


def should_offer_link(message: str, hits=None, is_policy: bool = False,
                      has_products=None) -> tuple:
    """Kimehet-e a záró kereső-link. -> (bool, ok)

    A hívó adja be az is_policy flaget (app.services.policy_filter.is_policy_query),
    hogy ez a modul stdlib-only maradjon.

    m89/1 — `has_products`: a kontextus-fail-safe FELÜLÍRÁSA. A m25-ös
    (search_fallback) ágon a BOLT SAJÁT keresője adta a találatokat, a Qdrant-pool
    pedig éppen azért gyenge, mert emiatt indult a bolti keresés; ráadásul a
    shop_hits elemeknek nincs 'payload' kulcsuk. Mérve 583 valódi fallback-
    kérdésen: üres pool mellett 391 (67,1%) veszítené el a linkjét, köztük a
    legjobb termék-kérdések ("Előketartót keresek", "Macskaalmot keresek").
    A kérdés-oldali hard-stopok a bolti ágon is változatlanul érvényesek.
    """
    if is_policy:
        return False, "policy"
    if not is_contentful(message):
        return False, "nincs tartalmas szo"
    if non_product_intent(message):
        return False, "nem-termek szandek"
    _hp = has_product_hit(hits) if has_products is None else bool(has_products)
    if not _hp:
        return False, "nincs termek a kontextusban"
    return True, "ok"

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
}
_FILLER = {
    "van", "vannak", "volt", "lesz", "lehet", "kell", "kene", "szeretnek",
    "szeretnem", "erdeklodnek", "erdeklodom", "kerdes", "kerdesem", "kerem",
    "milyen", "mennyi", "mennyibe", "mikor", "hogyan", "hogy", "hol", "melyik",
    "akkor", "csak", "ott", "itt", "ezt", "azt", "ezek", "azok", "meg", "mar",
    "tudsz", "tudna", "tudnal", "tudnatok", "segit", "segiteni", "segitseg",
    "jo", "nagyon", "szepen", "elore", "is", "es", "de", "vagy", "majd",
}

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
    return bool(_ORDER.search(f) or _SHOPINFO.search(f))


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


def should_offer_link(message: str, hits=None, is_policy: bool = False) -> tuple:
    """Kimehet-e a záró kereső-link. -> (bool, ok)

    A hívó adja be az is_policy flaget (app.services.policy_filter.is_policy_query),
    hogy ez a modul stdlib-only maradjon.
    """
    if is_policy:
        return False, "policy"
    if not is_contentful(message):
        return False, "nincs tartalmas szo"
    if non_product_intent(message):
        return False, "nem-termek szandek"
    if not has_product_hit(hits):
        return False, "nincs termek a kontextusban"
    return True, "ok"

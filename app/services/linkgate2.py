# -*- coding: utf-8 -*-
"""m126 (K3): zaro-link kapu 2 - a "Tovabbi talalatok a webaruhazban" kereso-link CSAK
termek-jellegu kerdesre, ertelmes (a bolt termekneveibol vett) kulcsszoval.

Lelet (d21a audit + d21b meres, 2026-10-21): 10-13 ota a valodi valaszok ~40%-a alatt van
zaro-link, ebbol 326 kezzel atnezve 132 ertelmetlen ("keyword=Hol+tart", "=venni", "=kosz",
"=Rendelés+adásátol", "=lenne+ket", "=Tesla"). Okok: (1) a m95 kerdes-alapu tartalek-term az
uzenet elso ket nem-toltelek szava, barmi legyen is; (2) a m117 katalogus-kapu szo-resz
egyezest nez, es 15-85 ezer terméknév kozott szinte minden szo-to elofordul ("tart" -> tarto);
(3) rendeles-utani, atveteli, panasz-korben is kiment; (4) a bolti kereso-agon (m25) a teljes
kerdes-frazis lett a keresoszo.
A kapu: rendeles/atvetel/panasz -> nincs link; kerdes-alapu (es bolti kereso-) termnel a kerdesben
legyen termeknev-szo (pontos szo vagy rag-levalasztas, legalabb 3 nevben, beszelgetesi szo nem),
a term ezekbol a szavakbol epul; a nevek >50%-aban szereplo szo (teslashop: Tesla, Model) nem
kulcsszo. Meres (d21b/k3, 326 kezzel cimkezett valasz): ertelmetlen 132 -> 89 levagva,
a tobbi ertelmesebb termet kap; jo linkbol 3/146 veszett el (elgepeles, elozmenybol jovo term).
Stdlib-only; a katalogus-szokincset a name_df() a lexmatch cache-ebol olvassa (lusta import).
"""
import re
import unicodedata

GENERIC_RATIO = 0.5
MIN_DF = 3


def fold(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


_TOK = re.compile(r"[a-z0-9]+")

# beszelgetesi / kerdes-keret szavak (foldolt) - termeknevben is elofordulhatnak, de kulcsszonak ertelmetlenek
STOP = set("""
tart tartok tartom tud tudom tudok tudja lehet lesz lenne volna kell kellene kene van vannak nincs
nincsenek volt jon jott megy ment kap kapok kaptam kapom kapnam kapni ker kerek kerem kernem keres
keresek kerestem nez nezek nezem latom latok lat irtam irok ir mondtam mond mit mi mire mikor hol hova
honnan hogy hogyan miert melyik milyen mennyi mennyibe mennyire meddig ki kinek kivel ez az ezt azt ezek
azok ezzel azzal ilyen olyan itt ott most mar meg csak is es vagy de ha mert akkor igen nem jo rossz nagy
kis kicsi uj regi sok keves mas masik egyik minden semmi valami barmi egy ket ketto harom negy ot hat het
nyolc kilenc tiz elso masodik ma holnap tegnap reggel este nap napot napja het hete honap ev eve ora oraig
perc szia hello helo udv udvozlom koszonom koszi kosz koszke koszonet koszonjuk koszonettel szepen nagyon
kerlek legyen legyszi rendben oke ok oki persze ertem remelem sajnos talan esetleg valoszinu biztos
info infot infok valasz valaszt valaszod segitseg segitseget segiteni segit gyors gyorsan email mail
telefon telefonszam szam szamon szamot hivas hivjon hivni hiv uzenet uzenetet level levelet bolt boltban
uzlet uzletben uzletetek weboldal oldal oldalon oldalt rendszer rendszerben kosar kosarban penztar
rendeles rendelest rendelesem rendelesemet rendeltem megrendeltem rendelni megrendelni rendelek rendelhet
rendelheto rendelhetem vasarolni vasarolnek vasarlas venni vennek vettem atvenni atvehet atveheto atvetel
szemelyesen szallitas szallitasi kiszallitas csomag csomagot csomagba csomagom futar posta postan
utanvet utanvettel fizetes fizetni fizettem utalas utaltam szamla szamlat ar ara aron arat olcso olcsobb
draga dragabb kedvezmeny kupon raktaron raktar keszlet keszleten keszletben elerheto
kerdes kerdesem kerdeznem erdeklodnek erdeklodom erdekelne erdekel szeretnek szeretnem szeretne
lehetne lehetseges tudna tudnatok tudnal mukodik mukodne jar jarna valo valok illik passzol hozza
neki nekem nalam nalatok nalunk tolem toletek tolunk velem veletek rola rolam ami amit amire amibe
aki akit ahol amikor mint minden mindig soha sem se pedig hanem tehat szoval ugye hat jah ja aha
utan elott alatt felett mellett kozott helyett nelkul szerint szerinted fel le ki be el hez hoz nak nek
erdek erdekes
hossz hossza hosszu hosszabb rovidebb szeles szelesseg szelessege magas magassag meret merete meretben meretu
suly sulya vastag vastagsag szin szine szinben szinu szinekben tipus tipusu tipust fajta kapacitas teljesitmeny
tobb tobbet kevesebb jobb jobbat legjobb gyorsabb gyorsabbat olcsobbat model modell azonosito
azonnal beszel beszelni angolul nyugi barat baratom leg kompatibilis kompatibilise szar benne rajta
link pontosan normalis szep darab utolso melle gyujtok gyujt
""".split())

_ALNUM = re.compile(r"\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*[0-9])[a-z0-9]{3,}\b")
_NUMUNIT = re.compile(r"\b\d+[\s,.-]*\d*\s*(mm|cm|m|meter|meteres|kg|kilos|g|dkg|ml|l|liter|literes|db|kw|w|v|"
                      r"ah|mah|gb|tb|col|colos|inch|mp|lbs)\b")
_DIM = re.compile(r"\b\d+([.,]\d+)?\s*[x×]\s*\d+")

# rendeles utani / atveteli / panasz kor: ilyenkor a kereso-link sosem segit
_HARDSTOP = re.compile(
    r"rendelesszam\s*#|\b(meg)?rendeltem\b|\b(meg)?rendeltunk\b|leadtam a rendel|adtam le (a )?rendel|"
    r"rendeles\w*\s+(\w+\s+)?le ?ad|leadni a rendel|rendeles\w* (mar )?(zart|lezar)|nem tudok (hozza )?rendelni|"
    r"nem kaptam|nem kapom|nem jott|nem erkezett|megkap(om|tam|nom)|megjon|megerkez|kiszallit|"
    r"\bspam|visszaigazol|hangposta|telt el|munkanap|"
    r"\bhol tart\b|meg mindig|varom a hivas|nem vette fel|nem veszik fel|"
    r"visszamond|visszakuld|reklamac|reklamal|\bpanasz|kiderult|hirdetett|"
    r"\bi (just )?bought\b|\bmy order\b|\bdelivery\b|\be-?mail(ben|t|re|em|emet)?\b|"
    r"szemelyesen( \w+){0,3} (at ?venni|atvehet\w*|atveszem|megvenni|elhozni)|at ?tudom venni|"
    r"atveheto|atvehetem|atvenni"
)

_ATTR = re.compile(r"\b(hossz|rovid|nagyobb|kisebb|szeles|keskeny|magas|alacsony|olcsobb|dragabb|erosebb|"
                   r"gyengebb|konnyebb|nehezebb|vastag|vekony|meteres|literes|kilos|colos|fajta|szinu|szinben)")
_COURTESY = re.compile(r"\b(koszon\w*|kosz|koszi|koszke|szia|hello|helo|udv\w*|jo napot|szep napot|"
                       r"rendben|oke|ertem|latom|nalatok|neked|kepet)\b")


def is_stop(tok):
    if tok in STOP:
        return True
    for k in (2, 3):
        st = tok[:-k]
        if len(st) >= 4 and st in STOP:
            return True
    return False


def catalog_word(tok, df):
    """A (foldolt) token termeknev-szo-e: pontos egyezes vagy rag-levalasztas utan (1 betu: to >= 4,
    2-3 betu: to >= 5, 4-5 betu: to >= 7), es legalabb MIN_DF termeknevben szerepel."""
    if len(tok) < 3 or tok.isdigit() or is_stop(tok):
        return False
    if df.get(tok, 0) >= MIN_DF:
        return True
    for k in (1, 2, 3, 4, 5):
        st = tok[:-k]
        need = 4 if k == 1 else (5 if k <= 3 else 7)
        if len(st) >= need and st not in STOP and df.get(st, 0) >= MIN_DF:
            return True
    return False


def _ratio(tok, dfx):
    df, n = dfx
    return (df.get(tok, 0) / n) if n else 0.0


def product_tokens(message, df):
    return [t for t in _TOK.findall(fold(message)) if catalog_word(t, df)]


def productish(message, df):
    """Termek-jellegu-e a kerdes: van benne termeknev-szo, tipuskod vagy mertekegyseges meret."""
    f = fold(message)
    if product_tokens(message, df):
        return True
    return bool(_ALNUM.search(f) or _NUMUNIT.search(f) or _DIM.search(f))


def hard_stop(message, prev_user=""):
    """Rendeles-utani / atveteli / panasz kor (vagy az elozo uzenet a rendeles-urlap volt)."""
    if _HARDSTOP.search(fold(message)):
        return True
    p = fold(prev_user).strip()
    return p.startswith("rendelesszam #") or p.startswith("rendelesszam#")


def attr_followup(message):
    f = fold(message)
    return bool(_ATTR.search(f)) and not _COURTESY.search(f)


def derivable_from(term, text):
    tt = [t for t in _TOK.findall(fold(term)) if len(t) >= 3]
    qt = [t for t in _TOK.findall(fold(text)) if len(t) >= 3]
    return any(a in b or b in a for a in tt for b in qt)


def name_term_ok(term, dfx):
    toks = [t for t in _TOK.findall(fold(term)) if len(t) >= 3]
    return bool(toks) and not all(_ratio(t, dfx) > GENERIC_RATIO for t in toks)


def topic_term(message, dfx):
    """Kerdes-alapu kulcsszo CSAK termeknev-szavakbol (max 2) es tipuskodbol, a nevek
    >50%-aban szereplo szavak nelkul."""
    df = dfx[0]
    out = []
    for raw in re.findall(r"[\w-]+", str(message or "")):
        f = fold(raw)
        fc = f.replace("-", "")
        if _ALNUM.fullmatch(fc or "") and len(fc) >= 5 and not re.fullmatch(r"\d+[a-z]+", fc):
            out.append(raw)
        else:
            f = f.replace("-", "")
            if len(f) < 3 or any(ch.isdigit() for ch in f) or not catalog_word(f, df) \
                    or _ratio(f, dfx) > GENERIC_RATIO:
                continue
            out.append(raw)
        if len(out) == 2:
            break
    return " ".join(out)


def filter_term(term, dfx):
    """Meglevo (bolti kereso-) kulcsszo szurese: csak a termeknev-szavak maradnak, sorrendben."""
    df = dfx[0]
    out = []
    for raw in re.findall(r"\w+", str(term or "")):
        f = fold(raw)
        if catalog_word(f, df) and (any(ch.isdigit() for ch in f) or _ratio(f, dfx) <= GENERIC_RATIO):
            out.append(raw)
    return " ".join(out[:3])


def keep_or_rebuild(term, message, dfx, shop=False):
    """A meglevo kulcsszo marad, ha egyik szava sem toltelek es legalabb egy termeknev-szo; kulonben
    ujraepites a termeknev-szavakbol (ures -> nincs zaro-link)."""
    df = dfx[0]
    toks = [fold(t) for t in re.findall(r"\w+", str(term or ""))]
    toks = [t for t in toks if len(t) >= 3 and not t.isdigit()]
    if toks and not any(is_stop(t) for t in toks) and any(catalog_word(t, df) for t in toks) \
            and not all(_ratio(t, dfx) > GENERIC_RATIO for t in toks):
        return term
    return filter_term(term, dfx) if shop else topic_term(message, dfx)


def gate_term(message, prev_user, term, dfx, topic=False, shop=False):
    """-> (kulcsszo, tilt, ok). tilt=True: nincs zaro-link (fasetta-/kategoria-link sem).
    dfx=None (a katalogus meg nincs kesz): csak a kerdes-oldali hard-stop el (fail-open)."""
    if hard_stop(message, prev_user):
        return "", True, "rendeles/atvetel/panasz"
    if not dfx or not dfx[1]:
        return term, False, "nincs katalogus"
    df = dfx[0]
    if not term:
        if not productish(message, df) and not attr_followup(message):
            return "", True, "nem termek-jellegu"
        return term, False, "ures term"
    if topic or shop:
        if not productish(message, df):
            return "", True, "nem termek-jellegu"
        nt = keep_or_rebuild(term, message, dfx, shop=shop)
        if not nt:
            return "", True, "nincs termeknev-szo"
        return nt, False, "ok" if nt == term else "term ujraepitve"
    if not name_term_ok(term, dfx):
        return "", True, "altalanos nev-term"
    if derivable_from(term, message) or productish(message, df) or attr_followup(message):
        return term, False, "ok"
    return "", True, "nem termek-jellegu kovetes"


def prev_user(history):
    for h in reversed(history or []):
        r = getattr(h, "role", None) or (h.get("role") if isinstance(h, dict) else "")
        if r == "user":
            c = getattr(h, "content", None)
            if c is None and isinstance(h, dict):
                c = h.get("content")
            return str(c or "")
    return ""


_DF_CACHE = {}


def name_df(client_id):
    """(token -> hany termeknevben, termekszam) a lexmatch katalogus-cache-bol; None, ha meg nincs kesz."""
    try:
        from app.services import lexmatch as _lx
        ent = _lx._catalog_nowait(client_id)
        if not ent:
            return None
        built = (_lx._cache.get(client_id) or (0, None))[0]
        hit = _DF_CACHE.get(client_id)
        if hit and hit[0] == built:
            return hit[1]
        df = {}
        for e in ent:
            nf = e[1] if isinstance(e, (list, tuple)) and len(e) > 1 else str(e)
            for t in set(_TOK.findall(str(nf))):
                if len(t) >= 3:
                    df[t] = df.get(t, 0) + 1
        val = (df, len(ent))
        _DF_CACHE[client_id] = (built, val)
        return val
    except Exception:  # noqa: BLE001 - a kapu hibaja sose torje a valaszt
        return None

"""m87: nem-latin szo-orseg egyseg-tesztek (fajl-betoltes, app-import nelkul).

A minta-szovegek VALODI eles valaszokbol valok (tools/m87_langscan.py, messages tabla).
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "langguard.py"
_spec = importlib.util.spec_from_file_location("langguard_m87", _p)
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

# --- valodi eles esetek ---
UKRAN = ("Fontos: ez a \u043d\u0430\u0439\u043a\u0440\u0430\u0449\u0435 \u00e1r a most el\u00e9rhet\u0151 adataim alapj\u00e1n, "
         "de nem biztos, hogy ez a teljes k\u00edn\u00e1lat legolcs\u00f3bbja.")
OROSZ = "A \u043d\u0430\u0439\u0434\u0435\u043d\u043e adataim alapj\u00e1n a legolcs\u00f3bb rakt\u00e1ron l\u00e9v\u0151 MSI notebook n\u00e1lunk a MSI Modern 14."
HIBRID = "Ez a \u043d\u0430\u0439mostani \u00e1r a legjobb, amit tal\u00e1ltam."
KUTYA = "a kutya \u043f\u043e\u0440\u043e\u0434\u044b, m\u00e9rete \u00e9s eg\u00e9szs\u00e9gi \u00e1llapota f\u00fcggv\u00e9ny\u00e9ben"

# --- amit NEM szabad jelezni ---
TISZTA = ("Igen, van! A legolcs\u00f3bb rakt\u00e1ron l\u00e9v\u0151 g\u00e9p az Asus Vivobook Go 14 \u2014 109 900 Ft, "
          "14\" FullHD kijelz\u0151, 4GB RAM, Windows 11 Home. \u00d850 mm, 5 \u00b5F, ~30 \u00b0C. \ud83d\ude42")
# valodi kellegyszerszam terneknev: a 'x' helyen CIRILL kha all (egyetlen karakter)
TERMEKNEV = "MAGUS MES10 10\u0445/22 mm (D 30 mm) szemlencse sk\u00e1l\u00e1val"
# olyan termeknev, ami TENYLEG tobb cirill betut tartalmaz -> a kontextus-kapu menti
CIRILL_TERMEK = "\u0417\u0423\u0411\u0420 profi csavarh\u00faz\u00f3 k\u00e9szlet"


def test_ukran_szivargas():
    assert lg.foreign_tokens(UKRAN) == ["\u043d\u0430\u0439\u043a\u0440\u0430\u0449\u0435"]
    assert lg.has_foreign_leak(UKRAN)


def test_orosz_szivargas():
    assert lg.foreign_tokens(OROSZ) == ["\u043d\u0430\u0439\u0434\u0435\u043d\u043e"]


def test_hibrid_token():
    assert lg.foreign_tokens(HIBRID) == ["\u043d\u0430\u0439mostani"]


def test_mondat_kozepi():
    assert lg.foreign_tokens(KUTYA) == ["\u043f\u043e\u0440\u043e\u0434\u044b"]


def test_tiszta_magyar_valasz_nem_jelez():
    """Ekezetek, hosszu o/u, \u00d8, mikro-jel, fok, emoji, hivatkozas -- egyik sem idegen szo."""
    assert lg.foreign_tokens(TISZTA) == []
    assert not lg.has_foreign_leak(TISZTA)


def test_egyetlen_cirill_karakter_a_termeknevben_nem_jelez():
    """A `_MIN_RUN`=2 kapu: egy beszorult karakter (10\u0445/22) nem szo-szivargas."""
    assert lg.foreign_tokens(TERMEKNEV) == []


def test_kontextus_kapu_menti_a_bolt_sajat_adatat():
    szoveg = "A(z) " + CIRILL_TERMEK + " ma rakt\u00e1ron van."
    assert lg.foreign_tokens(szoveg) != []          # kontextus nelkul jelezne
    assert lg.foreign_tokens(szoveg, CIRILL_TERMEK) == []   # a kontextusban benne van


def test_ures_es_none():
    assert lg.foreign_tokens("") == [] and lg.foreign_tokens(None) == []
    assert lg.strip_foreign("") == "" and not lg.has_foreign_leak(None)


def test_dedup_es_sorrend():
    t = "\u043d\u0430\u0439\u0434\u0435\u043d\u043e itt \u00e9s \u043d\u0430\u0439\u0434\u0435\u043d\u043e ott, meg \u043f\u043e\u0440\u043e\u0434\u044b."
    assert lg.foreign_tokens(t) == ["\u043d\u0430\u0439\u0434\u0435\u043d\u043e", "\u043f\u043e\u0440\u043e\u0434\u044b"]


# --- vegso mentesz ---

def test_strip_hibrid_visszaadja_a_magyar_szot():
    assert lg.strip_foreign(HIBRID) == "Ez a mostani \u00e1r a legjobb, amit tal\u00e1ltam."


def test_strip_tisztan_idegen_szot_kivesz():
    out = lg.strip_foreign(UKRAN)
    assert "\u043d\u0430\u0439\u043a\u0440\u0430\u0449\u0435" not in out
    assert "  " not in out                      # nincs dupla szokoz
    assert out.startswith("Fontos: ez a \u00e1r")   # a mondat tobbi resze ep


def test_strip_tiszta_szoveget_nem_bant():
    assert lg.strip_foreign(TISZTA) == TISZTA


def test_strip_utan_nincs_idegen_betu():
    for t in (UKRAN, OROSZ, HIBRID, KUTYA):
        assert lg.foreign_tokens(lg.strip_foreign(t)) == []

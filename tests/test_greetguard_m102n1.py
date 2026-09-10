"""m102/1: ujrakoszones-or (greetguard). Fajl-betoltos import."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "greetguard.py"
_spec = importlib.util.spec_from_file_location("greetguard_m102n1", _p)
gg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gg)

H = [{"role": "user", "content": "Horgászszéket keresek"},
     {"role": "assistant", "content": "Ezeket ajánlom: ..."},
     {"role": "user", "content": "És karfás van?"}]
FIRST = [{"role": "user", "content": "Horgászszéket keresek"}]


class _Obj:
    def __init__(self, role, content):
        self.role, self.content = role, content


def test_levag_a_nem_elso_korben():
    assert gg.strip_regreet("Szia! Igen, van karfás horgászszékünk is: ...", "És karfás van?", H) == \
        "Igen, van karfás horgászszékünk is: ..."
    assert gg.strip_regreet("Szia Péter! Örülök, hogy nálunk rendelsz, az utánvét elérhető.", "utánvét?", H) == \
        "Örülök, hogy nálunk rendelsz, az utánvét elérhető."
    assert gg.strip_regreet("**Szia!** A rendelésed állapotát szívesen megnézzük.", "rendelés?", H) == \
        "A rendelésed állapotát szívesen megnézzük."


def test_ket_formula_egymas_utan():
    assert gg.strip_regreet("Szia! Üdvözöllek! 😊 Látom, hogy a Samsung órát nézed.", "ez jó?", H) == \
        "😊 Látom, hogy a Samsung órát nézed."


def test_vesszos_koszones_kisbetus_folytatas_nagybetusodik():
    assert gg.strip_regreet("Szia, a szállítás 2-3 munkanap a raktáron lévő termékeknél.", "szállítás?", H) == \
        "A szállítás 2-3 munkanap a raktáron lévő termékeknél."


def test_elso_korben_marad():
    r = "Szia! Ezeket a horgászszékeket ajánlom: ..."
    assert gg.strip_regreet(r, "Horgászszéket keresek", FIRST) == r
    assert gg.strip_regreet(r, "Horgászszéket keresek", []) == r
    assert gg.strip_regreet(r, "Horgászszéket keresek", None) == r


def test_ha_a_latogato_koszont_marad():
    r = "Szia! Miben segíthetek még a horgászszékkel kapcsolatban?"
    for m in ("Szia", "Sziasztok, még egy kérdés", "Jó napot!", "Jonapot", "Üdv", "Hello", "hali"):
        assert gg.strip_regreet(r, m, H) == r, m


def test_rovid_maradeknal_marad():
    assert gg.strip_regreet("Szia! 😊 Miben?", "hmm", H) == "Szia! 😊 Miben?"


def test_nem_koszones_valasz_valtozatlan():
    for r in ("Igen, van ilyen termék.", "Kedves vásárlónk, a rendelésed úton van.",
              "Hello Kitty plüss is kapható nálunk, 3 990 Ft.", "A(z) #1234 rendelésed állapota: kész"):
        assert gg.strip_regreet(r, "kérdés", H) == r, r


def test_pydantic_szeru_history_objektum():
    h = [_Obj("user", "a"), _Obj("assistant", "b"), _Obj("user", "c")]
    assert gg.strip_regreet("Szia! Igen, ez raktáron van most.", "raktáron?", h) == "Igen, ez raktáron van most."
    assert not gg.has_prior_bot_turn([_Obj("assistant", "  ")])


def test_hibas_bemenet_nem_dob():
    assert gg.strip_regreet(None, None, H) == ""
    assert gg.strip_regreet("Szia! Igen, ez raktáron van most.", "x", 5) == "Szia! Igen, ez raktáron van most."

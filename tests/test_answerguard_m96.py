"""m96: valasz-orseg egyseg-tesztek (fajl-betoltes, app-import nelkul).

A minta-szovegek VALODI konturreklam valaszokbol valok (messages tabla + a d31a
szal eles E2E-i), nem kitalalt peldak.
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "answerguard.py"
_spec = importlib.util.spec_from_file_location("answerguard_m96", _p)
ag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ag)

POLICY = {
    "redact_emails": ["info@konturreklam.hu"],
    "email_replacement": "https://www.konturreklam.hu/elerhetoseg",
    "gate_phones": ["+36 70 770 0396"],
}

# --- valodi eles valaszok ---------------------------------------------------
VALODI_MINDKETTO = (
    "Ez azt jelenti, hogy s\u00fcrg\u0151s esetben ak\u00e1r m\u00e1snapra is megkaphatod a rendel\u00e9sed.\n"
    "Ez k\u00e9szleten l\u00e9v\u0151 term\u00e9kekre \u00e9rv\u00e9nyes. Ha s\u00fcrg\u0151s a rendel\u00e9sed, "
    "\u00edrj az info@konturreklam.hu c\u00edmre vagy h\u00edvj minket a +36 70 770 0396-os "
    "sz\u00e1mon, hogy megn\u00e9zz\u00fck, mit tudunk v\u00e1llalni!"
)
VALODI_TELEFON_VEGEN = (
    "Sapk\u00e1n\u00e1l a leggyakoribb megold\u00e1s a g\u00e9pi h\u00edmz\u00e9s. "
    "Sapkah\u00edmz\u00e9sn\u00e9l a maxim\u00e1lis m\u00e9ret 12 x 5 cm.\n"
    "Az \u00e1r a log\u00f3 m\u00e9ret\u00e9t\u0151l f\u00fcgg, ez\u00e9rt egyedi \u00e1raj\u00e1nlatot adunk. "
    "Ha szeretn\u00e9d, felt\u00f6ltheted a log\u00f3t, vagy h\u00edvhatsz: +36 70 770 0396."
)
VALODI_HOZOTT = (
    "Ha hozott term\u00e9ket szeretn\u00e9l embl\u00e9m\u00e1ztatni, azt csak el\u0151zetes egyeztet\u00e9s "
    "ut\u00e1n tudjuk v\u00e1llalni - \u00edrj az info@konturreklam.hu c\u00edmre a r\u00e9szletekkel."
)


class _FakeMsg:
    """A /chat history eleme pydantic objektum -> getattr-rel kell olvasni."""

    def __init__(self, role, content):
        self.role = role
        self.content = content


# --- e-mail redakcio --------------------------------------------------------
def test_email_csere_megtortenik():
    out, info = ag.apply_policy(VALODI_HOZOTT, POLICY, "hozott bogret tudtok logozni")
    assert "info@konturreklam.hu" not in out
    assert "konturreklam.hu/elerhetoseg" in out
    assert info["email"] == 1


def test_email_csere_kis_nagybetu():
    out, _ = ag.apply_policy("Ird meg az INFO@KonturReklam.hu cimre.", POLICY, "szia")
    assert "@" not in out.replace("konturreklam.hu/elerhetoseg", "")


# --- telefon-kapu -----------------------------------------------------------
def test_telefon_kiesik_ha_nem_kertek():
    out, info = ag.apply_policy(VALODI_TELEFON_VEGEN, POLICY,
                                "Sapk\u00e1ra hogyan ker\u00fcl r\u00e1 a log\u00f3?")
    assert "770 0396" not in out
    assert info["phone"] >= 1
    assert info["asked"] is False
    assert "12 x 5 cm" in out          # az erdemi resz megmarad


def test_telefon_marad_ha_kertek():
    kerdes = "Meg tudn\u00e1tok adni a telefonsz\u00e1motokat?"
    out, info = ag.apply_policy(VALODI_TELEFON_VEGEN, POLICY, kerdes)
    assert "770 0396" in out
    assert info["asked"] is True
    assert info["phone"] == 0


def test_mindketto_egy_mondatban():
    out, _ = ag.apply_policy(VALODI_MINDKETTO, POLICY, "munkaruha m\u00e1snapra?")
    assert "info@konturreklam.hu" not in out
    assert "770 0396" not in out
    assert "m\u00e1snapra" in out         # nem urul ki


# --- history: CSAK a latogato szavai szamitanak -----------------------------
def test_user_history_text_csak_a_usert_veszi():
    hist = [
        _FakeMsg("user", "Sapk\u00e1t szeretn\u00e9k logózni"),
        _FakeMsg("assistant", "Sz\u00edvesen! Ha gyorsabb, h\u00edvj minket telefonon."),
        {"role": "user", "content": "\u00e9s mennyi id\u0151 alatt k\u00e9sz?"},
        {"role": "assistant", "content": "8-10 munkanap."},
    ]
    txt = ag.user_history_text(hist)
    assert "Sapk\u00e1t" in txt and "k\u00e9sz" in txt
    assert "telefonon" not in txt       # a bot sajat szava NEM


def test_bot_korabbi_valasza_nem_nyitja_ki_a_kaput():
    """Regresszio: ha egyszer kiment a 'hivj minket', a kapu ne maradjon nyitva."""
    hist = [
        _FakeMsg("user", "Mennyi a sz\u00e1ll\u00edt\u00e1si d\u00edj?"),
        _FakeMsg("assistant", "3 500 Ft + \u00e1fa. Ha k\u00e9rd\u00e9sed van, h\u00edvj minket "
                              "a +36 70 770 0396-os sz\u00e1mon."),
    ]
    out, info = ag.apply_policy(VALODI_TELEFON_VEGEN, POLICY,
                                "\u00e9s a sapka?", hist)
    assert info["asked"] is False
    assert "770 0396" not in out


def test_user_history_kinyitja_a_kaput():
    hist = [_FakeMsg("user", "Mi a telefonsz\u00e1motok?")]
    out, info = ag.apply_policy(VALODI_TELEFON_VEGEN, POLICY, "k\u00f6sz", hist)
    assert info["asked"] is True
    assert "770 0396" in out


# --- szandek-detektor -------------------------------------------------------
def test_phone_requested_pozitiv():
    for q in ("Mi a telefonsz\u00e1motok?", "h\u00edvhatlak titeket?",
              "Meg tudn\u00e1tok adni az el\u00e9rhet\u0151s\u00e9geteket?",
              "hivjatok fel legyen szives",          # ekezet nelkul is
              "van mobil sz\u00e1motok?"):
        assert ag.phone_requested(q), q


def test_phone_requested_negativ():
    for q in ("Sapk\u00e1ra hogyan ker\u00fcl r\u00e1 a log\u00f3?",
              "P\u00f3l\u00f3nyomtat\u00e1s \u00e1ra?",
              "Ez a hivatalos \u00e1raj\u00e1nlat?",        # 'hivatalos' NEM telefon-szandek
              "Milyen a hivatkoz\u00e1si sz\u00e1m?",
              "Mennyi a sz\u00e1ll\u00edt\u00e1si d\u00edj?"):
        assert not ag.phone_requested(q), q


# --- szam-alakok ------------------------------------------------------------
def test_phone_pattern_alakok():
    rx = ag.phone_pattern("+36 70 770 0396")
    for alak in ("+36 70 770 0396", "06 70 770 0396", "70/770-0396",
                 "+36707700396", "a +36 70 770 0396-os sz\u00e1mon"):
        assert rx.search(alak), alak


def test_phone_pattern_rovid_szam_nincs():
    assert ag.phone_pattern("123") is None


# --- tenant-kapu es fail-safe ----------------------------------------------
def test_policy_nelkul_erintetlen():
    for p in (None, {}, "nem dict", []):
        out, info = ag.apply_policy(VALODI_MINDKETTO, p, "b\u00e1rmi")
        assert out == VALODI_MINDKETTO
        assert info["email"] == 0 and info["phone"] == 0


def test_nem_urul_ki_ha_minden_mondat_telefonos():
    csak_tel = "H\u00edvj minket: +36 70 770 0396."
    out, _ = ag.apply_policy(csak_tel, POLICY, "mit csin\u00e1ltok")
    assert out.strip()
    assert "770 0396" not in out


def test_mas_szam_nem_esik_ki():
    """Csak a policy-ban felsorolt szam kapuzott."""
    txt = "A fut\u00e1rszolg\u00e1lat sz\u00e1ma: +36 1 802 0265, azt h\u00edvd csomag\u00fcgyben."
    out, info = ag.apply_policy(txt, POLICY, "mikor kapom meg")
    assert "802 0265" in out
    assert info["phone"] == 0

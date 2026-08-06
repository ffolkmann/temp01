"""kf/9: a kozos konfigurator-lead vegpont tiszta fuggvenyei — file-load import.

A modul stdlib-only, ezert az app-csomag betoltese nelkul teszteljuk (a suite
mas tesztjei fake `app.services`-t hagyhatnak a sys.modules-ben).
"""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konflead.py"
_spec = importlib.util.spec_from_file_location("konflead_under_test", _P)
kl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kl)


# --------------------------------------------------------------------------- #
# parse_body — a widget urlencoded-et kuld, a REST-hivo JSON-t
# --------------------------------------------------------------------------- #
def test_parse_body_urlencoded():
    d = kl.parse_body(b"tenant=copygo&name=Teszt+Elek&email=a%40b.hu")
    assert d["tenant"] == "copygo"
    assert d["name"] == "Teszt Elek"
    assert d["email"] == "a@b.hu"


def test_parse_body_json():
    d = kl.parse_body('{"client_id": "copygo", "name": "Teszt"}')
    assert d["client_id"] == "copygo" and d["name"] == "Teszt"


def test_parse_body_szemet_es_ures():
    assert kl.parse_body(b"") == {}
    assert kl.parse_body("{nem json") == {}
    assert kl.parse_body("[1,2,3]") == {}  # lista sem jo, dict kell


# --------------------------------------------------------------------------- #
# normalize
# --------------------------------------------------------------------------- #
def test_normalize_tenant_alias_es_kisbetu():
    p = kl.normalize({"tenant": "CopyGo", "name": "  Teszt   Elek "})
    assert p["client_id"] == "copygo"
    assert p["name"] == "Teszt Elek"


def test_normalize_client_id_eloz_meg_a_tenantot():
    p = kl.normalize({"client_id": "a", "tenant": "b"})
    assert p["client_id"] == "a"


def test_normalize_summary_sorvegei_megmaradnak():
    p = kl.normalize({"summary": "elso\r\nmasodik", "note": "sor1\nsor2"})
    assert p["summary"] == "elso\nmasodik"
    assert p["note"] == "sor1\nsor2"


def test_normalize_hosszkorlat():
    p = kl.normalize({"name": "x" * 500, "summary": "y" * 9000})
    assert len(p["name"]) == kl.MAX_NAME
    assert len(p["summary"]) == kl.MAX_SUMMARY


def test_normalize_honeypot_mezo():
    assert kl.normalize({"website": "http://spam"})["hp"] == "http://spam"
    assert kl.normalize({})["hp"] == ""


# --------------------------------------------------------------------------- #
# has_contact — e-mail VAGY telefon eleg
# --------------------------------------------------------------------------- #
def test_has_contact_email():
    assert kl.has_contact({"email": "a@b.hu"}) is True
    assert kl.has_contact({"email": "a@b"}) is False
    assert kl.has_contact({"email": "nincs-kukac"}) is False


def test_has_contact_telefon():
    assert kl.has_contact({"phone": "+36 30 123 4567"}) is True
    assert kl.has_contact({"phone": "123"}) is False


def test_has_contact_ures():
    assert kl.has_contact({}) is False
    assert kl.has_contact(None) is False


# --------------------------------------------------------------------------- #
# cimzett-feloldas
# --------------------------------------------------------------------------- #
def test_recipient_sorrend():
    cfg = {"to_email": "shop@x.hu", "fallback_email": "info@x.hu"}
    assert kl.recipient(cfg, "tenant@x.hu") == "shop@x.hu"
    assert kl.recipient({"fallback_email": "info@x.hu"}, "tenant@x.hu") == "tenant@x.hu"
    assert kl.recipient({"fallback_email": "info@x.hu"}, "") == "info@x.hu"
    assert kl.recipient({}, "") == ""


def test_recipient_ervenytelen_erteket_atlep():
    assert kl.recipient({"to_email": "nincs-kukac"}, "jo@x.hu") == "jo@x.hu"


def test_recipient_tobb_cimzett_megmarad():
    # a Mailgun vesszos listat is elfogad (a tenants.lead_email igy tarolja)
    assert kl.recipient({}, "a@x.hu,b@y.hu") == "a@x.hu,b@y.hu"


# --------------------------------------------------------------------------- #
# forward_url — csak http(s)
# --------------------------------------------------------------------------- #
def test_forward_url():
    assert kl.forward_url({"forward_url": "https://n8n.example/hook"}) == "https://n8n.example/hook"
    assert kl.forward_url({"forward_url": "javascript:alert(1)"}) == ""
    assert kl.forward_url({}) == ""


# --------------------------------------------------------------------------- #
# e-mail es tarolt alak
# --------------------------------------------------------------------------- #
def test_compose_alap():
    p = kl.normalize({"name": "Teszt", "email": "a@b.hu", "phone": "+36301234567",
                      "summary": "Valaszok:\n - Szines"})
    subj, body = kl.compose("copygo", p)
    assert "copygo" in subj
    assert "Teszt" in body and "a@b.hu" in body
    assert "--- KONFIGURATOR ---" in body and "Szines" in body


def test_compose_sajat_targy():
    subj, _ = kl.compose("copygo", {}, {"subject": "Ajanlatkeres a nyomtato-valasztobol"})
    assert subj == "Ajanlatkeres a nyomtato-valasztobol"


def test_stored_message_note_es_summary():
    msg = kl.stored_message({"note": "sietos", "summary": "Valaszok: A"})
    assert msg.startswith("sietos") and "Valaszok: A" in msg
    assert kl.stored_message({"summary": "csak ez"}) == "csak ez"
    assert kl.stored_message({}) == ""


def test_history_blob():
    h = kl.history_blob({"page": "https://x.hu/valaszto", "summary": "s"})
    assert h["kind"] == "konfigurator" and h["page"].endswith("valaszto")


def test_forward_payload_tartalmazza_a_tenantot():
    fp = kl.forward_payload("copygo", kl.normalize({"name": "T", "email": "a@b.hu"}))
    assert fp["tenant"] == "copygo" and fp["client_id"] == "copygo"
    assert fp["email"] == "a@b.hu"


# --------------------------------------------------------------------------- #
# rate limit kulcs / kliens IP
# --------------------------------------------------------------------------- #
def test_client_ip_xff_elso_eleme():
    assert kl.client_ip({"x-forwarded-for": "1.2.3.4, 10.0.0.1"}) == "1.2.3.4"
    assert kl.client_ip({"X-Forwarded-For": "5.6.7.8"}) == "5.6.7.8"


def test_client_ip_fallback():
    assert kl.client_ip({}, "9.9.9.9") == "9.9.9.9"
    assert kl.client_ip({}, "") == "anon"


def test_rl_key():
    assert kl.rl_key("copygo", "1.2.3.4") == "cx:rl:konflead:copygo:1.2.3.4"
    assert kl.rl_key("", "") == "cx:rl:konflead:?:anon"

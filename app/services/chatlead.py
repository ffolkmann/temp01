"""m100: a chatbe GEPELT e-mail-cim lead-rogzitese (source="chat").

Lelet (d10b_leadscan2, 30 nap, valodi `s_` sessionok): 42 latogatoi uzenetbol,
amiben szabad szovegben e-mail-cim allt, 18-ra a bot azt irta, hogy
"rogzitettem / kollegank hamarosan felveszi veled a kapcsolatot" - de lead
CSAK a widget lead-urlapjabol (type="lead") keletkezett, igy a bolt ezekrol
sosem kapott ertesitest (koztuk egy rendeles-lemondas es egy 492 890 Ft-os
arajanlat-keres). Feco dontese (2026-09-10): a chatbe irt cim a hozzajarulas-
checkbox nelkul is lead, `source="chat"` jelolessel.

Ugyanitt `strip_contacts`: az intent.detect_order_intent a rendelesszamot a
latogato e-mail-cime es telefonszama NELKUL keresi (a "0630/235-7558"
telefonszam "235-7558" rendelesszamnak, a "kovacs.1985@..." cim "1985"-nek
latszott -> a kapcsolatfelvetel rendeles-lekeresbe fulladt).

Stdlib-only: a tesztek fajlbol toltik be, az intent.py importalja.
"""

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# magyar telefonszam: +36 / 06 elotag, 1-2 jegyu korzet, majd 6-7 jegy tagolva
# (0630/235-7558, +36308149415, +36 70 616 0856, 06 20 360 27 97, 0620/3602797)
PHONE_RE = re.compile(
    r"(?<![\d+])(?:\+\s?36|06)[\s./-]*\(?\d{1,2}\)?[\s./-]*\d{3}[\s./-]*\d{2,4}"
    r"(?:[\s./-]*\d{2})?(?!\d)"
)

# a widget rendeles-urlapja ezt kuldi: "rendelésszám #57035, e-mail: x@y.hu"
_FORM_ORDER_RE = re.compile(r"^\s*rendel\w*\s*#", re.IGNORECASE)

MAX_EMAIL = 160
MAX_PHONE = 40


def strip_contacts(text) -> str:
    """Az e-mail-cimek es telefonszamok helyen szokoz (rendelesszam-kereseshez)."""
    s = EMAIL_RE.sub(" ", str(text or ""))
    return PHONE_RE.sub(" ", s)


def extract_contact(message):
    """{"email", "phone"} ha a latogato SZABAD SZOVEGBEN e-mail-cimet irt, kulonben None.

    A widget rendeles-urlapjanak uzenete nem lead (az rendeles-lekeres).
    """
    msg = str(message or "")
    if not msg.strip() or _FORM_ORDER_RE.search(msg):
        return None
    m = EMAIL_RE.search(msg)
    if not m:
        return None
    email = m.group(0).strip().strip(".")[:MAX_EMAIL]
    if "@" not in email:
        return None
    ph = PHONE_RE.search(msg)
    phone = re.sub(r"\s+", " ", ph.group(0)).strip()[:MAX_PHONE] if ph else ""
    return {"email": email, "phone": phone}


def should_capture(action) -> bool:
    """Rendeles-urlapos valasznal a widget urlapja viszi tovabb; operatornal a pult."""
    return str(action or "") not in ("order_status_form", "operator_wait")


def is_shop_email(email, domains) -> bool:
    """A bolt SAJAT cime (pl. info@<bolt-domain>) nem latogatoi lead."""
    e = str(email or "").strip().lower()
    if "@" not in e:
        return False
    dom = e.rsplit("@", 1)[1]
    for d in re.split(r"[,\s;]+", str(domains or "").lower()):
        d = re.sub(r"^https?://", "", d.strip()).split("/")[0]
        if d.startswith("www."):
            d = d[4:]
        if d and (dom == d or dom.endswith("." + d)):
            return True
    return False

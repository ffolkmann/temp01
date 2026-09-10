"""m101: platform rendeles-statusz -> magyar felirat. Stdlib-only (fajlbol toltheto).

Lelet (d10b_review2): nagyonallatshopon 14 sikeres lekeresnel a latogato ezt kapta:
"A(z) #75527 rendelesed allapota: processing." -- a WooCommerce REST a nyers
angol slugot adja. Egyedi (bolt-sajat) statusznal a slug valtozatlan marad.
"""

WOO_STATUS_HU = {
    "pending": "Fizetésre vár",
    "processing": "Feldolgozás alatt",
    "on-hold": "Függőben (fizetés beérkezésére vár)",
    "completed": "Teljesítve",
    "cancelled": "Törölve",
    "refunded": "Visszatérítve",
    "failed": "Sikertelen fizetés",
    "checkout-draft": "Folyamatban",
}


def woo_status_hu(slug) -> str:
    s = str(slug or "").strip()
    if not s:
        return "ismeretlen"
    k = s.lower()
    if k.startswith("wc-"):
        k = k[3:]
    return WOO_STATUS_HU.get(k, s)

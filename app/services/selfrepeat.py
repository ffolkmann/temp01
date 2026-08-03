"""m78: determinisztikus onismetles/elavult-ar detektor (m77 utod).

Ket jelenseg:
1) verbatim onismetles — a modell a historybeli sajat valaszat masolja
   (normalizalt egyezes/tartalmazas, min. hossz mindket oldalon);
2) elavult-ar horgony — a modell UJ szoveggel, de a historybeli regi
   arat/konkluziot ismetli a friss kontextus-minimum helyett
   (ar-token atfedes a valasz es egy korabbi assistant-fordulo kozott).
Csak stdlib (re) — tesztbol kozvetlenul fajl-betoltheto.
"""
import re

_PRICE_RE = re.compile(r"(\d{1,3}(?: \d{3})+|\d{4,7})\s*Ft")


def _norm(s):
    return "".join((s or "").lower().split()).replace("\u00a0", "")


def is_self_repeat(reply, old_replies, min_len=120):
    n = _norm(reply)
    if len(n) < min_len:
        return False
    for o in old_replies or []:
        m = _norm(o)
        if len(m) >= min_len and (n == m or m in n or n in m):
            return True
    return False


def price_tokens(s):
    t = (s or "").replace("\u00a0", " ")
    return {m.group(1).replace(" ", "") for m in _PRICE_RE.finditer(t)}


def has_stale_price(reply, old_replies):
    rp = price_tokens(reply)
    if not rp:
        return False
    for o in old_replies or []:
        if rp & price_tokens(o):
            return True
    return False

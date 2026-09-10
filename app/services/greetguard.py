"""m102/1: UJRAKOSZONES-ORSEG - a nem-elso korben a valasz elejerol a puszta koszonest levagja.

Mert lelet (d10c, 2026-09-10, teljes 30 napos korpusz): a folyamatban levo beszelgetesek
nem-elso koreinek 11%-a (1551-bol 172; fishingoutlet 493-bol 120 = 24%) "Szia!"-val kezdodott,
holott a latogato nem koszont ujra. A tenant-promptok nem kerik (csak a tegezodest), a modell
hajlama. A m77 tanulsaga szerint az ilyen stilus-hibara determinisztikus utofeldolgozas kell.

Szabalyok:
- csak ha a history-ban mar van KORABBI bot-valasz (a widget az aktualis uzenetet is a
  history vegere teszi, ezert a "van user-elem" nem eleg);
- ha a latogato maga is koszont ebben az uzenetben, a visszakoszones marad;
- legfeljebb ket egymas utani koszono formula ("Szia! Udvozollek! ...");
- ha a maradek 15 karakternel rovidebb, nem nyulunk hozza; kisbetus kezdest nagybetusit.

PURE, stdlib-only modul (fajl-betoltheto a tesztbol).
"""

import re
import unicodedata

_UP = u"A-Z\u00c1\u00c9\u00cd\u00d3\u00d6\u0150\u00da\u00dc\u0170"
_LEAD = re.compile(
    u"^\\s*(?:\\*\\*)?(?:Szia(?:sztok)?|Szervusz(?:tok)?|\u00dcdv(?:\u00f6zl\u00f6m|\u00f6z\u00f6llek|\u00f6zlet)?|"
    u"Hell\u00f3|Hello|Hali|J\u00f3 (?:napot|reggelt|est\u00e9t)(?: k\u00edv\u00e1nok)?|Kedves)"
    u"(?:[ ,]+[" + _UP + u"][\\w.-]*){0,2}\\s*(?:\\*\\*)?\\s*[!,.]+(?:\\*\\*)?\\s*",
    re.U)
_USERGREET = re.compile(
    r"^\W*(szia\w*|szervusz\w*|udv\w*|hell?o\w*|hali\w*|hi|hey|csao|jo ?(napot|reggelt|estet)\w*|kedves)\b")
_MIN_REST = 15


def _fold(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def user_greeted(message) -> bool:
    return bool(_USERGREET.match(_fold(message)))


def _role(h):
    if isinstance(h, dict):
        return h.get("role"), h.get("content")
    return getattr(h, "role", None), getattr(h, "content", None)


def has_prior_bot_turn(history) -> bool:
    try:
        for h in history or []:
            r, c = _role(h)
            if r == "assistant" and str(c or "").strip():
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def strip_regreet(reply, message, history) -> str:
    """A valasz koszonessel kezdodo elejet levagja, ha a beszelgetes mar folyik es a
    latogato nem koszont. Barmi hiba / bizonytalansag -> a valasz valtozatlan."""
    r = str(reply or "")
    try:
        if not r or not has_prior_bot_turn(history) or user_greeted(message):
            return r
        out = r
        for _ in range(2):
            m = _LEAD.match(out)
            if not m:
                break
            out = out[m.end():]
        if out == r:
            return r
        rest = out.lstrip()
        if len(rest) < _MIN_REST:
            return r
        if rest[:1].islower():
            rest = rest[:1].upper() + rest[1:]
        return rest
    except Exception:  # noqa: BLE001 - az or hibaja sose torje a valaszt
        return r

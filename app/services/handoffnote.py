# -*- coding: utf-8 -*-
"""m119: e-mailes atadas (handoff) utani onellentmondas ellen (stdlib-only, tiszta fuggvenyek).

Lelet (notebookstore, 2026-10-14): a bot kanned valasza ("Természetesen! 📨 Továbbítottam a
beszélgetésünket a kollégáinknak...") utan a latogato beirta a telefonszamat, a modell pedig a
sajat korabbi uzenetet hamisnak velte es visszavonta ("nem ember vagyok, nem tudom garantalni,
hogy eljutott"), pedig a rendszer a handoff-levelet tenylegesen elkuldte, es a telefonszamot
(m100/m101) leadkent rogzitette es tovabbitotta. Ok: a kanned uzenetet nem a modell irta, igy nem
tudja, hogy igaz. Javitas: ha az elozmenyben ott a handoff-valasz, a dinamikus promptba egy
rendszer-teny kerul.
"""

HANDOFF_MARK = "továbbítottam a beszélgetésünket"  # m120: kisbetus osszevetes (oszinte valtozat is)

# m120: ha a latogato azt kerdezi/kerte, ember-e a bot, a kanned "Természetesen!" igennek hangzik ->
#       a modell utana helyesbitett ("nem ember vagyok, az elozo felrevezeto volt"). Feco 10-15: oszinte eleje.
HONEST_REPLY = (
    "A bolt online asszisztense vagyok, de 📨 továbbítottam a beszélgetésünket a kollégáimnak. "
    "Kérlek, add meg az e-mail-címed (és ha szeretnéd, a telefonszámod), hogy mielőbb fel tudják "
    "venni veled a kapcsolatot."
)

NOTE = (
    "\n\n# KORÁBBI ÁTADÁS (rendszer-tény, igaz)\n"
    "Ebben a beszélgetésben a rendszer már ténylegesen e-mailben továbbította a beszélgetést a bolt "
    "munkatársainak — ez az előzményben szereplő „Továbbítottam a beszélgetésünket…” üzenet, és igaz. "
    "Ha a látogató ezután telefonszámot vagy e-mail-címet ír, azt a rendszer automatikusan rögzíti és "
    "szintén eljuttatja a kollégáknak. Ezt soha ne vond vissza, ne mondd, hogy nem tudod garantálni, "
    "és ne kérd újra ugyanazt az elérhetőséget: köszönd meg, és mondd, hogy a kollégák a megadott "
    "elérhetőségen keresik. Pontos visszahívási időpontot ne ígérj. Ha a bolt ügyfélszolgálata most "
    "elérhető, a számát megadhatod, ha a látogató azonnal beszélne valakivel."
)


def _field(h, name):
    v = getattr(h, name, None)
    if v is None and isinstance(h, dict):
        v = h.get(name)
    return v or ""


def handoff_done(history) -> bool:
    """True, ha az elozmenyben van bot-oldali e-mailes atadas-uzenet."""
    for h in history or []:
        if _field(h, "role") == "assistant" and HANDOFF_MARK in str(_field(h, "content")).lower():
            return True
    return False


_FOLD = str.maketrans("áéíóöőúüű", "aeiooouuu")
import re as _re  # noqa: E402

_HUMAN_RE = _re.compile(
    r"\b(emberrel|ember vagy|ember-e|ember van|ember valaszol|ember ir|elo ember|valodi ember|"
    r"valodi szem|hus.?ver|robot|gep(pel)? (beszel|irok|levelez)|gep vagy|bot vagy|botot|"
    r"chatbot|mesterseges intelligencia|\bai\b|automata)"
)


def asks_human(message) -> bool:
    """m120: a latogato arra kerdez/arra utal, hogy emberrel vagy geppel beszel-e."""
    t = str(message or "").lower().translate(_FOLD)
    return bool(_HUMAN_RE.search(t))


def reply_for(message, default: str) -> str:
    """m120: az e-mailes atadas kanned valasza - ember/robot-kerdesnel az oszinte valtozat."""
    return HONEST_REPLY if asks_human(message) else default


# --- m124: tenantonkenti atadas-valasz (tenants.handoff_replies) ---
import unicodedata as _ud  # noqa: E402


def _fold124(s) -> str:
    s = str(s or "").lower()
    s = _ud.normalize("NFD", s)
    return "".join(c for c in s if not _ud.combining(c))


def tenant_reply(message, rules, default: str) -> str:
    """m124: a tenant sajat atadas-valasza (tenants.handoff_replies, jsonb lista).

    Elem: {"match": "<reszlet>", "reply": "<szoveg>"}; match "*" = minden atadasra.
    A konkret match (ekezet-strip + kisbetu reszlet-egyezes, min. 3 karakter) elobb nyer, mint a "*".
    Orseg: a valasz 20..800 karakter es tartalmazza a HANDOFF_MARK-ot (kulonben az m119
    rendszer-teny nem kapcsolna be) - kulonben a default marad.
    Kivalto: notebookstore 'Céges érdeklődés' gomb (Laci, 10-21) - atadaskor kerdezzen ra a termekre/darabszamra.
    """
    if not isinstance(rules, list) or not rules:
        return default
    a = _fold124(message)
    star = None
    for r in rules:
        if not isinstance(r, dict):
            continue
        rep = r.get("reply")
        m = str(r.get("match") or "").strip()
        if not isinstance(rep, str) or not (20 <= len(rep.strip()) <= 800):
            continue
        if HANDOFF_MARK not in rep.lower():
            continue
        if m == "*":
            if star is None:
                star = rep.strip()
            continue
        k = _fold124(m)
        if len(k) >= 3 and k in a:
            return rep.strip()
    return star or default

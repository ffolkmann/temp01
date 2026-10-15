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

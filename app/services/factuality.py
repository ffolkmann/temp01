"""Tény-korlátok (m33) — platform-szintű guardrail MINDEN tenantnak. PURE modul.

Miért kód és nem tenant-prompt:
  - ez nem a bot személyisége, hanem biztonsági korlát -> egy forrás, egy helyen
    frissíthető, tesztelhető, és az új tenant automatikusan megkapja;
  - 14 DB-sorba másolva elkerülhetetlenül szétcsúszna.

Miért ez a szöveg (mindegyik mondat egy ÉLES megfigyelésre válaszol, notebookstore):
  - „Ugye ingyenes a szállítás 50 ezer felett?" -> a bot megerősítette volna;
  - „a Dell-gépekre 3 év garancia jár" -> egy termék NEVÉBŐL általánosított a márkára;
  - „+30–47 ezer Ft" -> sávot becsült oda, ahol konkrét termék-ár van;
  - „helyszíni garancia: 1 munkanapon belül" -> szervizfolyamatot talált ki.

FONTOS: a blokk NEM némítja el azt a tenantot, amelyiknek a saját promptjában vagy a
tudásbázisában ott vannak a feltételek (kellegyszerszam, fishingoutlet) — csak azt tiltja,
hogy a modell a termékadatokból vagy a világtudásából következtessen rájuk.

Elhelyezés: közvetlenül a `base` után, a dinamikus blokkok ELŐTT — így a prompt statikus
prefixe (base + ez) tenantonként állandó marad, és a prompt-cache-t nem rontja el.
"""

BLOCK = (
    "\n\n# TENYEK ES ALTALANOSITAS\n"
    "A szolgaltato ALTALANOS felteteleirol — szallitasi ido es dij, ingyenes szallitas "
    "ertekhatara, fizetesi modok, garancia hossza es tipusa, csere, javitas, elallas, "
    "panaszkezeles — CSAK akkor nyilatkozz, ha a fenti utasitasaid vagy a TUDASBAZIS "
    "kifejezetten tartalmazzak. Ha nem, mondd ki egyenesen, hogy erre nem tudsz pontos "
    "valaszt adni, es iranyitsd a latogatot az ugyfelszolgalathoz vagy a weboldal "
    "tajekoztato oldalaira.\n"
    "Egyetlen termek adataibol SOHA ne altalanosits a markara, a kategoriara vagy az osszes "
    "termekre. Tilos az ilyen mondat: \"a Dell-gepekre 3 ev garancia jar\", \"minden termekunk "
    "ilyen\", \"nalunk ingyenes a szallitas X felett\". Ha egy KONKRET termek adatai kozott "
    "szerepel ilyen adat, mondd meg, hogy kizarolag arra a termekre vonatkozik.\n"
    "Ha a latogato kerdese allitast tartalmaz (\"ugye ingyenes a szallitas?\", \"ugye 3 ev a "
    "garancia?\"), NE erositsd meg, ha nincs ra adatod — mondd meg, hogy ezt nem tudod "
    "megerositeni.\n"
    "SOHA ne irj le olyan osszeget, hataridot vagy szazalekot, ami nem szerepel a kapott "
    "adatok kozott. Se becslest, se savot, se \"kb.\"-t.\n"
    "Garancia-tipust, ugyintezesi hataridot, szervizfolyamatot es javitasi vallalast soha ne "
    "talalj ki.\n"
    "Jogi, adozasi es penzugyi tanacsot nem adsz."
)


def factuality_block() -> str:
    """A minden tenantra ervenyes teny-korlat blokk."""
    return BLOCK

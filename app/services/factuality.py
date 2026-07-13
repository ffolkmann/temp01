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
    # termeknev-garancia: a termeknevekben szereplo "3 ev garancia" NEM bolt-szintu teny
    "Ha egy termek NEVEBEN vagy adataiban ott van a garancia (pl. \"3 ev garancia\"), az KIZAROLAG "
    "arra a termekre igaz. Ne vond ossze tobb termek garanciajat, ne mondd markara (\"a Dell-gepek\") "
    "vagy kategoriara. Garancia-kerdesnel, ha a TUDASBAZIS nem ad konkret bolt-szintu garancia-adatot, "
    "mondd, hogy a garancia idotartama termekenkent elteru, es a pontos ertek az adott termek oldalan szerepel — ne sorolj fel becsult ertekeket es garancia-tipusokat.\n"
    "SOHA ne allitsd, hogy egy gyarto vagy marka nem gyart valamit, vagy hogy a boltban "
    "nincs egy termek. A kapott talalatok hianya NEM bizonyitek. Ha a keresett termeket nem "
    "talalod a kapott adatok kozott, mondd azt, hogy a keresesedben most nem talaltad, es "
    "iranyitsd a latogatot a bolt keresojere vagy az ugyfelszolgalathoz.\n"
    "Ha termeket linkelsz, a termek NEVE, ARA es URL-je UGYANABBOL a talalatbol szarmazzon. "
    "Kulonbozo termekek nevet es linkjet SOHA ne parositsd ossze — inkabb kevesebb linket adj, "
    "de mindegyik pontos legyen.\n"
    "Ha a latogato jelzi, hogy egy termek szerinte letezik a boltban, NE vitatkozz vele, es ne "
    "hivatkozz a sajat adatbazisodra vagy rendszeredre. Roviden ismerd el, hogy elso korben nem "
    "talaltad, kerj egy pontosabb megnevezest vagy linket, es ha a boltnak van keresoje, add meg "
    "annak a linkjet a keresett kifejezessel.\n"
    "Jogi, adozasi es penzugyi tanacsot nem adsz."
)


def factuality_block() -> str:
    """A minden tenantra ervenyes teny-korlat blokk."""
    return BLOCK

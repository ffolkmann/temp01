"""m131 (K8): BESZEDMOD-ORSEG - a bot a sajat mukodeset emlegeto fordulatokat kodbol veszi ki.

Mert lelet (d21h, 2026-10-21, 30 napos korpusz, 3538 valasz): a m102/2 prompt-szabaly
(factuality BESZEDMOD) utan is ~30 valaszban maradt "a talalataim kozott" (16),
"a rendelkezesemre allo adatok/informaciok/termekek kozott|alapjan" (10), "a keresesem
alapjan" (2), "a kapott/megadott (termek)adatok kozott" (3). A vevo ezt ugy olvassa:
"te vagy az elado, es nem tudod, mi van a boltban?" (kellegyszerszam). A m77 tanulsaga:
stilus-hibara determinisztikus utofeldolgozas kell, a prompt nem eleg.

Szabaly (PURE, stdlib-only, fail-safe):
- a fordulat ("a mostani/jelenlegi/fenti talalataim/ajanlataim kozott", "a rendelkezesemre allo
  X kozott/alapjan", "a keresesem alapjan/soran", "a kapott/megadott (termek)adatok
  kozott/alapjan", "az adataim kozott") kikerul a mondatbol;
- ha a mondat enelkul mar nem mondja ki, HOL nincs a termek (nincs benne webaruhaz /
  kinalat / bolt / webshop / adatlap), es a fordulat "kozott"-re vegzodik, a helyere
  "a kinalatban" kerul (igy "Sajnos a jelenlegi talalataim kozott nincs ilyen bot" ->
  "Sajnos a kinalatban nincs ilyen bot"); kulonben torles ("nem latok a webaruhazban
  olyan nyomtatot a talalataim kozott, amivel" -> "nem latok a webaruhazban olyan
  nyomtatot, amivel");
- "alapjan"-ra vegzodo fordulat mindig torlodik ("nem tudom megmondani a rendelkezesemre
  allo informaciok alapjan, ezert" -> "nem tudom megmondani, ezert");
- iras-tisztitas CSAK a valtozott sorokon: dupla szokoz, " ," -> ",", " ." -> ".", mondatkezdo
  kisbetu nagybetusitese;
- markdown-link szovegebe / URL-be nem nyul (a linkeket elobb kimaszkolja).
"""

import re
import unicodedata

# A fordulat: nevelo + (jelzo)? + a bot-ra utalo birtokos kifejezes + utolo (kozott|kozt|alapjan|soran).
_DET = r"(?:a|az)\s+"
_ADJ = r"(?:(?:mostani|jelenlegi|fenti|eddigi|aktu[aá]lis)\s+)?"
_CORE = (
    r"(?:"
    r"tal[aá]lat(?:aim|aink)"
    r"|aj[aá]nlat(?:aim|aink)"
    r"|keres[eé]s(?:em|[eü]nk)"
    r"|rendelkez[eé]s(?:em|[uü]nk)re\s+[aá]ll[oó]\s+(?:term[eé]k-?)?(?:adatok|inform[aá]ci[oó]k|term[eé]kek|tal[aá]latok|lista|adatb[aá]zis)"
    r"|(?:kapott|megadott|be[eé]rkezett|(?:most\s+)?el[eé]rhet[oő])\s+(?:term[eé]k-?)?(?:adatok|inform[aá]ci[oó]k|lista|tal[aá]latok)"
    r"|adat(?:aim|aink)"
    r"|(?:adat|tud[aá]s)b[aá]zis(?:om|unk)(?:ban)?"
    r")"
)
_TAIL = r"\s+(?:k[oö]z[oö]tt|k[oö]zt|alapj[aá]n|sor[aá]n|szerint)"
_PHRASE = re.compile(r"(?<![\w-])" + _DET + _ADJ + _CORE + _TAIL + r"(?![\w-])", re.I | re.U)
# "a tudasbazisomban / az adatbazisomban" onmagaban (utolo nelkul) is a sajat mukodes.
_BARE = re.compile(r"(?<![\w-])(?:a|az)\s+(?:adat|tud[aá]s)b[aá]zis(?:om|unk)ban(?![\w-])", re.I | re.U)
_PLACE = re.compile(r"web[aá]ruh[aá]z|k[ií]n[aá]lat|bolt|webshop|shop|adatlap|term[eé]koldal", re.I | re.U)
_LINK = re.compile(r"\[[^\]\n]*\]\([^)\s]*\)")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    start = 0
    for m in re.finditer(r"[.!?]\s+|\n", text[:pos]):
        start = m.end()
    m2 = re.search(r"[.!?](?=\s|$)|\n", text[pos:])
    end = pos + m2.end() if m2 else len(text)
    return start, end


def _tidy(s: str) -> str:
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r",\s*,", ",", s)
    return s


def rewrite(reply: str) -> tuple[str, int]:
    """(uj szoveg, csere-darab). Barmi hiba -> (eredeti, 0)."""
    r = str(reply or "")
    if not r:
        return r, 0
    try:
        # linkek kimaszkolasa, hogy a link-szovegbe / URL-be ne nyuljunk
        links: list[str] = []

        def _mask(m):
            links.append(m.group(0))
            return "\x00%d\x00" % (len(links) - 1)

        work = _LINK.sub(_mask, r)
        n = 0
        out = work
        # tobbszori futas: egy mondatban ket fordulat is lehet
        for _ in range(4):
            m = _PHRASE.search(out) or _BARE.search(out)
            if not m:
                break
            s0, s1 = _sentence_bounds(out, m.start())
            rest = (out[s0:m.start()] + " " + out[m.end():s1])
            ends_with_place = m.group(0).strip().lower().endswith(("alapján", "alapjan", "során", "soran", "szerint"))
            core = _fold(m.group(0))
            product_like = bool(re.search(r"talalat|ajanlat|termekek|adataim|adataink", core))
            if not ends_with_place and product_like and not _PLACE.search(_fold(rest)) and m.re is _PHRASE:
                repl = "a kínálatban"
            else:
                repl = ""
            # ha a fordulat a mondat elejen all es toroljuk, a kovetkezo szo nagybetus lesz
            before = out[:m.start()]
            after = out[m.end():]
            if repl == "":
                # a fordulat elotti/utani szokoz osszevonasa
                if before.endswith(" ") and after.startswith((" ", ",", ".", ")", "!", "?")):
                    before = before[:-1]
                new = before + after
                head = out[s0:m.start()].strip()
                if not head or head.endswith(("!", "?", ".")):
                    # mondatkezdo: a kovetkezo betut nagybetusitjuk
                    idx = len(before)
                    while idx < len(new) and new[idx] in " \t":
                        idx += 1
                    if idx < len(new) and new[idx].islower():
                        new = new[:idx] + new[idx].upper() + new[idx + 1:]
            else:
                new = before + repl + after
                head = out[s0:m.start()].strip()
                if not head or head.endswith(("!", "?", ".")):
                    new = before + "A kínálatban" + after
            out = new
            n += 1
        if n == 0:
            return r, 0
        # iras-tisztitas CSAK a valtozott sorokon (a tobbi sor - pl. behuzott lista - erintetlen)
        _wl = work.split("\n"); _ol = out.split("\n")
        if len(_wl) == len(_ol):
            out = "\n".join(_tidy(o) if o != w else o for w, o in zip(_wl, _ol))
        out = re.sub(r"\x00(\d+)\x00", lambda mm: links[int(mm.group(1))], out)
        return out, n
    except Exception:  # noqa: BLE001 - az or hibaja sose torje a valaszt
        return r, 0

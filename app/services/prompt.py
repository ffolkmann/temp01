"""Build Prompt — a prod `Build Prompt` Code node portja (lásd seed/prod_chat_logic.txt).

A `system` szöveg sorrend-érzékenyen épül fel: base -> AKTUALIS TERMEK -> TUDASBAZIS ->
KAPCSOLODO TERMEKEK -> (TOVABBI) HASONLO TERMEKEK -> AZONOS MARKA -> LINKELES -> AJANLAS ->
AKTUALIS OLDAL -> ELALLAS -> ELERHETO KUPONOK -> VALASZ FORMATUM.

NEM portolt (Sellvio live-API ág, `Has Live API?`=true): a # ELO FRISS AR/KESZLET és a
# WEBSHOP TERMEKEK blokk + a Sellvio kategória/márka lista. A márka/hasonló blokkok itt a
Qdrant (reranked) találatokból épülnek (KB-fallback), ahogy a prod is teszi embedded
katalógusú platformoknál.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.models.db_models import Coupon, Tenant
from app.services.current_product import CurrentProduct
from app.services.live_product import LivePriceStock

_DEFAULT_BASE = (
    "Te egy webshop udvarias, magyar nyelvu asszisztense vagy. "
    "Csak a megadott adatokbol valaszolj, ne talalgass."
)


@dataclass
class PromptContext:
    page_is_product: bool
    page_product_name: str
    page_url: str
    page_url_norm: str


def _huf(n: float) -> str:
    """Egész Ft ezres szóköz-tagolással (prod huf2/hufB)."""
    s = str(round(n))
    # ezres tagolás szóközzel, hátulról
    parts = []
    while len(s) > 3:
        parts.insert(0, s[-3:])
        s = s[:-3]
    parts.insert(0, s)
    return " ".join(parts) + " Ft"


def _fmt_price(v: Any) -> str:
    """A prod fmtPrice2/fmtB: ha betűt tartalmaz, ahogy van; különben számból huf."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if any(c.isalpha() for c in s):
        return s
    try:
        n = float(s.replace(" ", "").replace(",", "."))
    except ValueError:
        return ""
    return _huf(n)


def _parse_rel_list(s: str) -> list[str]:
    """related_similar/related_additional: 'név — url; név — url' -> ['- név Link: url', ...]."""
    out: list[str] = []
    for piece in str(s or "").split(";"):
        piece = piece.strip()
        if not piece:
            continue
        idx = piece.rfind(" — ")
        if idx >= 0:
            nm, url = piece[:idx].strip(), piece[idx + 3:].strip()
        else:
            nm, url = piece, ""
        if not nm:
            continue
        line = "- " + nm
        if url:
            line += " Link: " + url
        out.append(line)
    return out


def _chunks(hits: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for r in hits:
        p = r.get("payload", {}) or {}
        t = p.get("text") or p.get("content") or p.get("chunk") or ""
        if t:
            out.append(str(t))
    return out


def _kb_similar(hits: list[dict[str, Any]], page_url: str, main_name: str) -> list[str]:
    """# (TOVABBI) HASONLO TERMEKEK — reranked Qdrant termékek, page_url + main_name kihagyva."""
    seen: set[str] = set()
    out: list[str] = []
    for r in hits:
        p = r.get("payload", {}) or {}
        if p.get("type") != "product":
            continue
        nm = str(p.get("name") or "")
        if not nm:
            continue
        url = str(p.get("url") or "").strip()
        if page_url and url and url == page_url:
            continue
        if main_name and nm == main_name:
            continue
        if nm in seen:
            continue
        seen.add(nm)
        line = "- " + nm
        pr = _fmt_price(p.get("price"))
        if pr:
            line += " — " + pr
        if url:
            line += " Link: " + url
        out.append(line)
        if len(out) >= 6:
            break
    return out


def _kb_brand(hits: list[dict[str, Any]], page_url: str) -> tuple[list[str], str]:
    """# AZONOS MARKA TERMEKEI — a page_url-egyező termék márkája alapján."""
    main_brand = ""
    for r in hits:
        p = r.get("payload", {}) or {}
        if p.get("type") == "product" and page_url and str(p.get("url") or "").strip() == page_url:
            main_brand = str(p.get("brand") or "").strip()
            break
    if not main_brand:
        return [], ""
    seen: set[str] = set()
    out: list[str] = []
    for r in hits:
        p = r.get("payload", {}) or {}
        if p.get("type") != "product":
            continue
        bn = str(p.get("brand") or "").strip()
        if not bn or bn != main_brand:
            continue
        nm = str(p.get("name") or "")
        if not nm:
            continue
        url = str(p.get("url") or "").strip()
        if page_url and url and url == page_url:
            continue
        if nm in seen:
            continue
        seen.add(nm)
        line = "- " + nm
        pr = _fmt_price(p.get("price"))
        if pr:
            line += " — " + pr
        if url:
            line += " Link: " + url
        out.append(line)
        if len(out) >= 6:
            break
    return out, main_brand


def _active_coupon_lines(coupons: list[Coupon]) -> list[str]:
    today = date.today().isoformat()
    lines: list[str] = []
    for c in coupons:
        if not (c.active is True):
            continue
        vu = str(c.valid_until or "")[:10]
        if vu and vu < today:
            continue
        line = "- " + str(c.code) + ": " + str(c.discount or "")
        if c.kind:
            line += " (" + str(c.kind) + ")"
        if c.conditions:
            line += " — " + str(c.conditions)
        if vu:
            line += " [ervenyes " + vu + "-ig]"
        lines.append(line)
    return lines


def _live_block(live: LivePriceStock, name: str) -> str:
    """# ELO, FRISS AR, KESZLET (ELSODLEGES) — élő API ár/készlet a synced helyett."""
    parts: list[str] = []
    pr = _fmt_price(live.price)
    if pr:
        parts.append("ar: " + pr)
    if live.qty is not None:
        in_stock = live.qty > 0 or live.available is True
        parts.append(f"keszlet: {live.qty} db " + ("(raktaron)" if in_stock else "(jelenleg nincs raktaron)"))
    elif live.available is not None:
        parts.append("keszlet: " + ("raktaron" if live.available else "jelenleg nincs raktaron"))
    if getattr(live, "note", ""):
        # m24: raktár-szemantika (pl. "külső raktáron: 6 db, szállítás: 4-5 munkanap")
        parts.append(live.note)
    if not parts:
        return ""
    nm = (name or "").strip()
    line = ("- " + nm + " — " if nm else "- ") + ", ".join(parts)
    return (
        "\n\n# ELO, FRISS AR, KESZLET (ELSODLEGES)\n"
        "Ez a termek ELO, frissen lekert ara es keszlete. Ha barmiben eltér a fenti "
        "# AKTUALIS TERMEK adatlaptol, az ARNAL es KESZLETNEL EZ az ervenyes — ezt hasznald, "
        "ne a szinkronizalt adatlap arat/keszletet:\n" + line
    )


def build_system_prompt(
    tenant: Tenant,
    hits: list[dict[str, Any]],
    current: CurrentProduct | None,
    coupons: list[Coupon],
    ctx: PromptContext,
    live: LivePriceStock | None = None,
) -> str:
    base = (tenant.system_prompt or "").strip() or _DEFAULT_BASE
    system = base

    # 2) # AKTUALIS TERMEK
    current_text = current.text if current else ""
    if ctx.page_is_product and current_text:
        system += (
            "\n\n# AKTUALIS TERMEK (pontos, ellenorzott adatlap)\n"
            "Ez annak a termeknek az adatlapja, amit a latogato EPPEN ezen az oldalon nez. "
            "A termek-specifikus kerdesekre (meret, muszaki parameter, vizallosag, hoszigeteles, "
            "legzarosag, ar, keszlet, tulajdonsag) ELSODLEGESEN es kizarolag ezt az adatlapot "
            "hasznald; ne keverd ossze mas meretu vagy mas kivitelu variansokkal. Ha itt szerepel "
            "az adat, abbol valaszolj, ne mondd hogy nincs informaciod:\n" + current_text
        )

    # 3) # TUDASBAZIS
    chunks = _chunks(hits)
    context = "\n\n---\n\n".join(chunks) if chunks else "(nincs talalat a tudasbazisban)"
    system += "\n\n# TUDASBAZIS\n" + context

    # 4) # ELO, FRISS AR, KESZLET — élő API ár/készlet (csak ha a hívó lekérte; a synced helyett)
    if live is not None:
        nm = live.name or (current.name if current else "") or ctx.page_product_name
        system += _live_block(live, nm)

    # 6) # KAPCSOLODO TERMEKEK (current product related_*; fallback: page_url-egyező reranked termék)
    rel_similar_raw = current.related_similar if current else ""
    rel_additional_raw = current.related_additional if current else ""
    if not rel_similar_raw and not rel_additional_raw:
        for r in hits:
            p = r.get("payload", {}) or {}
            u = str(p.get("url") or "").strip()
            if p.get("type") == "product" and u and (
                u == ctx.page_url or (ctx.page_url_norm and u == ctx.page_url_norm)
            ):
                rel_similar_raw = str(p.get("related_similar") or "")
                rel_additional_raw = str(p.get("related_additional") or "")
                break
    rel_similar = _parse_rel_list(rel_similar_raw)
    rel_additional = _parse_rel_list(rel_additional_raw)
    has_curated = bool(rel_similar or rel_additional)
    if has_curated:
        blk = (
            "\n\n# KAPCSOLODO TERMEKEK\n"
            "A webshop ehhez a termekhez kezzel beallitott, ellenorzott ajanlasai "
            "(kiegeszitok/tartozekok es hasonlo termekek). Ha a latogato ehhez a termekhez keres "
            "kiegeszitot, tartozekot vagy hasonlo termeket, ELSODLEGESEN ezeket ajanld, es vilagosan "
            "valaszd szet a ket csoportot."
        )
        if rel_additional:
            blk += "\nEhhez ajánljuk:\n" + "\n".join(rel_additional)
        if rel_similar:
            blk += "\nHasonló termékek:\n" + "\n".join(rel_similar)
        blk += (
            "\n\nFONTOS PRIORITAS: a fenti # KAPCSOLODO TERMEKEK a webshop altal kezzel valogatott, "
            "ellenorzott ajanlas, ezert MINDIG elsobbseget elvez a lentebbi automatikus "
            "(# TOVABBI HASONLO TERMEKEK) es marka-alapu (# AZONOS MARKA TERMEKEI) listakkal szemben. "
            "Ha a latogato kiegeszitot vagy tartozekot ker es az \"Ehhez ajánljuk:\" lista nem ures, "
            "KIZAROLAG abbol ajanlj. Ha hasonlo terméket ker es a \"Hasonló termékek:\" lista nem ures, "
            "eloszor abbol ajanlj. Az automatikus/marka-listakat csak akkor hasznald, ha a megfelelo "
            "kuratalt lista ures, vagy ha a latogato kifejezetten mas tipusu termeket ker."
        )
        system += blk

    # 7) # (TOVABBI) HASONLO TERMEKEK — KB fallback
    main_name = ""  # nincs Sellvio Pick Product Id a kód-magban
    similar = _kb_similar(hits, ctx.page_url, main_name)
    if similar:
        if has_curated:
            sim_lbl = "# TOVABBI HASONLO TERMEKEK (automatikus talalat, masodlagos)"
        else:
            sim_lbl = "# HASONLO TERMEKEK (automatikus talalat)"
        system += "\n\n" + sim_lbl + "\n" + "\n".join(similar)

    # 8) # AZONOS MARKA TERMEKEI — KB fallback
    brand_list, brand_name = _kb_brand(hits, ctx.page_url)
    if brand_list:
        suffix = (" (" + brand_name + ")") if brand_name else ""
        system += "\n\n# AZONOS MARKA TERMEKEI" + suffix + "\n" + "\n".join(brand_list)

    # 9) # LINKELES
    system += (
        "\n\n# LINKELES\n"
        "Amikor konkret termeket emlitesz vagy ajanlasz, a termek nevet alakitsd MARKDOWN LINKKE a "
        "hozza tartozo Link mezovel, igy: [Termek neve](Link). Csak a fenti listaban (TUDASBAZIS, "
        "KAPCSOLODO TERMEKEK, WEBSHOP TERMEKEK, HASONLO TERMEKEK vagy AZONOS MARKA TERMEKEI) szereplo "
        "linkeket hasznald, sose talalj ki URL-t. Ha egy termekhez nincs Link, ne linkeld."
    )

    # 10) # AJANLAS
    system += (
        "\n\n# AJANLAS\n"
        "Ha a fentiekben van # KAPCSOLODO TERMEKEK blokk, az ott szereplo kuratalt ajanlasok "
        "elsobbseget elveznek; az alabbi szabalyokat csak akkor alkalmazd, ha nincs kuratalt ajanlas "
        "vagy az nem fedi a latogato kereset. Ha a latogato hasonlo termekeket ker, vagy egy adott "
        "tulajdonsaggal (pl. nagyobb/kisebb teljesitmeny, adott energiaosztaly, halkabb mukodes, "
        "funkcio) rendelkezo termekeket keres, NE kerdezz vissza a marka-preferenciara. Ehelyett, ha "
        "az AZONOS MARKA TERMEKEI es a HASONLO TERMEKEK lista is tartalmaz relevans talalatot, ajanlj "
        "mindkettobol, vilagosan szetvalasztva: eloszor 2-3 azonos markaju termeket \"Ugyanettol a "
        "markatol:\" felvezetessel, majd 2-3 mas opciot \"Ha a marka nem szamit, ezek is szoba "
        "johetnek:\" felvezetessel, es hagyd, hogy a latogato valasszon. Ha csak a HASONLO TERMEKEK "
        "listaban van talalat (nincs hasznalhato marka-adat), egyszeruen abbol ajanlj 2-4 relevansat, "
        "marka-bontas nelkul. Ha a latogato kifejezetten egy MARKAT vagy GYARTOT nevez meg, az AZONOS "
        "MARKA TERMEKEI listat reszesitsd elonyben. Roviden indokold, miert illik az ajanlas a "
        "kereshez, es linkeld a termekeket. Csak a fenti listakban szereplo termekeket ajanld, ne "
        "talalj ki ujakat."
    )
    # m24: "nem talalom" eszkalacio — ELOSZOR a webshop keresojere mutatunk, nem a
    # vevoszolgalatra (ugyfel-keres: ne noveljuk a telefonhivasok szamat).
    plat = str(tenant.platform or "").strip().lower()
    pub = str(tenant.public_url or "").strip().rstrip("/")
    search_url = ""
    if pub and plat == "shoprenter":
        search_url = pub + "/kereses?keyword="
    elif pub and plat == "woocommerce":
        search_url = pub + "/?s="
    if search_url:
        system += (
            " Ha egyik listaban sincs megfelelo termek, mondd el oszinten, ajanld a legkozelebbi "
            "alternativat, ES add meg a webaruhaz keresojenek linkjet a keresett kifejezessel, "
            "markdown linkkent: [Keresés a webáruházban](" + search_url + "<kifejezes>) — a "
            "<kifejezes> helyere a latogato altal keresett szavakat ird, szokozok helyett + jellel "
            "(pl. bait+bait+bojli). Jelezd, hogy ott a teljes kinalat lathato. Az elerhetoseg "
            "elkereset (collect_lead) csak akkor ajanld fel, ha a latogato kifejezetten kollegatol "
            "ker segitseget, vagy a kereso-link sem segitett."
        )
    else:
        system += (
            " Ha egyik listaban sincs megfelelo termek, mondd el oszinten, ajanld a "
            "legkozelebbi alternativat, vagy kerd el az elerhetoseget, hogy egy kollega segithessen."
        )

    # 11) # AKTUALIS OLDAL
    if ctx.page_is_product and ctx.page_product_name:
        system += (
            "\n\n# AKTUALIS OLDAL\n"
            "A latogato jelenleg ezt a termeket nezi a webshopban: " + ctx.page_product_name
            + ((" (" + ctx.page_url + ")") if ctx.page_url else "")
            + ". Ha a kerdese nem nevez meg konkret termeket, valoszinuleg errol a termekrol kerdez. "
            "Hasznald ezt a kontextust a valaszhoz, de tovabbra is csak a rendelkezesre allo "
            "adatobol valaszolj."
        )

    # 12) # ELALLAS / VISSZAKULDES
    el_url = str(tenant.elallas_url or "").strip()
    system += (
        "\n\n# ELALLAS / VISSZAKULDES\n"
        "Ha a latogato elallasrol, visszakuldesrol, termekvisszarol, penzvisszateritesrol vagy "
        "csererol kerdez: ha a TUDASBAZIS tartalmaz sajat elallasi/visszakuldesi szabalyzatot, "
        "ELSODLEGESEN abbol valaszolj. Ha nincs ilyen, ismertesd roviden az altalanos szabalyt: "
        "online vasarlasnal a fogyasztot az atveteltol szamitott 14 napos, indoklas nelkuli elallasi "
        "jog illeti meg (45/2014. Korm. rendelet); a visszakuldes kozvetlen koltseget altalaban a "
        "vasarlo viseli; a visszaterites a termek visszaerkezese vagy a visszakuldes igazolasa utan "
        "14 napon belul esedekes. Jelezd, hogy a pontos reszleteket a webshop ASZF-je tartalmazza."
    )
    if el_url:
        system += (
            "\nAz elallasi nyilatkozatot online is kitoltheti a latogato — a valaszban add meg "
            "markdown linkkent: [Elállási nyilatkozat kitöltése](" + el_url + ")."
        )
    else:
        system += (
            "\nHa a latogato konkretan el akar allni es tovabbi segitseg kell, ajanld fel a "
            "kapcsolatfelvetelt (collect_lead)."
        )

    # 13) # ELERHETO KUPONOK
    coupon_lines = _active_coupon_lines(coupons)
    if coupon_lines:
        system += (
            "\n\n# ELERHETO KUPONOK\n"
            "A kovetkezo kuponok elerhetok ennel a webshopnal. Ha a latogato kedvezmenyrol, kuponrol "
            "vagy akciorol kerdez, ajanld fel a megfelelot a feltetelekkel egyutt. SOHA ne talalj ki "
            "nem letezo kupont vagy kuponkodot.\n" + "\n".join(coupon_lines)
        )

    # 13.5) # AR-KOMMUNIKACIO (m22): akcios arnal MINDIG az akcios ar megy a vasarlonak
    system += (
        "\n\n# AR-KOMMUNIKACIO\n"
        "Ha egy termeknel AKCIOS ar szerepel, MINDIG az akcios arat kommunikald a vasarlonak, "
        "es minden esetben jelezd, hogy az ar akcios. Ha az eredeti ar is ismert, azt is ird le "
        "(pl. 'akcios aron 14 391 Ft, eredeti ar: 15 990 Ft'). SOHA ne az eredeti (nem akcios) "
        "arat add meg a termek arakent, ha van ervenyes akcios ar."
    )

    # 14) # VALASZ FORMATUM
    system += (
        "\n\n# VALASZ FORMATUM\n"
        "Mindig kizarolag egy JSON objektummal valaszolj, mas szoveg nelkul: "
        "{\"reply\": \"...\", \"collect_lead\": true vagy false, \"order_form\": true vagy false}. "
        "A reply mezoben hasznalhatsz markdown linket es **felkover** kiemelest. A collect_lead "
        "legyen true, ha nem tudsz valaszolni a rendelkezesre allo adatokbol, vagy ha a latogato "
        "beszerelest, idopontot, arajanlatot vagy kapcsolatfelvetelt ker. Ilyenkor az order_form "
        "legyen false. Ha viszont a latogato a SAJAT rendelese allapotarol, szallitasarol vagy "
        "csomagjarol erdeklodik (pl. hol tart a rendelesem, megerkezett-e a csomagom), akkor NE a "
        "collect_lead-et hasznald: ilyenkor az order_form legyen true es a collect_lead false, a "
        "reply-ban pedig roviden kerd meg, hogy a megjeleno urlapon adja meg a rendelesszamat es a "
        "rendeleskor hasznalt e-mail-cimet, es jelezd, hogy a reszleteket e-mailben kuldjuk. Konkret "
        "rendelesi adatot (allapot, cim, tetel) SOHA ne irj a chatbe."
    )

    return system

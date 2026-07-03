"""Per-platform Build Product Texts/Points — byte-paritás a reference/n8n-sync/ node-okkal.

Mindegyik builder: raw forrás -> list[SourceProduct] (text + payload-mezők + content-only hash).
A `text` az n8n node-dal BYTE-egyező (ettől összevethető a v2 vektor a cx_chatbot-tal). A
content_hash a v2 saját content-only hash-e (ár/készlet/elérhetőség NÉLKÜL — azt az élő lookup adja).
"""

from __future__ import annotations

import base64

from app.sync.hashing import ps_hash
from app.sync.models import SourceProduct
from app.sync.textutil import (
    content_fnv,
    dec_basic,
    huf,
    huf_unas,
    strip_basic,
    strip_full,
    strip_webdoc,
    trunc,
)

EMDASH = "—"  # —


def _s(v) -> str:
    return "" if v is None else str(v)


def _js_str(v) -> str:
    """JS String() coercion (Unas/webdoc param-érték lehet string VAGY lista).

    JS: String(["a","b"]) == "a,b" (vesszővel, zárójel/idézőjel nélkül); a Python str(list)
    "['a', 'b']" lenne -> drift. Bool -> 'true'/'false', egész float -> egész.
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ",".join(_js_str(e) for e in v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _js_key_order(d: dict) -> list[str]:
    """JS Object.keys / for…in sorrend: az array-index kulcsok (kanonikus egész, <2^32-1)
    NÖVEKVŐ numerikusan, majd a többi string-kulcs beillesztési sorrendben.

    A Python dict a JSON beillesztési sorrendet tartja; ez egész-kulcsú objektumnál (Sellvio
    categories) eltérne a JS-től -> más kategória-sorrend a textben -> más vektor. Ezzel egyezik.
    """
    idx, rest = [], []
    for k in d.keys():
        ks = str(k)
        if ks.isdigit() and ks == str(int(ks)) and int(ks) < 4294967295:
            idx.append(ks)
        else:
            rest.append(ks)
    idx.sort(key=int)
    return idx + rest


# =========================================================================== #
# Sellvio  (wf RMlmusDY3K58gm3N)
# =========================================================================== #
class SellvioBuilder:
    """Streamelő builder: index(page) (pass-1 reláció-index) + build(page) (pass-2 termékek).

    A logika bitre azonos a korábbi build_sellvio-val (kategória-index + rel_similar); a
    build_sellvio(rows) wrapper indexeli majd építi az egészet -> a parity-teszt védi.
    """

    def __init__(self, client_id: str, public_url: str = "") -> None:
        self.client_id = client_id
        self.by_id, self.cat_members, self.cat_size = {}, {}, {}

    def index(self, page: list[dict]) -> None:
        for p in page:
            pid = _s(p.get("id"))
            if not pid or p.get("is_visible") is False:
                continue
            self.by_id[pid] = {"name": _s(p.get("name")).strip(), "url": _s(p.get("pretty_url"))}
            cats = p.get("categories") if isinstance(p.get("categories"), dict) else {}
            for ck in _js_key_order(cats):        # JS for…in sorrend (payload-paritás)
                self.cat_size[ck] = self.cat_size.get(ck, 0) + 1
                self.cat_members.setdefault(ck, [])
                if len(self.cat_members[ck]) < 40:
                    self.cat_members[ck].append(pid)

    def _rel_similar(self, p) -> str:
        pid = _s(p.get("id"))
        cats = _js_key_order(p["categories"]) if isinstance(p.get("categories"), dict) else []
        cats.sort(key=lambda a: self.cat_size.get(a, 0))
        out, seen = [], {pid: 1}
        for ck in cats:
            for mid in self.cat_members.get(ck, []):
                if seen.get(mid):
                    continue
                t = self.by_id.get(mid)
                if not t or not t["name"]:
                    continue
                seen[mid] = 1
                out.append(t["name"] + (" " + EMDASH + " " + t["url"] if t["url"] else ""))
                if len(out) >= 5:
                    return "; ".join(out)
        return "; ".join(out)

    def build(self, page: list[dict]) -> list[SourceProduct]:
        products = []
        for p in page:
            pid = _s(p.get("id"))
            if not pid or p.get("is_visible") is False:
                continue
            name = _s(p.get("name")).strip()
            if not name:
                continue
            url = _s(p.get("pretty_url"))
            sku = _s(p.get("code"))
            price_obj = p.get("price") if isinstance(p.get("price"), dict) else {}
            price = price_obj.get("brutto_price")
            # m23: a brutto_price MAR az akcios (effektiv) ar; a discount a kedvezmeny
            # brutto OSSZEGE (0=number ha nincs, STRING ha van - elo teszt: plcomfort #3576;
            # az is_special flag NEM megbizhato akcio-jelzo). Eredeti ar = brutto + discount.
            try:
                sv_disc = float(price_obj.get("discount") or 0)
            except (TypeError, ValueError):
                sv_disc = 0.0
            ph = huf(price) if price is not None else ""
            brand = _s(p["brand"]["name"]) if isinstance(p.get("brand"), dict) and p["brand"].get("name") else ""
            cats = []
            if isinstance(p.get("categories"), dict):
                catsd = p["categories"]
                cats = [_s((catsd.get(k) or {}).get("name")) for k in _js_key_order(catsd)]  # JS Object.keys sorrend (VEKTOR!)
                cats = [c for c in cats if c]
            lead = trunc(strip_full(p.get("lead_text") or ""), 300)
            ld = trunc(strip_full(p.get("description") or ""), 800)
            line = name
            if ph:
                line += " " + EMDASH + " " + ph + " Ft"
                if sv_disc > 0:
                    try:
                        oh = huf(float(price) + sv_disc)
                    except (TypeError, ValueError):
                        oh = ""
                    line += " (AKCIÓS ár" + ((", eredeti ár: " + oh + " Ft") if oh else "") + ")"
            if brand:
                line += ". Márka: " + brand
            if cats:
                line += ". Kategória: " + ", ".join(cats)
            if lead:
                line += ". " + lead
            if ld:
                line += ". " + ld
            if url:
                line += ". Link: " + url
            line = trunc(line, 9000)
            ch = content_fnv(name, brand, ",".join(sorted(cats)), lead, ld, url)
            _pstr = "" if price is None else str(price)
            products.append(SourceProduct(
                id_key=pid, sku=sku, name=name, url=url,
                price=_pstr, brand=brand,
                related_similar=self._rel_similar(p), related_additional="",
                text=line, content_hash=ch,
                platform_id_field="sellvio_id", platform_id_value=pid,
                ps_hash_str=ps_hash(_pstr, "", str(int(sv_disc)) if sv_disc > 0 else ""),
                filename="__sellvio_products__"))
        return products


def build_sellvio(rows: list[dict], client_id: str) -> list[SourceProduct]:
    b = SellvioBuilder(client_id)
    b.index(rows)
    return b.build(rows)


# =========================================================================== #
# WooCommerce  (wf bnCd9mTgHVMNg8OZ)
# =========================================================================== #
class WooBuilder:
    def __init__(self, client_id: str, public_url: str = "") -> None:
        self.client_id = client_id
        self.by_id, self.cat_members, self.cat_size = {}, {}, {}

    def index(self, page: list[dict]) -> None:
        for p in page:
            pid = _s(p.get("id"))
            if not pid:
                continue
            self.by_id[pid] = {"name": _s(p.get("name")).strip(), "url": _s(p.get("permalink"))}
            for c in (p.get("categories") or []):
                ck = _s(c.get("id")) if isinstance(c, dict) else ""
                if not ck:
                    continue
                self.cat_size[ck] = self.cat_size.get(ck, 0) + 1
                self.cat_members.setdefault(ck, [])
                if len(self.cat_members[ck]) < 40:
                    self.cat_members[ck].append(pid)

    def _rel_list(self, ids) -> str:
        out, seen = [], {}
        for i in (ids or []):
            k = _s(i)
            if not k or seen.get(k):
                continue
            t = self.by_id.get(k)
            if not t or not t["name"]:
                continue
            seen[k] = 1
            out.append(t["name"] + (" " + EMDASH + " " + t["url"] if t["url"] else ""))
        return "; ".join(out)

    def _rel_similar_cat(self, p) -> str:
        pid = _s(p.get("id"))
        cats = [_s(c.get("id")) for c in (p.get("categories") or []) if isinstance(c, dict) and c.get("id") is not None]
        cats = [c for c in cats if c]
        cats.sort(key=lambda a: self.cat_size.get(a, 0))
        out, seen = [], {pid: 1}
        for ck in cats:
            for mid in self.cat_members.get(ck, []):
                if seen.get(mid):
                    continue
                t = self.by_id.get(mid)
                if not t or not t["name"]:
                    continue
                seen[mid] = 1
                out.append(t["name"] + (" " + EMDASH + " " + t["url"] if t["url"] else ""))
                if len(out) >= 8:
                    return "; ".join(out)
        return "; ".join(out)

    def build(self, page: list[dict]) -> list[SourceProduct]:
        products = []
        for p in page:
            wid = _s(p.get("id"))
            if not wid:
                continue
            name = _s(p.get("name")).strip()
            if not name:
                continue
            sku = _s(p.get("sku"))
            url = _s(p.get("permalink"))
            eff = p.get("sale_price") if (p.get("on_sale") and p.get("sale_price") not in (None, "")) else p.get("price")
            woo_on_sale = bool(p.get("on_sale")) and p.get("sale_price") not in (None, "")
            woo_orig = p.get("regular_price")
            ph = huf(eff)
            brands = p.get("brands")
            brand = _s(brands[0].get("name")) if isinstance(brands, list) and brands and isinstance(brands[0], dict) and brands[0].get("name") else ""
            cats = [_s(c.get("name")) for c in (p.get("categories") or []) if isinstance(c, dict)]
            cats = [c for c in cats if c]
            sd = trunc(strip_full(p.get("short_description") or ""), 600)
            ld = trunc(strip_full(p.get("description") or ""), 6000)
            attrs = []
            for a in (p.get("attributes") or []):
                if not isinstance(a, dict):
                    continue
                an = _s(a.get("name")).strip()
                ov = [_s(x) for x in (a.get("options") or [])]
                ov = [x for x in ov if x]
                if an and ov:
                    attrs.append(an + ": " + ", ".join(ov))
            stock_note = ""
            if p.get("manage_stock") is True and p.get("stock_quantity") is not None:
                stock_note = "készlet: " + _s(p.get("stock_quantity")) + " db"
            elif p.get("stock_status") == "instock":
                stock_note = "raktáron"
            elif p.get("stock_status") == "outofstock":
                stock_note = "jelenleg nincs raktáron"
            elif p.get("stock_status") == "onbackorder":
                stock_note = "elérhető (utánrendelés)"
            line = name
            if ph:
                line += " " + EMDASH + " " + ph + " Ft"
                if woo_on_sale:
                    woh = huf(woo_orig) if woo_orig not in (None, "") else ""
                    line += " (AKCIÓS ár" + ((", eredeti ár: " + woh + " Ft") if woh else "") + ")"
            if stock_note:
                line += " (" + stock_note + ")"
            if brand:
                line += ". Márka: " + brand
            if cats:
                line += ". Kategória: " + ", ".join(cats)
            if sd:
                line += ". " + sd
            if ld:
                line += ". " + ld
            if attrs:
                line += ". Paraméterek: " + "; ".join(attrs)
            if url:
                line += ". Link: " + url
            line = trunc(line, 9000)
            cross = [_s(i) for i in (p.get("upsell_ids") or [])] + [_s(i) for i in (p.get("cross_sell_ids") or [])]
            ch = content_fnv(name, brand, ",".join(sorted(cats)), sd, ld, ";".join(sorted(attrs)), url, ",".join(sorted(cross)))
            _pstr = "" if eff is None else str(eff)
            products.append(SourceProduct(
                id_key=wid, sku=sku, name=name, url=url,
                price=_pstr, brand=brand,
                related_similar=self._rel_similar_cat(p),
                related_additional=self._rel_list((p.get("upsell_ids") or []) + (p.get("cross_sell_ids") or [])),
                text=line, content_hash=ch,
                platform_id_field="wc_id", platform_id_value=wid,
                ps_hash_str=ps_hash(_pstr, "", stock_note),
                filename="__woocommerce_products__"))
        return products


def build_woo(rows: list[dict], client_id: str) -> list[SourceProduct]:
    b = WooBuilder(client_id)
    b.index(rows)
    return b.build(rows)


# =========================================================================== #
# Shoprenter  (wf GvzOXxllrtuTTPBK) — /productExtend full=1
# =========================================================================== #
def _b64dec(s: str) -> str:
    try:
        return base64.b64decode(_s(s)).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _sr_lang1_desc(descs):
    d = None
    for x in descs:
        if "language_id=1" in _b64dec(x.get("id")):
            d = x
            break
    return d or (descs[0] if descs else None)


def _sr_url(p, pub):
    ua = p.get("urlAliases") if isinstance(p.get("urlAliases"), list) else []
    if ua and ua[0].get("urlAlias"):
        return pub + _s(ua[0]["urlAlias"]).lstrip("/")
    return ""


def _sr_pid_from_href(href):
    try:
        seg = _s(href).split("?")[0].rstrip("/").split("/")[-1]
        dd = _b64dec(seg)
        import re
        m = re.search(r"product_id=(\d+)", dd)
        return m.group(1) if m else ""
    except Exception:  # noqa: BLE001
        return ""


def _sr_attr_pairs(p):
    import re
    out = []
    for a in (p.get("productAttributeExtend") or []):
        an = _s(a.get("name")).strip()
        vals = []
        av = a.get("value")
        if isinstance(av, list):
            for x in av:
                if isinstance(x, dict):
                    lid = ""
                    lh = (x.get("language") or {}).get("id") if isinstance(x.get("language"), dict) else ""
                    m = re.search(r"=(\d+)", _b64dec(lh))
                    if m:
                        lid = m.group(1)
                    if lid in ("1", ""):
                        if x.get("value") is not None:
                            vals.append(_s(x.get("value")))
                elif x is not None:
                    vals.append(_s(x))
        elif av is not None:
            vals.append(_s(av))
        seen, dedup = set(), []
        for v in vals:
            if v and v not in seen:
                seen.add(v)
                dedup.append(v)
        if an and dedup:
            out.append(an + ": " + ", ".join(dedup))
    return out


def _sr_clean_params(raw):
    import re
    s = dec_basic(_s(raw))
    out = []
    for ln0 in re.split(r"\r?\n", s):
        ln = re.sub(r"\s*:\s*", ": ", re.sub(r"\s+", " ", ln0.replace("\t", " ")), count=1).strip()
        if ln:
            out.append(ln)
    return out


class ShoprenterBuilder:
    def __init__(self, client_id: str, public_url: str = "", include_inactive: bool = False) -> None:
        self.client_id = client_id
        pub = _s(public_url)
        if pub and not pub.endswith("/"):
            pub += "/"
        self.pub = pub
        self.by_id = {}
        self.include_inactive = include_inactive

    def index(self, page: list[dict]) -> None:
        for p in page:
            pid = _s(p.get("innerId"))
            if not pid:
                continue
            descs = p.get("productDescriptions") if isinstance(p.get("productDescriptions"), list) else []
            d = _sr_lang1_desc(descs)
            nm = _s(d.get("name")).strip() if d else ""
            if not nm:
                continue
            self.by_id[pid] = {"name": nm, "url": _sr_url(p, self.pub)}

    def _build_rel(self, p, field, ref_key) -> str:
        out, seen = [], {}
        for rel in (p.get(field) or []):
            ref = rel.get(ref_key) if isinstance(rel, dict) else None
            href = ref.get("href") if isinstance(ref, dict) else ""
            pid = _sr_pid_from_href(href)
            if not pid:
                continue
            t = self.by_id.get(pid)
            if not t or not t["name"] or seen.get(pid):
                continue
            seen[pid] = 1
            out.append(t["name"] + (" " + EMDASH + " " + t["url"] if t["url"] else ""))
        return "; ".join(out)

    def build(self, page: list[dict]) -> list[SourceProduct]:
        import re as _re
        products = []
        for p in page:
            descs = p.get("productDescriptions") if isinstance(p.get("productDescriptions"), list) else []
            d = _sr_lang1_desc(descs)
            name = _s(d.get("name")).strip() if d else ""
            if not name:
                continue
            active = _s(p.get("status")) == "1"
            if not active and not self.include_inactive:
                continue
            prices = p.get("productPrices") if isinstance(p.get("productPrices"), list) else []
            gross = grossSpecial = None
            if prices:
                gross = prices[0].get("gross")
                grossSpecial = prices[0].get("grossSpecial")
                if grossSpecial in (None, ""):
                    # az akciós ár gyakran NEM a [0] price-sorban jön: az azonos grossOriginal-ú
                    # további sorok első kitöltött grossSpecial-ja az érvényes akciós ár (m22)
                    base_orig = _s(prices[0].get("grossOriginal") or gross)
                    for row in prices[1:]:
                        if not isinstance(row, dict):
                            continue
                        gs = row.get("grossSpecial")
                        if gs not in (None, "") and _s(row.get("grossOriginal")) == base_orig:
                            grossSpecial = gs
                            break
            price = grossSpecial if grossSpecial not in (None, "") else gross
            on_sale = grossSpecial not in (None, "") and _s(grossSpecial) != _s(gross)
            price_orig = (prices[0].get("grossOriginal") or gross) if prices else None
            stock = _re.sub(r"\.0+$", "", _s(p.get("stock1"))) if p.get("stock1") is not None else ""
            orderable = _s(p.get("orderable")) == "1"
            url = _sr_url(p, self.pub)
            sku = _s(p.get("sku") or p.get("modelNumber"))
            manu = _s(p["manufacturer"]["name"]) if isinstance(p.get("manufacturer"), dict) and p["manufacturer"].get("name") else ""
            sd = trunc(strip_basic(d.get("shortDescription")) if d else "", 600)
            ld = trunc(strip_basic(d.get("description")) if d else "", 8000)
            params = _sr_attr_pairs(p) + _sr_clean_params(d.get("parameters") if d else "")
            param_str = trunc("; ".join(params), 8000)
            avail = "inaktív" if not active else ("rendelhető" if orderable else "jelenleg nem rendelhető")
            line = name
            ph = huf(price)
            if ph:
                line += " " + EMDASH + " " + ph + " Ft"
                if on_sale:
                    oh = huf(price_orig)
                    line += " (AKCIÓS ár" + ((", eredeti ár: " + oh + " Ft") if oh else "") + ")"
            line += " (" + avail + (", készlet: " + stock + " db" if stock != "" else "") + ")"
            if manu:
                line += ". Márka: " + manu
            if sd:
                line += ". " + sd
            if ld:
                line += ". " + ld
            if param_str:
                line += ". Paraméterek: " + param_str
            if url:
                line += ". Link: " + url
            rel_similar = self._build_rel(p, "productRelatedProductRelations", "relatedProduct")
            rel_additional = self._build_rel(p, "productCollateralProductRelations", "collateralProduct")
            # content-only (ár/készlet/elérhetőség NÉLKÜL): name|manu|url|sku|sd|ld|params|relSim|relAdd
            ch = content_fnv(
                name, manu, url, sku, sd, ld,
                ";".join(sorted(params)),
                ",".join(sorted([x for x in rel_similar.split("; ") if x])),
                ",".join(sorted([x for x in rel_additional.split("; ") if x])),
            )
            id_key = sku or url or name
            _pstr = "" if price is None else str(price)
            products.append(SourceProduct(
                id_key=id_key, sku=sku, name=name, url=url,
                price=_pstr, brand=manu, stock_str=stock,
                related_similar=rel_similar, related_additional=rel_additional,
                text=line, content_hash=ch,
                ps_hash_str=ps_hash(_pstr, stock, avail),
                filename="__shoprenter_products__"))
        return products


def build_shoprenter(items: list[dict], client_id: str, public_url: str, include_inactive: bool = False) -> list[SourceProduct]:
    b = ShoprenterBuilder(client_id, public_url, include_inactive=include_inactive)
    b.index(items)
    return b.build(items)


# =========================================================================== #
# Unas  (wf 48aImzQW4QEncluH) — getProductDB CSV-export (;-elválasztott, BOM-strip)
# =========================================================================== #
def _parse_csv(s: str, delim: str) -> list[list[str]]:
    rows, row, field, i, in_q = [], [], "", 0, False
    n = len(s)
    while i < n:
        c = s[i]
        if in_q:
            if c == '"':
                if i + 1 < n and s[i + 1] == '"':
                    field += '"'
                    i += 2
                    continue
                in_q = False
                i += 1
                continue
            field += c
            i += 1
            continue
        if c == '"':
            in_q = True
            i += 1
            continue
        if c == delim:
            row.append(field)
            field = ""
            i += 1
            continue
        if c == "\r":
            i += 1
            continue
        if c == "\n":
            row.append(field)
            rows.append(row)
            row, field = [], ""
            i += 1
            continue
        field += c
        i += 1
    if field != "" or row:
        row.append(field)
        rows.append(row)
    return rows


def unas_rowdicts(csv_text: str) -> list[dict]:
    """CSV -> könnyű meta-sorok (name/sku/url/cat/sd/ld/brand/stock/price/rel_*/line).

    A CSV egy letöltés (bounded); a meták könnyűek (Unas text kicsi). A stream-adapter chunkokban
    adja tovább; a relációkat az UnasBuilder oldja fel. A mezők bitre azonosak a korábbi build-del.
    """
    import re
    raw = _s(csv_text)
    if not raw:
        return []
    raw = re.sub(r"^﻿", "", raw)
    rows = _parse_csv(raw, ";")
    if len(rows) < 2:
        return []
    header = [re.sub(r"^﻿", "", _s(h)).strip() for h in rows[0]]

    def ix(name):
        return header.index(name) if name in header else -1

    i_sku, i_name, i_gross, i_cat = ix("Cikkszám"), ix("Termék Név"), ix("Bruttó Ár"), ix("Kategória")
    i_short, i_long, i_url, i_stock = ix("Rövid Leírás"), ix("Tulajdonságok"), ix("Termék link"), ix("Raktárkészlet")
    i_attach, i_simp = ix("Kiegészítő Termékek"), ix("Hasonló Termékek")
    i_brand = ix("Gyártó")
    for alt in ("Márka", "Gyártó név", "Manufacturer", "Brand"):
        if i_brand < 0:
            i_brand = ix(alt)
    i_brand_param = -1
    for h, hh in enumerate(header):
        if hh.startswith("Paraméter:"):
            pn = re.sub(r"^Paraméter:\s*", "", hh).split("|")[0].strip()
            if pn == "Gyártó":
                i_brand_param = h
                break

    def col(cols, i):
        return _s(cols[i]) if 0 <= i < len(cols) else ""

    out = []
    for r in range(1, len(rows)):
        cols = rows[r]
        if not cols or len(cols) < 2:
            continue
        name = col(cols, i_name).strip()
        if not name:
            continue
        gross = cols[i_gross] if 0 <= i_gross < len(cols) else ""
        cat = col(cols, i_cat).strip()
        sd = trunc(strip_basic(col(cols, i_short)), 300)
        ld = trunc(strip_basic(col(cols, i_long)), 400)
        stock = re.sub(r"\.0+$", "", col(cols, i_stock).strip())
        brand = col(cols, i_brand).strip()
        brand_param = col(cols, i_brand_param).strip()
        line = name
        ph = huf_unas(gross)
        if ph:
            line += " " + EMDASH + " " + ph + " Ft"
        if cat:
            line += " (" + cat + ")"
        if stock != "":
            line += ". Készlet: " + stock + " db"
        if sd:
            line += ". " + sd
        if ld:
            line += ". " + ld
        if brand:
            line += ". Márka: " + brand
        out.append({
            "name": name, "sku": col(cols, i_sku).strip(), "url": col(cols, i_url).strip(),
            "cat": cat, "sd": sd, "ld": ld, "brand": (brand or brand_param), "stock": stock,
            "price": ("" if gross is None else str(gross)),
            "rel_add": [x.strip() for x in col(cols, i_attach).split("|") if x.strip()],
            "rel_sim": [x.strip() for x in col(cols, i_simp).split("|") if x.strip()],
            "line": line,
        })
    return out


class UnasBuilder:
    def __init__(self, client_id: str, public_url: str = "") -> None:
        self.client_id = client_id
        self.name_by_sku, self.url_by_sku = {}, {}

    def index(self, page: list[dict]) -> None:
        for m in page:
            if m["sku"]:
                self.name_by_sku[m["sku"]] = m["name"]
                self.url_by_sku[m["sku"]] = m["url"]

    def _fmt_rel(self, skus, cap) -> str:
        out = []
        for s in skus:
            if s in self.name_by_sku:
                u = self.url_by_sku.get(s, "")
                out.append((self.name_by_sku[s] + " " + EMDASH + " " + u) if u else self.name_by_sku[s])
            if len(out) >= cap:
                break
        return "; ".join(out)

    def build(self, page: list[dict]) -> list[SourceProduct]:
        products = []
        for m in page:
            rel_similar = self._fmt_rel(m["rel_sim"], 12)
            rel_additional = self._fmt_rel(m["rel_add"], 12)
            ch = content_fnv(
                m["name"], m["cat"], m["sd"], m["ld"], m["brand"], m["url"],
                ",".join(sorted(m["rel_add"])), ",".join(sorted(m["rel_sim"])),
            )
            products.append(SourceProduct(
                id_key=(m["sku"] or m["url"] or m["name"]), sku=m["sku"], name=m["name"], url=m["url"],
                price=m["price"], brand=m["brand"], stock_str=m["stock"],
                related_similar=rel_similar, related_additional=rel_additional,
                text=m["line"], content_hash=ch,
                ps_hash_str=ps_hash(m["price"], m["stock"], ""),
                filename="__unas_products__"))
        return products


def build_unas(csv_text: str, client_id: str, public_url: str) -> list[SourceProduct]:
    rows = unas_rowdicts(csv_text)
    b = UnasBuilder(client_id)
    b.index(rows)
    return b.build(rows)


# =========================================================================== #
# Webdoc  (wf BRyFj4UvunsJY9ZA) — feed-pillanatkép (data.products)
# =========================================================================== #
# FLAG: a webdoc reference node (sync_webdoc_code.js) NEM állt rendelkezésre; az alábbi
# text/payload/hash a megadott spec szerint pontos, de a FEED MEZŐNEVEI (name/price/available/
# brand/category_path|category/description/params|parameters/url|link/sku/id) FELTÉTELEZÉSEK —
# egy valós notebookstore termékkel (vagy a node-dal) megerősítendők. A dec/strip a full variáns.
def _webdoc_sort_key(p):
    v = _s(p.get("id"))
    return (0, int(v)) if v.isdigit() else (1, v)


def _webdoc_cats(p) -> list[str]:
    """catArr: category_path '>'-split (vagy category fallback)."""
    cp = _s(p.get("category_path")).strip()
    if cp:
        return [c.strip() for c in cp.split(">") if c.strip()]
    cat = _s(p.get("category")).strip()
    return [cat] if cat else []


class WebdocBuilder:
    """Nincs reláció -> index() no-op. A build() a KAPOTT sorrendben épít (a rendezés a hívóé)."""

    def __init__(self, client_id: str, public_url: str = "") -> None:
        self.client_id = client_id

    def index(self, page: list[dict]) -> None:
        return

    def build(self, page: list[dict]) -> list[SourceProduct]:
        out = []
        for p in page:
            wid = _s(p.get("id"))
            if not wid:
                continue
            name = _s(p.get("name")).strip()
            if not name:
                continue
            price = p.get("price_gross")        # a feedben price_gross (NINCS price kulcs)
            ph = huf(price)
            available = p.get("available") is True   # strict === true
            avail_txt = "raktáron" if available else "jelenleg nincs raktáron"
            brand = _s(p.get("brand"))
            cats = _webdoc_cats(p)
            ld = trunc(strip_webdoc(p.get("description") or ""), 6000)
            params = []
            for pr in (p.get("parameters") or p.get("params") or []):
                if not isinstance(pr, dict):
                    continue
                pn = _js_str(pr.get("name")).strip()
                pv = _js_str(pr.get("value")).strip()   # value lehet string VAGY lista
                if pn and pv:
                    params.append(f"{pn}: {pv}")
            url = _s(p.get("url") or p.get("link"))
            sku = _s(p.get("sku"))
            line = name
            if ph:
                line += " " + EMDASH + " " + ph + " Ft"
            line += " (" + avail_txt + ")"
            if brand:
                line += ". Márka: " + brand
            if cats:
                line += ". Kategória: " + " > ".join(cats)
            if ld:
                line += ". " + ld
            if params:
                line += ". Paraméterek: " + "; ".join(params)
            if url:
                line += ". Link: " + url
            line = trunc(line, 9000)
            price_str = "" if price is None else str(price)
            # content-only hash (ár/készlet NÉLKÜL): name|brand|cats('>')|ld|params.sorted(';')|url
            ch = content_fnv(name, brand, ">".join(cats), ld, ";".join(sorted(params)), url)
            out.append(SourceProduct(
                id_key=wid, sku=sku, name=name, url=url, price=price_str, brand=brand,
                available=available, ps_hash_str=ps_hash(price_str, "", available),
                text=line, content_hash=ch,
                platform_id_field="webdoc_id", platform_id_value=wid,
                filename="__webdoc_products__"))
        return out


def webdoc_sorted(products: list[dict]) -> list[dict]:
    return sorted(products, key=_webdoc_sort_key)   # id szerint rendezve


def build_webdoc(products: list[dict], client_id: str) -> list[SourceProduct]:
    return WebdocBuilder(client_id).build(webdoc_sorted(products))

"""Szöveg-segédek a sync build_text byte-paritásához (az n8n Code node-okkal egyezve).

- dec/strip: HTML entity-dekód + tag-strip + whitespace-collapse (két variáns: full = Sellvio/Woo,
  basic = Shoprenter/Unas — a node-ok dec-je kicsit eltér).
- huf: Math.round(parseFloat(v)).toLocaleString('hu-HU') reprodukció — NBSP (U+00A0) ezres-elválasztó,
  minimumGroupingDigits=2 (a 4-jegyű számok NEM csoportosítva). huf_unas: előbb szóköz-strip + ',' -> '.'.
- content_fnv: a v2 SAJÁT content-hash-e (FNV-1a, csak tartalom — ár/készlet nélkül).
"""

import math
import re

from app.sync.hashing import fnv1a_32


# --- entity dekód + strip -------------------------------------------------- #
def dec_full(s: str) -> str:
    """Sellvio/Woo dec: &lt; &gt; &quot; &#0?39; &#8217; &nbsp; &amp;."""
    s = str(s or "")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    s = re.sub(r"&#0?39;", "'", s)
    s = s.replace("&#8217;", "'")
    s = re.sub(r"&nbsp;", " ", s, flags=re.IGNORECASE)
    return s.replace("&amp;", "&")


def dec_basic(s: str) -> str:
    """Shoprenter/Unas dec: &lt; &gt; &quot; &#39; &amp;."""
    s = str(s or "")
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&#39;", "'").replace("&amp;", "&"))


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def strip_full(s: str) -> str:
    return _collapse(dec_full(s))


def strip_basic(s: str) -> str:
    return _collapse(dec_basic(s))


def trunc(s: str, n: int) -> str:
    """JS: if(s.length>n) s=s.slice(0,n)+'...'."""
    return (s[:n] + "...") if len(s) > n else s


# --- Webdoc entity-dekód (a webdoc node kanonikus dec/strip-je) ------------- #
# Numerikus (&#x..; / &#..;) + bővebb named tábla; a táblán KÍVÜLI named entity KÓDOLVA marad.
# FIGYELEM: NEM keverendő a Sellvio/Woo/SR/Unas dec-jével (azok node-verifikált egyszerűbb dec-et
# használnak — pl. Sellvio &#8217; -> ASCII ', nem ’).
_WD_ENT = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ",
    "aacute": "á", "Aacute": "Á", "eacute": "é", "Eacute": "É", "iacute": "í", "Iacute": "Í",
    "oacute": "ó", "Oacute": "Ó", "ouml": "ö", "Ouml": "Ö", "odblac": "ő", "Odblac": "Ő",
    "uacute": "ú", "Uacute": "Ú", "uuml": "ü", "Uuml": "Ü", "udblac": "ű", "Udblac": "Ű",
    "szlig": "ß", "ndash": "–", "mdash": "—", "hellip": "…",
    "rsquo": "'", "lsquo": "'", "rdquo": '"', "ldquo": '"',
    "euro": "€", "copy": "©", "reg": "®", "trade": "™", "deg": "°",
}


def _wd_num(m, base):
    try:
        return chr(int(m.group(1), base))
    except (ValueError, OverflowError):
        return m.group(0)


def dec_webdoc(s: str) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: _wd_num(m, 16), s)
    s = re.sub(r"&#(\d+);", lambda m: _wd_num(m, 10), s)
    s = re.sub(r"&([a-zA-Z]+);", lambda m: _WD_ENT.get(m.group(1), m.group(0)), s)
    return s


def strip_webdoc(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dec_webdoc(s))).strip()


# --- ár formázás (hu-HU) --------------------------------------------------- #
def _parse_float(v) -> float | None:
    m = re.match(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", str(v).strip())
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _group_huf(n: int) -> str:
    """NBSP ezres-elválasztó; minimumGroupingDigits=2 -> <5 jegy NINCS csoportosítva."""
    neg = n < 0
    s = str(abs(n))
    if len(s) >= 5:
        parts = []
        while len(s) > 3:
            parts.insert(0, s[-3:])
            s = s[:-3]
        parts.insert(0, s)
        body = " ".join(parts)
    else:
        body = s
    return ("-" + body) if neg else body


def huf(v) -> str:
    """Sellvio/Woo/SR: Math.round(parseFloat(v)).toLocaleString('hu-HU')."""
    n = _parse_float(v)
    if n is None or not math.isfinite(n):
        return ""
    return _group_huf(math.floor(n + 0.5))


def huf_unas(v) -> str:
    """Unas: parseFloat(String(v).replace(/\\s/g,'').replace(',','.')) majd huf."""
    s = re.sub(r"\s", "", str(v)).replace(",", ".")
    n = _parse_float(s)
    if n is None or not math.isfinite(n):
        return ""
    return _group_huf(math.floor(n + 0.5))


def content_fnv(*parts: str) -> str:
    """v2 content-hash: FNV-1a a tartalom-mezőkről (ár/készlet NÉLKÜL)."""
    return fnv1a_32("|".join(p if p is not None else "" for p in parts))

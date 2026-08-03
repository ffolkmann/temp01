"""m79b: fasetta/szuro SEO-link a zaro linkhez (pilot: notebookstore/webdoc).

A crawl-elt tenant-szintu kategoria/szuro-terkepbol (JSON,
/app/data/facet_map_<client_id>.json, tools/facet_crawl.py irja) es a
kerdes-oldali megkotesekbol (paramextract.detect_constraints) LETEZO,
talalatot ado szuro-URL-t epit, max 1 szurovel (prioritas:
meret > tipus > szin). Ha nincs passzolo: None -> a hivo az m79a
kereso-linket hasznalja (fail-safe). Csak stdlib — tesztbol
fajl-betoltheto.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

__all__ = ["facet_link", "load_map", "top_category"]

_MAP_DIR = os.environ.get("FACET_MAP_DIR", "/app/data")
_cache: dict = {}  # path -> (mtime, data)

_MERET_FACET = "maximalis-notebook-meret"
_TIPUS_FACET = "taska-tipusa"
_SZIN_FACET = "szin"
# paramextract p_tipus -> webshop szuro-ertek
_TIPUS_VAL = {"hatizsak": "hatizsak", "valltaska": "valltaskakezitaska", "tok": "toksleeve"}


def _fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c))


def _norm_key(s):
    """Kategorianev/slug -> kotojel- es irasjel-mentes osszehasonlito kulcs.

    Igy a feed-beli nev ('Notebook taska, hatizsak') es az URL-slug
    ('notebook-taska-hatizsak') akkor is egyezik, ha a webshop slugify-a
    mashogy kezeli az irasjeleket (pl. 'SSD/HDD' -> 'ssdhdd').
    """
    return re.sub(r"[^a-z0-9]", "", _fold(s))


def _build_idx(data):
    idx = {}
    for slug, ent in (data.get("categories") or {}).items():
        idx[_norm_key(slug)] = ent
    return idx


def load_map(client_id, map_dir=None):
    """A tenant facet-terkepenek betoltese (mtime-cache). Nincs fajl -> None."""
    path = os.path.join(map_dir or _MAP_DIR, "facet_map_%s.json" % client_id)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001 — serult fajl: fail-safe None
        return None
    data["_idx"] = _build_idx(data)
    _cache[path] = (mt, data)
    return data


def top_category(categories):
    """A kontextus-talalatok leggyakoribb category-erteke (ures kiszurve)."""
    cnt: dict = {}
    for c in categories or []:
        c = str(c or "").strip()
        if c:
            cnt[c] = cnt.get(c, 0) + 1
    if not cnt:
        return ""
    return max(cnt.items(), key=lambda kv: kv[1])[0]


def _leaf(category_name):
    parts = [p.strip() for p in str(category_name or "").split(">")]
    return parts[-1] if parts else ""


def _pick_meret(values, gte):
    """Diszkret szuro-ertekek (pl. '173' = 17.3\") kozul valasztas.

    Exact (gte*10) ha letezik darabszammal, kulonben a legkisebb >= gte
    (a '17-es laptophoz' kerdesre a 17.0-s szuro a legjobb letezo oldal).
    """
    try:
        want = int(round(float(gte) * 10))
    except (TypeError, ValueError):
        return None
    have = []
    for v, n in (values or {}).items():
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if int(n or 0) > 0:
            have.append(iv)
    if not have:
        return None
    if want in have:
        return str(want)
    bigger = sorted(x for x in have if x >= want)
    return str(bigger[0]) if bigger else None


def facet_link(base_url, categories, constraints, fmap):
    """SEO-szuro-URL vagy None. Csak letezo, darabszamos szuro-oldalra linkelunk."""
    if not (base_url and constraints and fmap):
        return None
    cat = top_category(categories)
    if not cat:
        return None
    idx = fmap.get("_idx") or _build_idx(fmap)
    ent = idx.get(_norm_key(_leaf(cat)))
    if not ent or not ent.get("url"):
        return None
    facets = ent.get("facets") or {}
    base = str(base_url).rstrip("/")

    def _url(attr, val):
        return base + str(ent["url"]) + "/" + attr + ":" + val

    g = constraints.get("p_max_meret_gte")
    if isinstance(g, (int, float)):
        v = _pick_meret(facets.get(_MERET_FACET), g)
        if v:
            return _url(_MERET_FACET, v)
    t = _TIPUS_VAL.get(str(constraints.get("p_tipus") or ""))
    if t and int((facets.get(_TIPUS_FACET) or {}).get(t) or 0) > 0:
        return _url(_TIPUS_FACET, t)
    sz = _fold(constraints.get("p_szin") or "").replace(" ", "")
    if sz and int((facets.get(_SZIN_FACET) or {}).get(sz) or 0) > 0:
        return _url(_SZIN_FACET, sz)
    return None

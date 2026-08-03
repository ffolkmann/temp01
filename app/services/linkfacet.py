"""m79b: fasetta/szuro SEO-link a zaro linkhez (pilot: notebookstore/webdoc).

A crawl-elt tenant-szintu kategoria/szuro-terkepbol (JSON,
/app/data/facet_map_<client_id>.json, tools/facet_crawl.py irja) es a
kerdes-oldali megkotesekbol (paramextract.detect_constraints) LETEZO,
talalatot ado szuro-URL-t epit, max 1 szurovel. Prioritas-sor
(_PRIORITY): taska-colmeret > kijelzo-meret > taska-tipus >
felhasznalas-jelleg > szin -- az adott kategoriaban nem letezo attr
automatikusan a kovetkezore esik at. Ha nincs passzolo: None -> a hivo
az m79a kereso-linket hasznalja (fail-safe). Csak stdlib — tesztbol
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

# paramextract p_tipus -> webshop szuro-ertek
_TIPUS_VAL = {"hatizsak": "hatizsak", "valltaska": "valltaskakezitaska", "tok": "toksleeve"}

# (constraint-kulcs, facet-attr, mod) -- az elso linkelheto nyer
_PRIORITY = (
    ("p_max_meret_gte", "maximalis-notebook-meret", "meret"),
    ("kijelzo_meret_gte", "kijelzo-meret", "meret"),  # m79b-nb
    ("p_tipus", "taska-tipusa", "tipus"),
    ("usage", "felhasznalas-jellege", "direct"),  # m79b-nb
    ("p_szin", "szin", "szin"),
)


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
    (a '17-es laptophoz' kerdesre a 17.0-s vagy a legkozelebbi nagyobb
    letezo szuro-oldal a legjobb).
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

    for key, attr, mode in _PRIORITY:
        raw = constraints.get(key)
        if raw in (None, ""):
            continue
        vals = facets.get(attr) or {}
        v = None
        if mode == "meret":
            if isinstance(raw, (int, float)):
                v = _pick_meret(vals, raw)
        elif mode == "tipus":
            v = _TIPUS_VAL.get(str(raw))
            if v and int(vals.get(v) or 0) <= 0:
                v = None
        elif mode == "direct":
            v = str(raw)
            if int(vals.get(v) or 0) <= 0:
                v = None
        else:  # szin
            v = _fold(raw).replace(" ", "")
            if not v or int(vals.get(v) or 0) <= 0:
                v = None
        if v:
            return base + str(ent["url"]) + "/" + attr + ":" + v
    return None

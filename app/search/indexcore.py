"""CX SmartSearch — platform-fuggetlen index-mag (S1, productizacio).

A /root/cx_smartsearch_indexer.py (N1 + A1) bizonyitott magjanak portja: a
bemenet mar NEM feed-specifikus, hanem a mapperek altal adott "feed-alaku"
termek-dict lista. Egy rekord alakja:

    {
      "id": <int|str>,            # stabil termek-azonosito
      "sku": str, "name": str, "brand": str, "category": str,
      "price_gross": <szam|None>,
      "orig_price": <szam|None>,  # akcio elotti (athuzott) ar, ha van es nagyobb
      "available": bool,
      "url": str, "image_url": str,          # ABSZOLUT url-ek (prefix itt vagodik)
      "parameters": [ {"name": str, "value": str|int|list}, ... ],
      "created_day": int|None,    # unix-nap; ha None, first_seen registry adja a "d"-t
    }

Kimenet (tenantonkenti out_dir): index.json {"products":[{i,k,n,b,c,p,a,u,m[,o],d}]},
params.json (szotar-kodolt facet-adat), manifest.json, es CSAK akkor
first_seen.json, ha van created_day nelkuli rekord (pl. webdoc feed).

kfsc/1 (2026-08-28): build_index(..., scope=[...]) - build-ideju alapszuro. Ezzel
ugyanabbol a lekert adatbol KET kimenet keszulhet: teljes index a keresonek es
szuk, scope-olt index a konfiguratornak (lasd app/search/__main__.py `konf` blokk).
Indok: a widget a TELJES indexet tolti le kliens-oldalon, ezert a konfiguratornak
nem szabad az egesz katalogust adni. ADR: claude/adr-001-egy-kodbazis-ket-kimeneti-profil.md

Vedelem a pilotbol orokolve: atomikus iras, min_ratio zsugorodas-guard,
hibanal a regi index marad es a manifest error-t kap.
"""
import hashlib
import json
import os
import time

PARAM_NAME_MAX = 60
PARAM_VAL_MAX = 150


def strip_prefix(value, prefix):
    return value[len(prefix):] if isinstance(value, str) and prefix and value.startswith(prefix) else value


def compact(p, url_prefix, img_prefix):
    row = {
        "i": str(p.get("id", "")),
        "k": (p.get("sku") or "").strip(),
        "n": (p.get("name") or "").strip(),
        "b": (p.get("brand") or "").strip(),
        "c": (p.get("category") or "").strip(),
        "p": p.get("price_gross"),
        "a": 1 if p.get("available") else 0,
        "u": strip_prefix(p.get("url") or "", url_prefix),
        "m": strip_prefix(p.get("image_url") or "", img_prefix),
    }
    o = p.get("orig_price")
    pr = p.get("price_gross")
    if isinstance(o, (int, float)) and isinstance(pr, (int, float)) and o > pr:
        row["o"] = o
    return row


def param_pairs(p):
    """A rekord 'parameters' mezojebol (nev, ertek) parok — normalizalva (N1-parity)."""
    out = []
    params = p.get("parameters")
    if not isinstance(params, list):
        return out
    for it in params:
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name or len(name) > PARAM_NAME_MAX:
            continue
        val = it.get("value")
        vals = val if isinstance(val, list) else [val]
        for v in vals:
            if isinstance(v, int) and not isinstance(v, bool):
                v = str(v)
            if not isinstance(v, str):
                continue
            v = v.strip()
            if not v or len(v) > PARAM_VAL_MAX:
                continue
            out.append((name, v))
    return out


def build_params(products):
    """Szotar-kodolt facet-adat: names/vals globalis listak, per termek flat [ni,vi,...] (A1-parity)."""
    names, nidx, vals, vidx, pmap = [], {}, [], {}, {}
    for p in products:
        pairs = param_pairs(p)
        if not pairs:
            continue
        flat, seen = [], set()
        for name, v in pairs:
            if name not in nidx:
                nidx[name] = len(names)
                names.append(name)
            if v not in vidx:
                vidx[v] = len(vals)
                vals.append(v)
            key = (nidx[name], vidx[v])
            if key in seen:
                continue
            seen.add(key)
            flat.append(key[0])
            flat.append(key[1])
        if flat:
            pmap[str(p.get("id", ""))] = flat
    return {"names": names, "vals": vals, "p": pmap}


def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def apply_days(rows, cdays, out_dir):
    """A 'd' mezo (unix-nap) beallitasa.

    - Ha MINDEN rekordnak van created_day-e (pl. Sellvio): azt hasznaljuk,
      first_seen.json NEM keszul (a forras az igazsag).
    - Kulonben (pl. webdoc feed): a created_day nelkuli rekordokra a first_seen
      registry megy az eredeti szaballyal (elso futasnal 0 = regi, nincs hamis Uj).
    Visszaadja az uj registry-id-k szamat.
    """
    if all(cd is not None for cd in cdays):
        for r, cd in zip(rows, cdays):
            r["d"] = int(cd)
        return 0
    fs_path = os.path.join(out_dir, "first_seen.json")
    today = int(time.time() // 86400)
    fs = None
    try:
        with open(fs_path, encoding="utf-8") as f:
            fs = json.load(f)
        if not isinstance(fs, dict):
            fs = None
    except Exception:
        fs = None
    if fs is None:
        # elso futas: minden created_day NELKULI termek "regi" (0) -> nincs hamis Uj
        fs = {r["i"]: 0 for r, cd in zip(rows, cdays) if cd is None}
    new_ids = 0
    for r, cd in zip(rows, cdays):
        if cd is not None:
            r["d"] = int(cd)
            continue
        if r["i"] not in fs:
            fs[r["i"]] = today
            new_ids += 1
        r["d"] = fs[r["i"]]
    atomic_write(fs_path, json.dumps(fs, separators=(",", ":")))
    return new_ids


def _param_map(p):
    """A feed-alaku rekord parametereibol {nev: [ertekek]} - a scope kiertekelesehez."""
    out = {}
    for name, v in param_pairs(p):
        out.setdefault(name, []).append(v)
    return out


def _scope_num(x):
    try:
        return float(str(x).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _scope_one(row, pmap, cond):
    """EGY scope-feltetel. Ugyanaz a szemantika, mint a widget ruleset-szurojeben:
    `param` = termekparameter (params.json), `field` = kompakt index-mezo (p/b/c/a),
    op = eq | neq | has_any | gte | lte | exists."""
    if not isinstance(cond, dict):
        return True
    op = str(cond.get("op") or "").strip()
    if cond.get("param"):
        v = pmap.get(str(cond["param"]))
    else:
        f = str(cond.get("field") or "").strip()
        v = row.get(f) if f else None
    tgt = cond.get("value", cond.get("v"))
    if op == "exists":
        return v not in (None, "", [], 0)
    if v is None:
        return False
    lst = v if isinstance(v, list) else [v]
    if op == "eq":
        return any(str(x) == str(tgt) for x in lst)
    if op == "neq":
        return all(str(x) != str(tgt) for x in lst)
    if op == "has_any":
        t = tgt if isinstance(tgt, list) else [tgt]
        return any(str(x).strip().lower() == str(y).strip().lower() for x in lst for y in t)
    ns = [n for n in (_scope_num(x) for x in lst) if n is not None]
    tn = _scope_num(tgt)
    if not ns or tn is None:
        return False
    if op == "gte":
        return any(n >= tn for n in ns)
    if op == "lte":
        return any(n <= tn for n in ns)
    return False


def scope_match(row, pmap, scope):
    """Beleesik-e a termek a scope-ba. A feltetelek ES-kapcsolatban; egy elem lehet
    lista is (azon belul is ES). Ures/hianyzo scope -> minden termek benne van."""
    for cond in scope or ():
        conds = cond if isinstance(cond, list) else [cond]
        if not all(_scope_one(row, pmap, c) for c in conds):
            return False
    return True


def _prev_count(manifest_path):
    if not os.path.exists(manifest_path):
        return 0
    try:
        return json.load(open(manifest_path)).get("count", 0)
    except Exception:
        return 0


def write_error_manifest(out_dir, tenant, err):
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.json")
    atomic_write(manifest_path, json.dumps(
        {"tenant": tenant, "error": str(err), "count": _prev_count(manifest_path),
         "failed_at": int(time.time())}, ensure_ascii=False))


def build_index(tenant, products, out_dir, url_prefix, img_prefix,
                only_available=True, min_ratio=0.5, scope=None, labels=None):
    """Feed-alaku termeklistabol a harom kiszolgalt fajl. Eredmeny-dict a CLI-nek.

    kfsc/1: a `scope` build-ideju alapszuro (a ruleset-scope parja) - ezzel egy
    tenantnak KET kimenete lehet ugyanabbol a lekert adatbol: teljes index a
    keresonek, szuk index a konfiguratornak. Ures scope -> minden termek bekerul,
    tehat a meglevo tenantok viselkedese valtozatlan."""
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.json")
    index_path = os.path.join(out_dir, "index.json")
    params_path = os.path.join(out_dir, "params.json")

    prev_count = _prev_count(manifest_path)

    if only_available:
        products = [p for p in products if p.get("available")]
    rows = [compact(p, url_prefix, img_prefix) for p in products]

    if scope:
        # a products es a rows sorrendje osszetartozik (apply_days zip-eli oket),
        # ezert EGYUTT szurunk
        pairs = [(p, r) for p, r in zip(products, rows)
                 if scope_match(r, _param_map(p), scope)]
        products = [p for p, _ in pairs]
        rows = [r for _, r in pairs]

    if prev_count and len(rows) < prev_count * min_ratio:
        err = f"gyanus zsugorodas {prev_count}->{len(rows)}, index nem frissult"
        atomic_write(manifest_path, json.dumps(
            {"tenant": tenant, "error": err, "count": prev_count,
             "failed_at": int(time.time())}, ensure_ascii=False))
        return {"tenant": tenant, "error": err, "count": prev_count}

    new_ids = apply_days(rows, [p.get("created_day") for p in products], out_dir)

    params = build_params(products)
    if isinstance(labels, dict) and labels:
        # ssq/6: emberi cimkek CSAK a hasznalt parameter-nevekre (a widget facet-cime, AI x)
        used = {n: str(labels[n]) for n in params["names"] if labels.get(n)}
        if used:
            params["labels"] = used
    params_body = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    pv = hashlib.sha256(params_body.encode()).hexdigest()[:12]

    body = json.dumps({"products": rows}, ensure_ascii=False, separators=(",", ":"))
    version = hashlib.sha256(body.encode()).hexdigest()[:12]
    atomic_write(index_path, body)
    atomic_write(params_path, params_body)
    atomic_write(manifest_path, json.dumps({
        "tenant": tenant, "v": version, "count": len(rows),
        "built_at": int(time.time()),
        "url_prefix": url_prefix, "img_prefix": img_prefix,
        "pv": pv, "pcount": len(params["p"]),
    }, ensure_ascii=False))
    return {"tenant": tenant, "v": version, "count": len(rows), "new_ids": new_ids,
            "index_mb": round(len(body) / 1e6, 2), "pv": pv, "pcount": len(params["p"]),
            "params_mb": round(len(params_body) / 1e6, 2), "out": out_dir,
            "scoped": bool(scope)}

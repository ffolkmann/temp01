"""m82d ELŐMÉRÉS — megéri-e a facets-szűrést kiterjeszteni nem-szuperlatívusz kérdésekre?

NINCS kódváltozás: az ÉLES facetdict/policy_filter/qdrant kódot futtatja, és azt méri,
hogy a mai (szűretlen) nem-szuperlatívusz pool mennyire felel meg a kérdésben
megnevezett bolti szűrőnek.

Három szám kell a döntéshez:
  A) FELISMERÉS  — a pozitív korpuszból hányra ad címkét a szótár (a kapu ma nem is fut)
  B) NYERESÉG    — a mai szűretlen top-24-ből hány termék felel meg TÉNYLEGESEN a címkének
                   (ha ez magas, nincs mit nyerni; ha alacsony, a modell rossz halmazból válaszol)
  C) KOCKÁZAT    — a negatív (KB/policy/általános) korpuszon 0 címkének kell lennie

Futtatás:
  docker exec -i chatbot-api-prod python - < tools/m82d_nonsuper.py
"""
import asyncio

CLIENT = "notebookstore"
LIMIT = 24  # = settings.retrieval_top_k — a nem-szuperlatívusz ág mai pool-mérete

# Nem-szuperlatívusz, termék-szándékú kérdések, amelyek megneveznek egy bolti szűrőt.
POSITIVE = [
    "Van 32 GB memóriával laptopotok?",
    "Milyen 4K monitorokat ajánlotok?",
    "Keresek egy érintőképernyős laptopot",
    "Milyen lézernyomtatóitok vannak?",
    "Ajánlj egy ujjlenyomat-olvasós üzleti laptopot",
    "Windows 11 Pro-s gépet szeretnék",
    "Van NVIDIA videokártyás notebookotok?",
    "IPS paneles monitort keresek",
    "Gamer laptopot szeretnék venni",
    "Otthoni használatra milyen notebookot ajánlasz?",
    "Tintasugaras nyomtatót keresek",
    "Milyen 16 GB RAM-os laptopjaitok vannak?",
]

# KB / policy / általános — ezekre NEM szabad termékszűrésbe esni.
NEGATIVE = [
    "Mennyibe kerül a szállítás?",
    "Milyen garancia jár a termékekre?",
    "Hogyan tudok elállni a vásárlástól?",
    "Fizethetek utánvéttel?",
    "Hol van a boltotok?",
    "Nyitva vagytok szombaton?",
    "Milyen fekete péntek akcióitok lesznek?",
    "Nem szeretnék regisztrálni, úgy is tudok rendelni?",
    "Mikor érkezik meg a csomagom?",
    "Van intelligens megoldásotok az irodára?",
    "Szeretnék panaszt tenni egy termékre",
    "Milyen fizetési módok vannak?",
]


def _is_product(h):
    p = h.get("payload") or {}
    if str(p.get("type") or "").lower() == "product":
        return True
    return bool(str(p.get("sku") or "").strip())


def _matches(h, tags, cat):
    """A találat megfelel-e a felismert szűrőnek (címkék ÉS kategória)."""
    p = h.get("payload") or {}
    fl = p.get("facets") or []
    if not isinstance(fl, (list, tuple)):
        fl = [fl]
    fl = {str(x) for x in fl}
    if not all(str(t) in fl for t in tags):
        return False
    if cat and str(p.get("category") or "") != str(cat):
        return False
    return True


async def run_one(q, msg, fmap, catalog, embed_query, deps):
    (detect_facet_tags, detect_category, category_value,
     build_facet_conditions, is_policy_query, policy_embed_input,
     product_query_cleanup) = deps

    policy = is_policy_query(msg)
    vector = await embed_query(policy_embed_input(msg, product_query_cleanup(msg)))
    hits = await q.search(vector=vector, client_id=CLIENT, limit=LIMIT, product_only=False)
    cats = [str((h.get("payload") or {}).get("category") or "") for h in hits]
    qcat = detect_category(msg, catalog)
    tags = detect_facet_tags(msg, cats, fmap, category=qcat)
    cat = category_value(cats, fmap, category=qcat) if tags else ""

    prods = [h for h in hits if _is_product(h)]
    ok = [h for h in prods if _matches(h, tags, cat)] if tags else []

    n_filtered = None
    if tags:
        fc = build_facet_conditions(tags, cat)
        fh = await q.search(vector=vector, client_id=CLIENT, limit=LIMIT,
                            product_only=False, extra_must=fc)
        n_filtered = len(fh)
        if not fh and cat:  # ugyanaz a fail-safe, mint a retrieval-ben
            fh = await q.search(vector=vector, client_id=CLIENT, limit=LIMIT,
                                product_only=False, extra_must=build_facet_conditions(tags))
            n_filtered = "%d (kat. nélkül)" % len(fh)

    return {
        "msg": msg, "policy": policy, "qcat": qcat, "cat": cat, "tags": tags,
        "n_hits": len(hits), "n_prod": len(prods), "n_ok": len(ok), "n_filtered": n_filtered,
    }


async def main():
    from app.core.embeddings import embed_query
    from app.core.qdrant import get_qdrant
    from app.services.facetdict import (build_facet_conditions, category_value,
                                        detect_category, detect_facet_tags)
    from app.services.linkfacet import load_map
    from app.services.policy_filter import is_policy_query, policy_embed_input
    from app.services.query_cleanup import product_query_cleanup
    from app.services.retrieval import category_catalog

    deps = (detect_facet_tags, detect_category, category_value,
            build_facet_conditions, is_policy_query, policy_embed_input,
            product_query_cleanup)

    fmap = load_map(CLIENT)
    catalog = await category_catalog(CLIENT)
    q = get_qdrant()
    print("facet_map kategóriák: %d | category-katalógus: %d\n"
          % (len(((fmap or {}).get("categories") or {})), len(catalog)))

    print("=" * 78)
    print("A/B) POZITÍV korpusz — felismerés + a MAI szűretlen pool megfelelősége")
    print("=" * 78)
    hit_cnt = 0
    ratios = []
    for m in POSITIVE:
        r = await run_one(q, m, fmap, catalog, embed_query, deps)
        if r["tags"]:
            hit_cnt += 1
            ratio = (100.0 * r["n_ok"] / r["n_prod"]) if r["n_prod"] else 0.0
            ratios.append(ratio)
            print("\n[+] %s" % m)
            print("    kategória : %s" % (r["cat"] or "(nincs kapu)"))
            print("    címkék    : %s" % r["tags"])
            print("    MAI pool  : %d találat / %d termék, ebből MEGFELEL: %d (%.0f%%)"
                  % (r["n_hits"], r["n_prod"], r["n_ok"], ratio))
            print("    szűrt pool: %s találat" % r["n_filtered"])
        else:
            print("\n[-] %s" % m)
            print("    NINCS címke (qcat=%r, policy=%s)" % (r["qcat"], r["policy"]))

    print("\n" + "=" * 78)
    print("C) NEGATÍV korpusz — itt 0 címkének kell lennie (vagy policy-kapu fog)")
    print("=" * 78)
    fp = []
    for m in NEGATIVE:
        r = await run_one(q, m, fmap, catalog, embed_query, deps)
        flag = "OK " if not r["tags"] else ("policy-kapu" if r["policy"] else "!! FP")
        print("%-12s | %-52s | tags=%s policy=%s cat=%r"
              % (flag, m[:52], r["tags"], r["policy"], r["cat"]))
        if r["tags"] and not r["policy"]:
            fp.append((m, r["tags"]))

    print("\n" + "=" * 78)
    print("ÖSSZEGZÉS")
    print("=" * 78)
    print("A) felismerés      : %d/%d pozitív kérdésre van címke" % (hit_cnt, len(POSITIVE)))
    if ratios:
        ratios.sort()
        print("B) mai pool-találat: átlag %.0f%% felel meg a címkének (medián %.0f%%, min %.0f%%, max %.0f%%)"
              % (sum(ratios) / len(ratios), ratios[len(ratios) // 2], ratios[0], ratios[-1]))
        print("   -> ennyi a modell rendelkezésére álló HELYES halmaz a mai, szűretlen úton")
    print("C) false positive  : %d a %d negatív kérdésből (policy-kapu nélkül számolva)"
          % (len(fp), len(NEGATIVE)))
    for m, t in fp:
        print("   !! %s -> %s" % (m, t))


asyncio.run(main())

"""m82e KOCKÁZAT-TÉRKÉP — kategória-elhajlás (melléknévi -s képző).

A vizsgált szabály: ha a kategória-név illeszkedése után MELLÉKNÉVI KÉPZŐ áll
(-s/-os/-es/-as + esetrag), akkor ott a kategória-név JELZŐ, nem a kérdés
tárgya ("NVIDIA videokártyáS notebookotok"), tehát ne vigye el a kaput.

  v1a = csak jelzői jelölt esetén "" (mai fallback: a találatok top-kategóriája)
  v1b = csak jelzői jelölt esetén marad a régi viselkedés (leghosszabb jelzői)

A tool a MODUL detect_category-jét ("ma") méri a két shadow-változat ellen, így
patch ELŐTT tervezésre, patch UTÁN igazolásra ugyanaz fut: a m82e után
"ma" == v1a kell legyen mindenütt.

Futtatás (patchelt kód + Qdrant + embed):
  docker run --rm -i --network container:chatbot-api-prod --env-file .env \\
    -v "$PWD/app:/app/app" -v "$PWD/data:/app/data" -w /app \\
    chatbot-prod-api:latest python - < tools/m82e_catdiag.py
  M82E_CATS=1 -> a 100 kategória kiírása is
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, "/app")

CLIENT = "notebookstore"
_ADJ = re.compile(r"^(?:[oea]?s)[a-z]{0,3}$")


def _tail(fm, end):
    m = re.match(r"[a-z0-9]{0,4}", fm[end:])
    return m.group(0) if m else ""


def _cands(message, catalog, _fold, _cat_parts, _cat_rx):
    fm = _fold(message)
    out = []
    for cat in catalog:
        cat = str(cat or "")
        if not cat:
            continue
        for p in _cat_parts(cat):
            rx = _cat_rx(p)
            if rx is None:
                continue
            for m in rx.finditer(fm):
                t = _tail(fm, m.end())
                adj = bool(t) and bool(_ADJ.match(t))
                out.append({"cat": cat, "part": p, "tail": t,
                            "adj": adj, "cls": 0 if adj else 1})
    return out


def _pick(cands, mode):
    if not cands:
        return ""
    top = max(c["cls"] for c in cands)
    if top == 0 and mode == "v1a":
        return ""
    pool = [c for c in cands if c["cls"] == top]
    bl = max(len(c["part"]) for c in pool)
    pool = [c for c in pool if len(c["part"]) == bl]
    return "" if len({c["cat"] for c in pool}) > 1 else pool[0]["cat"]


def _adjform(part):
    return part + ("s" if part[-1] in "aeiou" else "os")


async def main():
    from app.core.embeddings import embed_query
    from app.core.qdrant import get_qdrant
    from app.services.facetdict import (_cat_parts, _cat_rx, _fold, _leaf,
                                        build_facet_conditions, category_value,
                                        detect_category, detect_facet_tags)
    from app.services.linkfacet import load_map
    from app.services.policy_filter import policy_embed_input
    from app.services.query_cleanup import product_query_cleanup
    from app.services.retrieval import category_catalog

    fmap = load_map(CLIENT)
    catalog = await category_catalog(CLIENT)
    parts_all = sorted({p for c in catalog for p in _cat_parts(c)})
    print("category-katalógus: %d | distinct kategória-rész: %d\n"
          % (len(catalog), len(parts_all)))

    if os.environ.get("M82E_CATS"):
        for cat in sorted(catalog):
            print("%-44s | %s" % (_leaf(cat)[:44], _cat_parts(cat)))
        print()

    def cur(m):
        return detect_category(m, catalog)

    def sh(m, mode):
        return _pick(_cands(m, catalog, _fold, _cat_parts, _cat_rx), mode)

    def scan(title, questions):
        print("=" * 92)
        print(title)
        print("=" * 92)
        d_a, d_b = [], []
        for q in questions:
            c0, a, b = cur(q), sh(q, "v1a"), sh(q, "v1b")
            if c0 != a:
                d_a.append((q, c0, a))
            if c0 != b:
                d_b.append((q, c0, b))
        print("eset: %d | ma != v1a: %d | ma != v1b: %d" % (len(questions), len(d_a), len(d_b)))
        for q, c0, a in d_a[:15]:
            print("   MA!=V1A  %-44s ma=%-28s v1a=%s"
                  % (q[:44], _leaf(c0) or "(nincs)", _leaf(a) or "(nincs)"))
        if len(d_a) > 15:
            print("   ... +%d további" % (len(d_a) - 15))
        print()
        return len(d_a), len(d_b)

    # 1) JELZŐI SCAN: mind a 111 kategória-név jelzőként, notebook-kérdésben
    a1, b1 = scan("1) KIMERÍTŐ JELZŐI SCAN — 'Van {név}s notebookotok?' (a név itt JELZŐ)",
                  ["Van %s notebookotok?" % _adjform(p) for p in parts_all])

    # 2) REGRESSZIÓ: ugyanaz a 111 név FEJKÉNT — itt semminek nem szabad változnia
    heads = []
    for p in parts_all:
        heads += ["Milyen %sok vannak?" % p, "Keresek egy %st" % p, "Van %s készleten?" % p]
    a2, b2 = scan("2) REGRESSZIÓ — ugyanaz a 111 név FEJKÉNT (itt 0 eltérés kell)", heads)

    # 3) NEGATÍV korpusz (KB/policy/általános) — itt sem szabad változnia
    NEG = [
        "Mennyibe kerül a szállítás?", "Milyen garancia jár a termékekre?",
        "Hogyan tudok elállni a vásárlástól?", "Fizethetek utánvéttel?",
        "Hol van a boltotok?", "Nyitva vagytok szombaton?",
        "Milyen fekete péntek akcióitok lesznek?", "Mikor érkezik meg a csomagom?",
        "Van intelligens megoldásotok az irodára?", "Szeretnék panaszt tenni egy termékre",
        "Milyen fizetési módok vannak?", "Nem szeretnék regisztrálni, úgy is tudok rendelni?",
    ]
    a3, b3 = scan("3) NEGATÍV korpusz (itt 0 eltérés kell)", NEG)

    print("=" * 92)
    print("4) VALÓDI KÉRDÉSEK — jelöltek osztályozása")
    print("=" * 92)
    CASES = [
        "Van NVIDIA videokártyás notebookotok?",
        "Keresek egy billentyűzetes tabletet",
        "Van webkamerás monitorotok?",
        "Melyik a legolcsóbb lézernyomtató?",
        "Milyen 4K monitorokat ajánlotok?",
        "Melyik a legolcsóbb gamer asztali számítógép?",
        "Melyik a legolcsóbb notebooktáska?",
        "Van 32 GB memóriával laptopotok?",
    ]
    for q in CASES:
        cs = _cands(q, catalog, _fold, _cat_parts, _cat_rx)
        det = " ".join("%s%s[%s]" % (c["part"], "+" + c["tail"] if c["tail"] else "",
                                     "JELZO" if c["adj"] else "fej") for c in cs) or "(nincs jelölt)"
        print("\n%s\n   jelöltek : %s\n   ma       : %s | v1a: %s | v1b: %s"
              % (q, det, _leaf(cur(q)) or "(fallback)",
                 _leaf(sh(q, "v1a")) or "(fallback)", _leaf(sh(q, "v1b")) or "(fallback)"))

    print("\n" + "=" * 92)
    print("5) ÉLES POOL — a tényleges kapu és a szűrt találatszám")
    print("=" * 92)
    q = get_qdrant()
    LIVE = [
        "Van NVIDIA videokártyás notebookotok?",
        "Milyen érintőképernyős laptopjaitok vannak?",
        "Van webkamerás monitorotok?",
        "Milyen 16 GB RAM-os laptopjaitok vannak?",
        "Gamer laptopot szeretnék venni",
    ]
    for msg in LIVE:
        vector = await embed_query(policy_embed_input(msg, product_query_cleanup(msg)))
        hits = await q.search(vector=vector, client_id=CLIENT, limit=30, product_only=False)
        cats = [str((h.get("payload") or {}).get("category") or "") for h in hits]
        cnt = {}
        for c in cats:
            if c:
                cnt[c] = cnt.get(c, 0) + 1
        top3 = sorted(cnt.items(), key=lambda kv: -kv[1])[:3]
        qcat = cur(msg)
        tags = detect_facet_tags(msg, cats, fmap, category=qcat)
        cat = category_value(cats, fmap, category=qcat) if tags else ""
        n = ""
        if tags:
            fh = await q.search(vector=vector, client_id=CLIENT, limit=30, product_only=False,
                                extra_must=build_facet_conditions(tags, cat))
            n = " -> %d szűrt találat" % len(fh)
        print("\n%s" % msg)
        print("   pool top : %s" % ", ".join("%s=%d" % (_leaf(c), k) for c, k in top3))
        print("   kapu     : %s | tags=%s%s"
              % (_leaf(cat) or _leaf(qcat) or "(találat-fallback)", tags, n))

    print("\n" + "=" * 92)
    print("VERDIKT: ma!=v1a összesen %d (0 kell a m82e után) | ma!=v1b %d (a jelzői scan mérete)"
          % (a1 + a2 + a3, b1 + b2 + b3))
    print("=" * 92)


asyncio.run(main())

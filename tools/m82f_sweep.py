"""m82f MÉRÉS v2 — szülő-szintű kategória-feloldás ("laptopotok" → ÚJ Notebook).

ADAT-LELET (tools/m82f_catdiag.py): a "Laptop, Notebook" szülő alatt PONTOSAN EGY
levél van (ÚJ Notebook, 6416 termék), tehát a m82d/2-ben zsákutcának jelölt
szülő-út itt NEM fut holtversenybe.

  SZABÁLY (a shadow PONTOSAN a javasolt production-logika):
   1. levél-kör változatlan (m82e _head_match-csel); ha van FEJ-alakú
      levél-jelölt, a mai logika dönt (holtverseny -> "");
   2. HA nincs fej-alakú levél-jelölt, a SZÜLŐ-út nevei is jelöltek, de CSAK
      azoké a szülőké, amelyek alatt PONTOSAN EGY levél van;
   3. a szülő-jelölt is csak FEJ-alakban számít: esetrag ("laptopOTOK") vagy
      tagmondat-vég ("...a legolcsóbb laptop?"). A csupasz tő + másik szó
      összetételi JELZŐ ("laptop táskátok"), a -s képzős alak pedig m82e óta
      eleve nem jelölt.

Futtatás (patchelt vagy éles kód + Qdrant + embed):
  docker run --rm -i --network container:chatbot-api-prod --env-file /tmp/x.env \\
    -v "$PWD/app:/app/app" -v "$PWD/data:/app/data" -w /app \\
    chatbot-prod-api:latest python - < tools/m82f_sweep.py
"""
import asyncio
import re
import sys

sys.path.insert(0, "/app")

CLIENT = "notebookstore"
_ADJ = re.compile(r"^(?:[oea]?s)[a-z]{0,3}$")
_TAIL = re.compile(r"[a-z0-9]{0,4}")


def single_leaf_parents(catalog):
    par = {}
    for c in catalog:
        parts = [p.strip() for p in str(c).split(">")]
        if len(parts) < 2:
            continue
        par.setdefault(" > ".join(parts[:-1]), []).append(str(c))
    return {p: v[0] for p, v in par.items() if len(v) == 1}


def parent_head(rx, fm):
    """FEJ-alakban áll-e a szülő-név (esetrag vagy tagmondat-vég)?"""
    for m in rx.finditer(fm):
        tail = _TAIL.match(fm, m.end()).group(0)
        if tail:
            if _ADJ.match(tail):
                continue          # m82e: jelzői képző
            return True           # esetrag -> fej
        rest = fm[m.end():].lstrip(" -")
        if not rest or not rest[:1].isalpha():
            return True           # tagmondat-vég -> fej
    return False                  # csupasz tő + másik szó -> összetételi jelző


def make_shadow(mod, catalog):
    slp = single_leaf_parents(catalog)

    def shadow(msg):
        base = mod.detect_category(msg, catalog)
        if base:
            return base, "levél"
        fm = mod._fold(msg)
        # volt-e FEJ-alakú levél-jelölt? (ha igen, a "" valódi holtverseny)
        for c in catalog:
            for p in mod._cat_parts(c):
                rx = mod._cat_rx(p)
                if rx is not None and mod._head_match(rx, fm):
                    return "", "levél-holtverseny"
        best, best_len, tie = "", 0, False
        for par, leaf in slp.items():
            for p in mod._cat_parts(par):
                rx = mod._cat_rx(p)
                if rx is None or not parent_head(rx, fm):
                    continue
                if len(p) > best_len:
                    best, best_len, tie = leaf, len(p), False
                elif len(p) == best_len and leaf != best:
                    tie = True
        if tie or not best:
            return "", "nincs"
        return best, "szülő"
    return shadow


async def main():
    import app.services.facetdict as fd
    from app.core.embeddings import embed_query
    from app.core.qdrant import get_qdrant
    from app.services.facetdict import (_cat_parts, _leaf, build_facet_conditions,
                                        category_value, detect_category, detect_facet_tags)
    from app.services.linkfacet import load_map
    from app.services.policy_filter import policy_embed_input
    from app.services.query_cleanup import product_query_cleanup
    from app.services.retrieval import category_catalog

    fmap = load_map(CLIENT)
    catalog = await category_catalog(CLIENT)
    parts_all = sorted({p for c in catalog for p in _cat_parts(c)})
    slp = single_leaf_parents(catalog)
    shadow = make_shadow(fd, catalog)

    print("katalógus: %d | kategória-rész: %d | EGY-LEVELŰ szülő: %d"
          % (len(catalog), len(parts_all), len(slp)))
    for par, leaf in sorted(slp.items()):
        print("   %-30s -> %-28s | részek: %s" % (par[:30], _leaf(leaf)[:28], _cat_parts(par)))

    def cmp(title, questions, expect_same=False):
        print("\n" + "=" * 96)
        print(title)
        print("=" * 96)
        diff = []
        for q in questions:
            a = detect_category(q, catalog)
            b, why = shadow(q)
            if a != b:
                diff.append((q, a, b, why))
        print("eset: %d | eltérés: %d%s"
              % (len(questions), len(diff), "  (0 KELL)" if expect_same else ""))
        vals = {}
        for _q, _a, b, _w in diff:
            vals[_leaf(b) or "(fallback)"] = vals.get(_leaf(b) or "(fallback)", 0) + 1
        if vals:
            print("   az UJ ertekek eloszlasa: %s" % vals)
        for q, a, b, why in diff[:12]:
            print("   %-46s ma=%-22s uj=%-22s (%s)"
                  % (q[:46], _leaf(a) or "(fallback)", _leaf(b) or "(fallback)", why))
        if len(diff) > 12:
            print("   ... +%d további" % (len(diff) - 12))
        return len(diff)

    heads = []
    for p in parts_all:
        heads += ["Milyen %sok vannak?" % p, "Keresek egy %st" % p, "Van %s készleten?" % p]
    r1 = cmp("1) REGRESSZIÓ — 111 kategória-név FEJKÉNT (3 alak)", heads, True)

    adj = ["Van %s%s notebookotok?" % (p, "s" if p[-1] in "aeiou" else "os") for p in parts_all]
    r2 = cmp("2) JELZŐI SCAN — 'Van {név}s notebookotok?' (itt a FEJ a notebook, "
             "tehát az ÚJ Notebook a HELYES; ma találat-fallback)", adj)

    NEG = [
        "Mennyibe kerül a szállítás?", "Milyen garancia jár a termékekre?",
        "Hogyan tudok elállni a vásárlástól?", "Fizethetek utánvéttel?",
        "Hol van a boltotok?", "Nyitva vagytok szombaton?",
        "Milyen fekete péntek akcióitok lesznek?", "Mikor érkezik meg a csomagom?",
        "Van intelligens megoldásotok az irodára?", "Szeretnék panaszt tenni egy termékre",
        "Milyen fizetési módok vannak?", "Nem szeretnék regisztrálni, úgy is tudok rendelni?",
        "Szeretnék reklamálni", "Van személyes átvétel?", "Számlát tudtok adni?",
    ]
    r3 = cmp("3) NEGATÍV korpusz", NEG, True)

    WANT = [
        "Van 32 GB memóriával laptopotok?",
        "Milyen laptopokat ajánlotok?",
        "Keresek egy laptopot",
        "Van notebookotok?",
        "Melyik a legolcsóbb laptop?",
        "Ajánlj egy laptopot irodai munkára",
        "Milyen notebookot vegyek egyetemre?",
        "Milyen notebookjaitok vannak 16 GB RAM-mal?",
    ]
    cmp("4) CÉL-KORPUSZ — itt VÁRJUK az ÚJ Notebookot", WANT)

    TRAP = [
        "Van laptop táskátok?", "Milyen laptop töltőt ajánlotok?",
        "Keresek egy laptop hűtőt", "Van notebook állványotok?",
        "Milyen notebook táskáitok vannak?", "Laptop akkumulátort keresek",
        "Van laptop dokkolótok?", "Milyen notebook hűtőt ajánlotok?",
        "Van laptopos táskátok?", "Melyik a legolcsóbb notebooktáska?",
    ]
    print("\n" + "=" * 96)
    print("5) ÖSSZETÉTELI JELZŐ-CSAPDÁK — NEM szabad ÚJ Notebookra állni")
    print("=" * 96)
    bad = 0
    for q in TRAP:
        a = detect_category(q, catalog)
        b, why = shadow(q)
        hit = b and _leaf(b) == "ÚJ Notebook"
        bad += 1 if hit else 0
        print("   %-42s ma=%-26s uj=%-26s (%s)%s"
              % (q[:42], _leaf(a) or "(fallback)", _leaf(b) or "(fallback)", why,
                 "  <-- FIGYELEM" if hit else ""))
    print("   csapdába esett: %d / %d" % (bad, len(TRAP)))

    print("\n" + "=" * 96)
    print("6) ÉLES POOL — a kapu és a szűrt találatszám ma vs. új")
    print("=" * 96)
    q = get_qdrant()
    LIVE = [
        "Van 32 GB memóriával laptopotok?",
        "Van NVIDIA videokártyás notebookotok?",
        "Van laptop táskátok?",
    ]
    for msg in LIVE:
        vector = await embed_query(policy_embed_input(msg, product_query_cleanup(msg)))
        hits = await q.search(vector=vector, client_id=CLIENT, limit=30, product_only=False)
        cats = [str((h.get("payload") or {}).get("category") or "") for h in hits]
        cnt = {}
        for c in cats:
            if c:
                cnt[c] = cnt.get(c, 0) + 1
        print("\n%s" % msg)
        print("   pool top : %s"
              % ", ".join("%s=%d" % (_leaf(c), n)
                          for c, n in sorted(cnt.items(), key=lambda kv: -kv[1])[:3]))
        for label, qcat in (("ma ", detect_category(msg, catalog)), ("uj ", shadow(msg)[0])):
            tags = detect_facet_tags(msg, cats, fmap, category=qcat)
            cat = category_value(cats, fmap, category=qcat) if tags else ""
            extra = ""
            if tags:
                fh = await q.search(vector=vector, client_id=CLIENT, limit=30,
                                    product_only=False,
                                    extra_must=build_facet_conditions(tags, cat))
                names = [str((h.get("payload") or {}).get("name") or "")[:36] for h in fh[:2]]
                extra = " -> %d szűrt | %s" % (len(fh), " ; ".join(names))
            print("   %s kapu=%-26s tags=%s%s"
                  % (label, _leaf(cat) or _leaf(qcat) or "(találat-fallback)", tags, extra))

    print("\n" + "=" * 96)
    print("VERDIKT: regressziós eltérés (1+3) = %d (0 kell) | csapda %d (0 kell) | "
          "jelzői scan %d eset javul" % (r1 + r3, bad, r2))
    print("=" * 96)


asyncio.run(main())

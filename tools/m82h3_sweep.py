"""m82h/3 SWEEP: a MARKANEV kivezetese az EMBEDELT kerdesbol (shadow).

DIAGNOZIS (tools/m82h3_diag.py): a marka must-feltetel mar szur, de a marka
NEVE bennemarad az embedelt kerdesben -> a vektor a markara huz, a szurt
poolban viszont MINDEN termek ugyanattol a markatol van, tehat a marka-jel
NULLA informacio. Kovetkezmeny: az altipus ("sator", "szaraz", "okosora")
nem hoz talalatot: Delphin-nal limit=1000 mellett is csak 6 sator, legjobb
dense rank 120.

JAVASOLT SZABALY (v1): ha a marka-szures fut (cons["brand"]), az EMBEDELT
szovegbol a marka nevet kivesszuk -- TOKEN-szinten, hogy a maradek EKEZETES
maradjon (ekezet nelkul gyenge az embed). Ha a maradek ertelmetlen (<3
karakter alfanumerikus), marad a mai embed (fail-safe: "Van Ryobi
termeketek?" tipusu, tiszta marka-kerdes).

v2 = v1 + emelt pool-limit (a marka-halmaz nagy lehet).

Futtatas: docker exec -i chatbot-api-prod python - < tools/m82h3_sweep.py
"""
import asyncio
import re
import sys
import unicodedata

sys.path.insert(0, "/app")

from app.core.embeddings import embed_query  # noqa: E402
from app.core.qdrant import get_qdrant  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.services.paramextract import build_filter_conditions, detect_constraints  # noqa: E402
from app.services.policy_filter import policy_embed_input  # noqa: E402
from app.services.query_cleanup import product_query_cleanup  # noqa: E402
from app.services.rerank import rerank  # noqa: E402

S = get_settings()
_SPLIT = re.compile(r"([^0-9A-Za-zÀ-ÿ]+)")
_MIN_REST = 3


def fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c))


def strip_brand(message, brand_key):
    """A marka szavainak kivetele a szovegbol, TOKEN-szinten (ekezet marad).

    brand_key: a branddict kulcs slug-alakja ("carp-expert") vagy szokozos.
    Ures/tul rovid maradek -> "" (a hivo ilyenkor a mai embedet hasznalja).
    """
    words = {w for w in re.split(r"[^0-9a-z]+", fold(brand_key)) if w}
    if not words:
        return ""
    parts = _SPLIT.split(message)
    out = []
    for p in parts:
        out.append("" if fold(p) in words else p)
    rest = "".join(out)
    if len(re.sub(r"[^0-9A-Za-zÀ-ÿ]+", "", rest)) < _MIN_REST:
        return ""
    return re.sub(r"\s{2,}", " ", rest).strip(" ,.-")


try:  # igazolo mod: ha a patchelt modul elerheto, AZT merjuk
    from app.services.branddict import strip_brand as _mod_strip
except Exception:  # noqa: BLE001
    _mod_strip = None


CASES = [
    ("CEL", "fishingoutlet", "Milyen Delphin sátratok van?", ["sator"]),
    ("CEL", "nagyonallatshop", "Whiskas száraz tápot kerestek?", ["szaraz"]),
    ("CEL", "kellegyszerszam", "Ryobi akkus fúrót keresek", ["furo"]),
    ("CEL", "copygo", "Xiaomi okosóra érdekelne", ["watch", "okosora", "smart band", "band"]),
    ("CEL", "fishingoutlet", "Delphin merítőszák érdekelne", ["merito"]),
    ("KONTROLL", "notebookstore", "Milyen HP tintapatronotok van?", ["tintapatron"]),
    ("KONTROLL", "fishingoutlet", "Carp Expert bototok van?", ["bot"]),
    ("KONTROLL", "notebookstore", "Van MSI laptopotok?", ["msi"]),
    ("TISZTA-MARKA", "kellegyszerszam", "Van Ryobi termeketek?", ["ryobi"]),
    ("TISZTA-MARKA", "notebookstore", "és ASUS márkájúak közül?", ["asus"]),
]


def is_hit(p, words):
    n = fold(p.get("payload", {}).get("name"))
    return any(w in n for w in words)


async def run(cid, msg, embed_text, limit, must):
    vector = await embed_query(policy_embed_input(embed_text, product_query_cleanup(embed_text)))
    hits = await get_qdrant().search(vector=vector, client_id=cid, limit=limit,
                                     product_only=False, extra_must=must)
    rr = rerank(msg, hits, top_n=S.context_top_n)
    return hits, rr


async def main():
    print("%-13s %-16s %-34s | %-22s | v0 pool/top8 | v1 pool/top8 | v2 pool/top8"
          % ("tag", "tenant", "kerdes", "embed v1/v2 szovege"))
    print("-" * 150)
    stat = {"v0": 0, "v1": 0, "v2": 0}
    for tag, cid, msg, words in CASES:
        cons = detect_constraints(msg, cid)
        must = build_filter_conditions(cons)
        if not must:
            print("%-13s %-16s %-34s | NINCS MARKA-SZURO" % (tag, cid, msg[:34]))
            continue
        stripped = (_mod_strip or strip_brand)(msg, cons.get("brand") or "")
        etext = stripped or msg
        res = []
        for name, txt, lim in (("v0", msg, S.retrieval_top_k),
                               ("v1", etext, S.retrieval_top_k),
                               ("v2", etext, 300)):
            hits, rr = await run(cid, msg, txt, lim, must)
            inpool = sum(1 for p in hits if is_hit(p, words))
            intop = sum(1 for p in rr if is_hit(p, words))
            res.append((name, len(hits), inpool, intop))
            if intop:
                stat[name] += 1
        print("%-13s %-16s %-34s | %-22s | %s"
              % (tag, cid, msg[:34], (stripped or "(marad a mai)")[:22],
                 " | ".join("%s %3d/%2d/%d" % (n, ln, ip, it) for n, ln, ip, it in res)))
    print("-" * 150)
    print("   jelmagyarazat: <valtozat> <pool-meret>/<altipus a poolban>/<altipus a rerank top-8-ban>")
    print("   ESET, AHOL A TOP-8-BAN VAN ALTIPUS: v0=%d  v1=%d  v2=%d  (osszes eset: %d)"
          % (stat["v0"], stat["v1"], stat["v2"], len(CASES)))

    print()
    print("=" * 100)
    print("RESZLETEK a cel-esetekre (v2 rerank top-8 nevei)")
    print("=" * 100)
    for tag, cid, msg, words in CASES:
        if tag != "CEL":
            continue
        cons = detect_constraints(msg, cid)
        must = build_filter_conditions(cons)
        etext = (_mod_strip or strip_brand)(msg, cons.get("brand") or "") or msg
        _, rr = await run(cid, msg, etext, 300, must)
        print("[%s] %s   (embed: %r)" % (cid, msg, etext))
        for p in rr:
            pl = p.get("payload", {}) or {}
            print("    %s %s | %s Ft" % ("*" if is_hit(p, words) else " ",
                                         str(pl.get("name"))[:66], pl.get("price")))


asyncio.run(main())

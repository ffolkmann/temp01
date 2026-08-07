"""m85/2: a nyelvi res ELLENORZESE — van-e egyaltalan olyan termek, amit a magyar
kerdes keres, es ha igen, elojon-e?

A m85/1 azt mutatta, hogy a "lexikai vaksag" nagy resze NEM nyelvi res (rendeles-
szam, e-mail, koszones, toldalekos alak), a kontroll-esetek pedig mukodnek
("laptopotok" -> Notebook, "szaraz tap" -> szarazeledel). Egyetlen bukó maradt:
copygo "Xiaomi okosora". Itt azt merjuk, hogy a boltban LETEZIK-e a kert termek
(nev-szubsztring alapjan), es a top-8-ba bekerul-e.

Csak olvas. Futtatas:
  docker exec -i chatbot-api-prod python - < tools/m85_langgap2.py
"""
import asyncio
import json
import sys
import unicodedata
import urllib.request

sys.path.insert(0, "/app")

from app.services.policy_filter import _is_product  # noqa: E402
from app.services.retrieval import retrieve  # noqa: E402

Q = "http://qdrant:6333"
COLL = "cx_chatbot_v2"

# (tenant, magyar kerdes, a bolti nev VART alakjai)
CASES = [
    ("copygo", "Xiaomi okosóra érdekelne", ["watch", "band", "okosora", "smart band"]),
    ("copygo", "Van okosórátok?", ["watch", "band", "okosora"]),
    ("copygo", "fülhallgatót keresek", ["headphone", "headset", "buds", "fulhallgato", "earbud"]),
    ("notebookstore", "Van olcsó laptopotok?", ["notebook", "laptop"]),
    ("nagyonallatshop", "Whiskas száraz tápot kerestek?", ["szarazeledel", "szaraz"]),
    ("fishingoutlet", "Milyen sátratok van?", ["sator", "shelter", "bivvy", "brolly"]),
    ("kellegyszerszam", "Van akkus csavarbehajtótok?", ["csavarozo", "csavarbehajto", "impact"]),
]


def post(path, body, timeout=180):
    r = urllib.request.Request(Q + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def fold(s):
    d = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in d if not unicodedata.combining(c))


def catalog_hits(cid, needles, cap=60):
    """Hany termek neveben szerepel valamelyik alak? (nev-szubsztring, teljes katalogus)"""
    found, n = [], 0
    offset = None
    for _ in range(120):
        body = {"filter": {"must": [{"key": "client_id", "match": {"value": cid}},
                                    {"key": "type", "match": {"value": "product"}}]},
                "limit": 1000, "with_payload": ["name", "available", "category"],
                "with_vector": False}
        if offset:
            body["offset"] = offset
        res = post("/collections/%s/points/scroll" % COLL, body)["result"]
        for pt in res.get("points", []):
            p = pt.get("payload") or {}
            nm = fold(p.get("name"))
            n += 1
            if any(x in nm for x in needles):
                if len(found) < cap:
                    found.append((str(p.get("name"))[:64], p.get("available"),
                                  str(p.get("category") or "")[:40]))
                else:
                    found.append(None)
        offset = res.get("next_page_offset")
        if not offset:
            break
    real = [f for f in found if f]
    return n, len(found), real


async def main():
    for cid, q, needles in CASES:
        tot, n_match, sample = catalog_hits(cid, needles)
        hits, _s, _m = await retrieve(q, q, cid)
        prods = [h for h in hits if _is_product(h)]
        in_top = [h for h in prods
                  if any(x in fold((h.get("payload") or {}).get("name")) for x in needles)]
        print("=" * 100)
        print("[%s] %r   alakok=%s" % (cid, q, needles))
        print("  katalogus: %d termek, ebbol NEVBEN egyezo: %d | top-8-ban: %d/%d"
              % (tot, n_match, len(in_top), len(prods)))
        if n_match:
            print("  minta a katalogusbol:")
            for nm, av, cat in sample[:5]:
                print("     %-9s %-62s %s" % ("KAPHATO" if av is True else
                                              ("KIFUTO" if av is False else "n/a"), nm, cat))
        if n_match and not in_top:
            print("  >>> NYELVI RES IGAZOLVA: van ilyen termek, de a top-8-ba EGY SEM jott be")
            print("  a top-8 helyette:")
            for h in prods[:5]:
                print("     %s" % str((h.get("payload") or {}).get("name"))[:76])
        elif not n_match:
            print("  >>> NINCS ilyen termek a boltban -> a bot helyesen nem talal (nem res)")
        else:
            print("  >>> OK: a dense embed athidalja a nyelvi kulonbseget")


asyncio.run(main())

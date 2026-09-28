"""m108 elotte/utana: retrieve() a szuperlativusz-kerdesekre, a kontextus termekei.
Futtatas a kontenerben: cd <appdir> && python m108_sweep.py <tag>"""
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="LOG %(name)s %(message)s")
for n in ("httpx", "httpcore"):
    logging.getLogger(n).setLevel(logging.WARNING)

Q = [
    # valodi (30 nap) - copygo
    ("copygo", "melyik a legolcsóbb lézer nyomtató?"),
    ("copygo", "melyik a legolcsóbb lézernyomtató?"),
    ("copygo", "melyik a legolcsóbb lézernyomttó"),
    ("copygo", "mennyi a legolcsóbb szállítás"),
    # szintetikus copygo
    ("copygo", "melyik a legolcsóbb tintasugaras nyomtató?"),
    ("copygo", "melyik a legolcsóbb multifunkciós nyomtató?"),
    ("copygo", "legolcsóbb színes lézernyomtató"),
    ("copygo", "melyik a legdrágább lézernyomtató?"),
    ("copygo", "legolcsóbb nyomtató"),
    ("copygo", "legolcsóbb projektor"),
    ("copygo", "legolcsóbb laptop"),
    ("copygo", "legolcsóbb szkenner"),
    ("copygo", "legolcsóbb fénymásoló"),
    ("copygo", "legolcsóbb inverter"),
    ("copygo", "legolcsóbb napelem"),
    ("copygo", "legolcsóbb router"),
    ("copygo", "legolcsóbb toner"),
    ("copygo", "legolcsóbb HP toner"),
    ("copygo", "legolcsóbb egér"),
    ("copygo", "legolcsóbb szünetmentes"),
    ("copygo", "legolcsóbb okosóra"),
    # teslashop
    ("teslashop", "melyik a legolcsóbb gumiszőnyeg?"),
    ("teslashop", "legolcsóbb töltő"),
    ("teslashop", "legolcsóbb felni"),
    ("teslashop", "legolcsóbb Model 3 gumiszőnyeg"),
    ("teslashop", "legdrágább felni"),
    ("teslashop", "legolcsóbb kijelzővédő fólia"),
    # nem erintett tenantok (valodi)
    ("notebookstore", "Legolcsóbb laptop?"),
    ("fishingoutlet", "Harcsázó orsóból melyik a legolcsóbb?"),
    ("kellegyszerszam", "A legolcsobb kalapács"),
]


async def main(tag):
    from app.services.retrieval import retrieve
    out = []
    for cid, q in Q:
        try:
            hits, top, mode = await retrieve(q, q, cid, hide_oos=True)
        except Exception as e:  # noqa: BLE001
            out.append({"cid": cid, "q": q, "err": repr(e)})
            continue
        rows = []
        for h in hits:
            pl = h.get("payload", h)
            if str(pl.get("type") or "") != "product":
                rows.append(["KB", str(pl.get("filename") or "")[:40]])
                continue
            rows.append([pl.get("price"), pl.get("available"), str(pl.get("name") or "")[:70]])
        out.append({"cid": cid, "q": q, "mode": mode, "top": round(top, 3), "ctx": rows})
    print("JSON " + json.dumps({"tag": tag, "res": out}, ensure_ascii=False))
    for r in out:
        print("\n### [%s] %s | %s mode=%s" % (tag, r["cid"], r["q"], r.get("mode")))
        for x in r.get("ctx") or []:
            print("   ", x)
        if r.get("err"):
            print("   ERR", r["err"])


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "x"))

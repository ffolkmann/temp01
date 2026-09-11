"""m103: lexmatch (cikkszam- es lexikai nev-ag) - tiszta fuggvenyek + augment fake Qdranttal.

Fajl-betoltos import: a suite mas tesztjei fake app.services-t hagyhatnak a sys.modules-ben.
"""
import importlib.util
import pathlib
import time

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "lexmatch.py"
_spec = importlib.util.spec_from_file_location("lexmatch_m103", _p)
lx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lx)

E = [
    (1, lx.fold("Fieldmann Faszenes Grillsütő FZG 1010"), "41010001", True),
    (2, lx.fold("Fieldmann Inox gáz grillsütő 3+1 égőfej integrált gyújtás"), "41010418", True),
    (3, lx.fold("Fieldmann gáz grillsütő 2 égőfej integrált gyújtás"), "41012388", False),
    (4, lx.fold("YATO 125 mm Sarokcsiszoló porelszívó adapter vágáshoz"), lx.norm_sku("YT-82992"), True),
    (5, lx.fold("Carp Zoom CZ Összkomfortos horgász fotel, 63x60"), "cz1", True),
    (6, lx.fold("Legjobb horgász! -Hűtőmágnes"), "x2", True),
    (7, lx.fold("Huawei Luna Smart Power Sensor 3F 80A HUAWEI"), "hl80", True),
    (8, lx.fold("Huawei Luna Smart Power Sensor 3F 100A HUAWEI"), "hl100", True),
    (9, lx.fold("YATO valami 24231"), lx.norm_sku("P-YT-24231"), True),
    (10, lx.fold("BAIT MAKER Kaptár 10 mm Sajt 30g"), "b1", True),
    (11, lx.fold("Btech BC-MS8 asztali számológép, napelemes"), "b2", True),
    (12, lx.fold("Nagy képernyős párhuzamos feladatvégzés. Konfigurálható laptop"), "m1", True),
]
E += [(100 + i, "horgasz kiegeszito %d" % i, "s%d" % i, True) for i in range(200)]


def names(ids):
    return [e[1] for e in E if e[0] in ids]


def test_tokenek():
    assert lx.query_tokens("Gáz grill jó áron szeretnék") == ["gaz", "grill"]
    assert lx.sku_tokens("Keresem a yt82992 cikkszàmú terméket") == ["yt82992"]
    assert lx.sku_tokens("hívj a 06301234567 számon") == []
    assert lx.sku_tokens("Bosch fúró") == []


def test_nev_ag_gazgrill_es_fotel():
    s, n, _ = lx.pick(E, "Gáz grill jó áron szeretnék", ["Fieldmann Faszenes Grillsütő FZG 1010"])
    assert s == [] and n and all("gaz grill" in x for x in names(n))
    s, n, _ = lx.pick(E, "Horgasz fotelt keresek", ["Legjobb horgász! -Hűtőmágnes"])
    assert n == [5]


def test_testver_variant_teljes_fedes():
    s, n, _ = lx.pick(E, "Huawei Luna Smart Power Sensor 3F 80A HUAWEI",
                      ["Huawei Luna Smart Power Sensor 3F 100A HUAWEI"], exclude_ids=[8])
    assert n == [7]


def test_cikkszam_ag():
    assert lx.pick(E, "Keresem a yt82992 cikkszàmú terméket", [])[0] == [4]
    assert lx.pick(E, "YT-24231 kellene", [])[0] == [9]  # szallito-elotag (P-YT-24231)


def test_hamis_pozitiv_vedelem():
    for q in ("Nem kaptam imailt sajnos", "Mikortól számolva a 4-5 nap?", "Igen", "kössz",
              "az elég nagy hely?"):
        assert lx.pick(E, q, [])[1] == [], q


def test_marketing_nev_kizarva():
    assert 12 not in lx.pick(E, "konfigurálható laptop párhuzamos", [])[1]


def test_pool_mar_fedi_es_tul_altalanos():
    assert lx.pick(E, "gáz grill", ["Fieldmann Inox gáz grillsütő 3+1 égőfej"])[1] == []
    assert lx.pick(E, "horgász kiegészítő", [])[1] == []  # 200-as szint > _TIER_MAX


def test_hide_oos():
    _, n, _ = lx.pick(E, "gáz grill", [], hide_oos=True)
    assert n == [2]


async def test_augment_fake_qdrant():
    async def fake_fetch(ids):
        return [{"id": i, "payload": {"type": "product", "name": "N%s" % i, "url": "/p/%s" % i}} for i in ids]

    async def noop(cid):
        return None
    old_f, old_b = lx._fetch_points, lx._build_guarded
    lx._fetch_points, lx._build_guarded = fake_fetch, noop
    lx._cache["t103"] = (time.monotonic(), E)
    try:
        hits = [{"id": 1, "score": 0.61, "payload": {"type": "product", "name": "Fieldmann Faszenes Grillsütő"}}]
        out = await lx.augment(hits, "Gáz grill kellene", "t103")
        assert len(out) > 1 and all(h.get("m103") for h in out[1:])
        assert out[1]["score"] == 0.61 and out[0] is hits[0]
        assert await lx.augment(hits, "", "t103") == hits
        assert await lx.augment(hits, "Gáz grill kellene", "nincs-katalogus") == hits  # pool valtozatlan
    finally:
        lx._fetch_points, lx._build_guarded = old_f, old_b
        lx._cache.pop("t103", None)

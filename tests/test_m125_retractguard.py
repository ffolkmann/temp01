# -*- coding: utf-8 -*-
"""m125 (K1): visszavonas-orseg + elozo kor adatai."""
import importlib.util
import os

_D = os.path.dirname(__file__)
_P = os.path.join(_D, "..", "app", "services", "retractguard.py")
_spec = importlib.util.spec_from_file_location("retractguard_m125", _P)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

REAL = [  # valodi kimenetek (d21b korpusz, 10-12..10-20)
    "Szívesen! Egy pontosítás az előző válaszomhoz: a banki átutalásnál és az AJI kártyánál írt részleteket nem tudom biztosan megerősíteni.",
    "Pontosítanom kell: az előző üzenetemben az MPL postapontos díjakat nem tudom megerősíteni, ezért kérlek, azokat ne vedd biztosra.",
    "Pontosítom a korábbi válaszomat: a Brit termékekről mostani adatom nincs.",
    "Az előző üzeneteimben pedig tévedtem: nem tudom, melyik termékre gondolsz.",
    "a SATA-s Seagate IronWolf ajánlásról most nem látok megbízható adatot, ezért azt ne vedd figyelembe.",
]
CLEAN = [
    "Szívesen! Ha bármiben segíthetek még, itt vagyok. 🎣",
    "A Mikado Cat Territory BANG kapásjelző 11 781 Ft, raktáron van.",
    "Nem tudom megerősíteni, hogy ipari terhelést is bír, ezt az ügyfélszolgálat tudja.",
    "Ahogy fent írtam, a GLS csomagpont díja 1 390 Ft.",
]


def test_detects_real_retractions():
    for t in REAL:
        assert rg.is_retraction(t), t


def test_clean_answers_not_flagged():
    for t in CLEAN:
        assert not rg.is_retraction(t), t


def test_user_disputes():
    for m in ("Ez nem igaz. A fizetésnél tartok és nincs ott olyan", "Rossz linket küldtél",
              "nem stimmel az ár", "tévedsz, ez 25 méteres"):
        assert rg.user_disputes(m), m
    for m in ("Köszönöm!", "Elektromos", "A 25 méteres kellene", "Utánvéttel nincs?", "részben"):
        assert not rg.user_disputes(m), m


def test_has_assistant():
    assert not rg.has_assistant([])
    assert not rg.has_assistant([{"role": "user", "content": "x"}])
    assert rg.has_assistant([{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}])


DYN = ("Ma 2026-10-21, szerda.\n\n# AKTUALIS TERMEK (pontos, ellenorzott adatlap)\nTermek A 1000 Ft"
       "\n\n# TUDASBAZIS\nchunk1\n\n---\n\nchunk2 Szallitas 990 Ft\n\n# KESZLET-ALAPU AJANLAS\nszabaly"
       "\n\n# KERESESI MOD\nnote\n\n# WEBSHOP KERESO TALALATAI\n- B — https://x/b")


def test_extract_data_keeps_only_data_sections():
    out = rg.extract_data(DYN)
    assert "Termek A 1000 Ft" in out and "chunk2 Szallitas 990 Ft" in out and "https://x/b" in out
    assert "KESZLET-ALAPU" not in out and "KERESESI MOD" not in out and "szerda" not in out


def test_extract_data_skips_empty_kb():
    assert rg.extract_data("x\n\n# TUDASBAZIS\n(nincs talalat a tudasbazisban)") == ""


def test_merge_rolling_and_limit():
    assert rg.merge("A", "") == "A"
    assert rg.merge("A", "B") == "A\n\nB"
    assert rg.merge("AB", "B") == "AB"
    assert len(rg.merge("x" * 8000, "y" * 8000)) == rg.MAX_CHARS
    assert rg.merge("", "B") == "B"


def test_prev_block_and_note():
    assert rg.prev_block("") == ""
    b = rg.prev_block("chunk")
    assert "# ELOZO KOR ADATAI" in b and b.endswith("chunk")
    assert "csak akkor" in rg.NOTE and "# KORABBI VALASZAID" in rg.NOTE


def test_retrieval_note_m77_only_outside_oos_guard():
    assert rg.retrieval_note("oos_guard", "N", True) == "N"
    assert rg.retrieval_note("stock_filtered", "N", True).startswith("N FIGYELEM")
    assert rg.retrieval_note("stock_filtered", "N", False) == "N"
    assert rg.retrieval_note("", "", True) == ""


class _FakeRedis:
    def __init__(self):
        self.d = {}

    async def get(self, k):
        return self.d.get(k)

    async def set(self, k, v, ex=None):
        self.d[k] = v


class _BadRedis:
    async def get(self, k):
        raise RuntimeError("down")

    async def set(self, k, v, ex=None):
        raise RuntimeError("down")


async def test_load_save_roundtrip_and_failsafe():
    r = _FakeRedis()
    assert await rg.load_prev(r, "t", "s1") == ""
    await rg.save(r, "t", "s1", "CUR", "")
    assert await rg.load_prev(r, "t", "s1") == "CUR"
    await rg.save(r, "t", "s1", "NEW", "CUR")
    assert await rg.load_prev(r, "t", "s1") == "NEW\n\nCUR"
    assert await rg.load_prev(r, "t", None) == ""
    await rg.save(r, "t", None, "X", "")
    assert await rg.load_prev(_BadRedis(), "t", "s1") == ""
    await rg.save(_BadRedis(), "t", "s1", "X", "")  # nem dob


def test_chat_hooks_present():
    src = open(os.path.join(_D, "..", "app", "api", "chat.py"), encoding="utf-8").read()
    assert "m125 elozo-kor" in src and "m125 retract guard" in src and "_rn125" in src
    assert "valaszodnak, es roviden jelezd" not in src  # a m77 szoveg a modulba koltozott

"""m93: a KB-dokumentum letöltés (kbdoc) tesztjei.

Fájl-betöltős import (spec_from_file_location), mert a suite más tesztjei fake
app.services-t hagynak a sys.modules-ben (kf/13, m80b, m89 tanulsága).
"""
import importlib.util
import os
import pathlib
import tempfile

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "kbdoc.py"
_spec = importlib.util.spec_from_file_location("kbdoc_m93", _p)
kb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kb)

C = kb.CHUNK


def _pt(idx, text):
    return {"payload": {"idx": idx, "text": text}}


# --- safe_name / disk_name: utvonal-bejaras es utkozes --------------------
def test_safe_name_kiszuri_az_utvonalat():
    assert kb.safe_name("../../etc/passwd") == "passwd"
    assert kb.safe_name("/abs/path/doc.txt") == "doc.txt"
    assert kb.safe_name("..") == "doc"
    assert kb.safe_name("") == "doc"
    assert kb.safe_name(None) == "doc"


def test_safe_name_hosszt_vag():
    assert len(kb.safe_name("a" * 500 + ".txt")) <= 120


def test_disk_name_nem_utkozik_ekezetes_neveknel():
    # safe_name onmagaban ugyanarra vinne a kettot -> a hash valasztja szet
    a = kb.disk_name("árazás.txt")
    b = kb.disk_name("arazas.txt")
    assert a != b
    assert "/" not in a and "/" not in b


def test_disk_name_determinisztikus():
    assert kb.disk_name("gyik.txt") == kb.disk_name("gyik.txt")


# --- join_chunks: sorrend ------------------------------------------------
def test_join_chunks_idx_szerint_rendez():
    pts = [_pt(2, "C" * 10), _pt(0, "A" * C), _pt(1, "B" * C)]
    out = kb.join_chunks(pts)
    assert out.startswith("A" * C)
    assert out.endswith("C" * 10)
    assert out.index("B") < out.index("C")


def test_join_chunks_ures_es_szemet():
    assert kb.join_chunks([]) == ""
    assert kb.join_chunks(None) == ""
    assert kb.join_chunks(["nem dict", {"payload": None}, {"payload": {"text": ""}}]) == ""


# --- join_chunks: elvalaszto-logika --------------------------------------
def test_teljes_hosszu_szeletek_kozott_nincs_elvalaszto():
    pts = [_pt(0, "A" * C), _pt(1, "B" * C), _pt(2, "C" * C)]
    assert kb.join_chunks(pts) == "A" * C + "B" * C + "C" * C


def test_rovidebb_szelet_utan_sortorest_teszunk():
    pts = [_pt(0, "A" * (C - 1)), _pt(1, "B" * C)]
    assert kb.join_chunks(pts) == "A" * (C - 1) + "\n" + "B" * C


def test_az_utolso_szelet_rovidsege_nem_szamit():
    pts = [_pt(0, "A" * C), _pt(1, "B" * 12)]
    assert kb.join_chunks(pts) == "A" * C + "B" * 12


def test_soha_nem_ragaszt_ossze_ket_szot_strip_eseten():
    pts = [_pt(0, "sorozat" + "x" * (C - 8)), _pt(1, "gyartas" + "y" * (C - 7))]
    out = kb.join_chunks(pts)
    assert "xgyartas" not in out
    assert "\n" in out


def test_hianyzo_idx_eseten_nem_szall_el():
    pts = [{"payload": {"text": "egy"}}, {"payload": {"idx": "nem szam", "text": "ketto"}}]
    out = kb.join_chunks(pts)
    assert "egy" in out and "ketto" in out


# --- eredeti fajl korut --------------------------------------------------
def test_eredeti_iras_olvasas_torles_korut():
    with tempfile.TemporaryDirectory() as d:
        assert kb.read_original("t1", "a.txt", base=d) is None
        kb.write_original("t1", "a.txt", "Árvíztűrő\nszöveg\n".encode("utf-8"), base=d)
        assert kb.read_original("t1", "a.txt", base=d) == "Árvíztűrő\nszöveg\n"
        assert kb.delete_original("t1", "a.txt", base=d) is True
        assert kb.delete_original("t1", "a.txt", base=d) is False
        assert kb.read_original("t1", "a.txt", base=d) is None


def test_ket_ekezetes_nev_nem_irja_felul_egymast():
    with tempfile.TemporaryDirectory() as d:
        kb.write_original("t1", "árazás.txt", b"AAA", base=d)
        kb.write_original("t1", "arazas.txt", b"BBB", base=d)
        assert kb.read_original("t1", "árazás.txt", base=d) == "AAA"
        assert kb.read_original("t1", "arazas.txt", base=d) == "BBB"


def test_eredeti_iras_nem_lep_ki_a_konyvtarbol():
    with tempfile.TemporaryDirectory() as d:
        kb.write_original("../../evil", "../../evil.txt", b"x", base=d)
        found = []
        for root, _dirs, files in os.walk(d):
            for f in files:
                found.append(os.path.join(root, f))
        assert len(found) == 1
        assert os.path.realpath(found[0]).startswith(os.path.realpath(d))


def test_nem_utf8_eredetit_is_visszaad():
    with tempfile.TemporaryDirectory() as d:
        kb.write_original("t2", "b.txt", "árvíz".encode("cp1250"), base=d)
        out = kb.read_original("t2", "b.txt", base=d)
        assert isinstance(out, str) and out

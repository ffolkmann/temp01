"""kf/13: az adminbol kert index-build keres/futas/eredmeny kezelesenek tesztjei.

A modul stdlib-only, ezert az app-csomag betoltese nelkul teszteljuk (a suite
mas tesztjei fake `app.services`-t hagyhatnak a sys.modules-ben) — kf/9 minta.
"""
import importlib.util
import json
import pathlib
import time

_P = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "konfbuild.py"
_spec = importlib.util.spec_from_file_location("konfbuild_under_test", _P)
kb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kb)


def _result(tmp_path, **kw):
    r = {"tenant": "copygo", "ok": True, "started_at": 100,
         "finished_at": 200, "count": 652, "v": "abc", "rc": 0, "note": ""}
    r.update(kw)
    (tmp_path / kb.RESULT_NAME).write_text(json.dumps(r), encoding="utf-8")
    return r


def _running(tmp_path, tenant="copygo", ts=1000):
    (tmp_path / kb.RUNNING_NAME).write_text("%s %d\n" % (tenant, ts), encoding="utf-8")


# --------------------------------------------------------------------------- #
# tenant-validacio
# --------------------------------------------------------------------------- #
def test_valid_tenant():
    assert kb.valid_tenant("copygo")
    assert kb.valid_tenant("4m-frigo")
    assert not kb.valid_tenant("")
    assert not kb.valid_tenant("a/b")          # utvonal-injekcio
    assert not kb.valid_tenant("a b")
    assert not kb.valid_tenant("x" * 65)


def test_ervenytelen_tenant_nem_ir_fajlt(tmp_path):
    ok, st = kb.request_build("../etc", dd=str(tmp_path))
    assert not ok and st["error"] == "bad_tenant"
    assert not list(tmp_path.iterdir())


# --------------------------------------------------------------------------- #
# keres
# --------------------------------------------------------------------------- #
def test_request_ures_konyvtarban(tmp_path):
    ok, st = kb.request_build("copygo", dd=str(tmp_path), now=1000)
    assert ok and st["pending"] and st["queued_at"] == 1000 and not st["running"]
    assert (tmp_path / kb.REQUEST_NAME).read_text().strip() == "copygo 1000"
    assert kb.read_request(str(tmp_path)) == ("copygo", 1000)


def test_masodik_keres_amig_sorban_all(tmp_path):
    kb.request_build("copygo", dd=str(tmp_path), now=1000)
    ok, st = kb.request_build("copygo", dd=str(tmp_path), now=1030)
    assert not ok and st["error"] == "pending"


def test_masik_tenant_kerese_sorban_all(tmp_path):
    kb.request_build("copygo", dd=str(tmp_path), now=1000)
    ok, st = kb.request_build("teslashop", dd=str(tmp_path), now=1010)
    assert not ok and st["error"] == "busy" and st["busy_with"] == "copygo"


# --------------------------------------------------------------------------- #
# futas-jelzo (kf/13a) — ez volt a lyuk az eles E2E-n
# --------------------------------------------------------------------------- #
def test_futas_kozben_nem_lehet_ujat_kerni(tmp_path):
    _running(tmp_path, "copygo", 1000)
    st = kb.state("copygo", dd=str(tmp_path), now=1100)
    assert st["running"] and st["started_at"] == 1000 and not st["pending"]
    ok, st2 = kb.request_build("copygo", dd=str(tmp_path), now=1100)
    assert not ok and st2["error"] == "running"
    assert not (tmp_path / kb.REQUEST_NAME).exists()


def test_masik_tenant_epul_eppen(tmp_path):
    _running(tmp_path, "teslashop", 1000)
    ok, st = kb.request_build("copygo", dd=str(tmp_path), now=1100)
    assert not ok and st["error"] == "busy" and st["busy_with"] == "teslashop"
    assert not st["running"]


def test_elakadt_futas_felulirhato(tmp_path):
    _running(tmp_path, "copygo", 1000)
    late = 1000 + kb.STALE_SEC + 1
    assert kb.state("copygo", dd=str(tmp_path), now=late)["stale"]
    ok, _ = kb.request_build("copygo", dd=str(tmp_path), now=late)
    assert ok


def test_elakadt_keres_felulirhato(tmp_path):
    kb.request_build("copygo", dd=str(tmp_path), now=1000)
    late = 1000 + kb.STALE_SEC + 1
    assert kb.state("copygo", dd=str(tmp_path), now=late)["stale"]
    ok, _ = kb.request_build("copygo", dd=str(tmp_path), now=late)
    assert ok


# --------------------------------------------------------------------------- #
# cooldown + eredmeny
# --------------------------------------------------------------------------- #
def test_cooldown_a_befejezett_build_utan(tmp_path):
    _result(tmp_path, finished_at=5000)
    ok, st = kb.request_build("copygo", dd=str(tmp_path), now=5050)
    assert not ok and st["error"] == "cooldown" and st["cooldown"] == kb.COOLDOWN_SEC - 50
    ok, _ = kb.request_build("copygo", dd=str(tmp_path), now=5000 + kb.COOLDOWN_SEC + 1)
    assert ok


def test_masik_tenant_eredmenye_nem_szamit_cooldownnak(tmp_path):
    _result(tmp_path, tenant="teslashop", finished_at=5000)
    ok, st = kb.request_build("copygo", dd=str(tmp_path), now=5050)
    assert ok and st["last"] is None


def test_eredmeny_visszaadasa(tmp_path):
    _result(tmp_path, finished_at=int(time.time()) - 10_000)
    st = kb.state("copygo", dd=str(tmp_path))
    assert st["last"]["count"] == 652 and st["cooldown"] == 0


# --------------------------------------------------------------------------- #
# robusztussag
# --------------------------------------------------------------------------- #
def test_hibas_fajlokkal_sem_dob(tmp_path):
    (tmp_path / kb.REQUEST_NAME).write_text("nem ervenyes tenant!!!", encoding="utf-8")
    (tmp_path / kb.RUNNING_NAME).write_text("", encoding="utf-8")
    (tmp_path / kb.RESULT_NAME).write_text("{ ez nem json", encoding="utf-8")
    st = kb.state("copygo", dd=str(tmp_path), now=1)
    assert st["pending"] is False and st["running"] is False and st["last"] is None
    assert kb.read_result(str(tmp_path)) is None


def test_state_nincs_fajl(tmp_path):
    assert kb.state("copygo", dd=str(tmp_path)) == {
        "pending": False, "running": False, "queued_at": 0, "started_at": 0,
        "stale": False, "busy_with": "", "last": None, "cooldown": 0}

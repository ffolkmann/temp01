"""kf/13: adminbol inditott index-build — keres-, futas- es eredmeny-fajl.

MIERT FAJL, ES NEM KOZVETLEN INDITAS: az index-buildet a HOST inditja
(`docker compose run --rm ... python -m app.search`), a futo API-konteneribol
dockert hivni nem lehet, a /cxsearch mount pedig read-only. A /app/data viszont
RW mount -> a kerest egy fajl hordozza, amit a `cx-index-build.path` systemd
unit figyel, es a `cx-index-build.sh` dolgoz fel (ugyanazzal a flock-kal, mint
az ejszakai cx-search-sync, tehat sosem fut ket build egyszerre).

    data/index_build.request  ->  "<tenant> <unix_ts>"   (sorban all)
    data/index_build.running  ->  "<tenant> <start_ts>"  (eppen epul)
    data/index_build.result   ->  {"tenant","ok","started_at","finished_at",
                                   "count","v","rc","note"}

kf/13a — a FUTAS-JELZO tanulsaga: a build ~7 perc, a keres-fajlt viszont a host
masodpercek alatt elviszi. Futas-jelzo nelkul az admin a build kozben "nincs
semmi"-t latott, es a pending-kapu nem vedett: az eles E2E-n ket build allt be
egymas utan. Ezert a script eloszor a .running-ot irja ki, es csak az EREDMENY
kiirasa utan torli.

A modul stdlib-only es tesztelheto: minden fuggveny kaphat sajat data_dir-t,
alapertelmezes a CX_DATA_DIR env, azutan a repo-relativ "data" (mint a
smartsearch.json feloldasa).
"""
import json
import os
import re
import time
from typing import Any

REQUEST_NAME = "index_build.request"
RUNNING_NAME = "index_build.running"
RESULT_NAME = "index_build.result"
COOLDOWN_SEC = 120     # ket kezi build kozott ennyit varunk (tenantonkent)
STALE_SEC = 1800       # ennyi utan a fuggo/futo allapotot elakadtnak tekintjuk
                       # (a mert futasido ~7 perc, tehat bo tartalek)

_SAFE = re.compile(r"^[a-z0-9_-]{1,64}$")


def data_dir(explicit: str | None = None) -> str:
    return explicit or os.environ.get("CX_DATA_DIR") or "data"


def valid_tenant(cid: Any) -> bool:
    return bool(_SAFE.match(str(cid or "").strip().lower()))


def _path(name: str, dd: str | None = None) -> str:
    return os.path.join(data_dir(dd), name)


def _read_pair(name: str, dd: str | None = None) -> tuple[str, int]:
    """"<tenant> <ts>" alaku jelzo-fajl. Hianyzo/ertelmetlen -> ("", 0)."""
    try:
        with open(_path(name, dd), encoding="utf-8") as f:
            raw = f.read(256)
    except OSError:
        return "", 0
    parts = raw.strip().split()
    if not parts or not valid_tenant(parts[0]):
        return "", 0
    ts = 0
    if len(parts) > 1:
        try:
            ts = int(float(parts[1]))
        except (TypeError, ValueError):
            ts = 0
    return parts[0].strip().lower(), ts


def read_request(dd: str | None = None) -> tuple[str, int]:
    """A sorban allo keres: (tenant, unix_ts)."""
    return _read_pair(REQUEST_NAME, dd)


def read_running(dd: str | None = None) -> tuple[str, int]:
    """Az eppen futo build: (tenant, start_ts)."""
    return _read_pair(RUNNING_NAME, dd)


def read_result(dd: str | None = None) -> dict[str, Any] | None:
    """A legutobbi befejezett build eredmenye (globalis, egy fajl)."""
    try:
        with open(_path(RESULT_NAME, dd), encoding="utf-8") as f:
            r = json.load(f)
    except (OSError, ValueError):
        return None
    return r if isinstance(r, dict) else None


def state(cid: Any, dd: str | None = None, now: float | None = None) -> dict[str, Any]:
    """A tenant build-allapota az adminnak. Sosem dob kivetelt.

    pending = sorban all, running = eppen epul, busy_with = MAS tenant foglalja.
    """
    ts_now = int(now if now is not None else time.time())
    cid = str(cid or "").strip().lower()
    pend, pts = read_request(dd)
    run, rts = read_running(dd)
    res = read_result(dd) or {}
    mine_p = bool(pend) and pend == cid
    mine_r = bool(run) and run == cid
    other = (run if (run and not mine_r) else (pend if (pend and not mine_p) else ""))
    out: dict[str, Any] = {
        "pending": mine_p,
        "running": mine_r,
        "queued_at": pts if mine_p else 0,
        "started_at": rts if mine_r else 0,
        "stale": bool((mine_p and pts and ts_now - pts > STALE_SEC)
                      or (mine_r and rts and ts_now - rts > STALE_SEC)),
        "busy_with": other,
        "last": res if str(res.get("tenant") or "").lower() == cid else None,
        "cooldown": 0,
    }
    if out["last"]:
        fin = int(out["last"].get("finished_at") or 0)
        out["cooldown"] = max(0, COOLDOWN_SEC - (ts_now - fin)) if fin else 0
    return out


def request_build(cid: Any, dd: str | None = None,
                  now: float | None = None) -> tuple[bool, dict[str, Any]]:
    """Kiirja a keres-fajlt. -> (elfogadtuk?, allapot). A fajlirast a hivo fogja el."""
    ts_now = int(now if now is not None else time.time())
    cid = str(cid or "").strip().lower()
    if not valid_tenant(cid):
        return False, {"error": "bad_tenant"}
    st = state(cid, dd, ts_now)
    if not st["stale"]:
        if st["running"]:
            st["error"] = "running"
            return False, st
        if st["pending"]:
            st["error"] = "pending"
            return False, st
    if st["busy_with"]:
        st["error"] = "busy"
        return False, st
    if st["cooldown"] > 0:
        st["error"] = "cooldown"
        return False, st
    p = _path(REQUEST_NAME, dd)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("%s %d\n" % (cid, ts_now))
    os.replace(tmp, p)   # atomos: a path unit sosem lat felig kiirt fajlt
    return True, state(cid, dd, ts_now)

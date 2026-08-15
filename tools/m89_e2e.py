#!/usr/bin/env python3
"""m89 éles E2E: a záró-link kapu.

A HOSTON fut (a publikus domain hairpin miatt 127.0.0.1:8095).
Log-ellenőrzés PILLANATKÉP-DIFF-fel (m86/1 tanulsága: a --since ablakba
belelóg az előző eset sora, attól a negatív esetek hamisan buknak).
Futásonként EGYEDI session-id (az újrahasznált sid transcriptje a m24-es
embed-prependen át átszennyezi a teszteket).
"""
import json
import subprocess
import sys
import time
import urllib.request
import uuid

API = "http://127.0.0.1:8095/chat"
MARK = "További találatok a webáruházban"
RUN = uuid.uuid4().hex[:8]

# (tenant, kérdés, elvárt-link?, címke)
CASES = [
    # --- TILTANI kell (ez a m89 lényege) ---
    ("kellegyszerszam", "Milyen fizetési módok vannak?", False, "policy / Feco eredeti esete"),
    ("notebookstore", "Mennyi a szállítási idő?", False, "policy / szallitas"),
    ("notebookstore", "Milyen szállítási módok vannak?", False, "policy / szallitasi modok"),
    ("fishingoutlet", "Szia", False, "koszones"),
    ("fishingoutlet", "A rendelésem után érdeklődöm", False, "rendeles-statusz"),
    ("notebookstore", "Nyitvatartási idö üzletben mettöl meddig van?", False, "bolt-info"),
    # --- ENGEDNI kell (regresszió-őrzés) ---
    ("notebookstore", "melyik a legolcsóbb notebook?", True, "termek / szuperlativusz"),
    ("teslashop", "Melyik a legolcsóbb raktáron lévő telefontartó?", True, "termek / m86 kapu"),
    ("kellegyszerszam", "Csavarhúzó készlet", True, "termek / m86-1 esete"),
    ("kellegyszerszam", "UV álló kötegelőt keresek", True, "termek / hosszu farok"),
    ("notebookstore", "Milyen lézernyomtatóitok vannak?", True, "termek / kategoria"),
]


def gate_lines():
    p = subprocess.run(["docker", "logs", "--since", "15m", "chatbot-api-prod"],
                       capture_output=True, text=True)
    blob = (p.stdout or "") + (p.stderr or "")
    return [ln for ln in blob.splitlines() if "m89 link gate" in ln]


def ask(client, msg):
    before = gate_lines()
    sid = "m89-%s-%s" % (RUN, uuid.uuid4().hex[:6])
    body = json.dumps({"client_id": client, "session_id": sid, "message": msg},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    reply = data.get("reply", "")
    time.sleep(2.0)
    new = gate_lines()[len(before):]   # PILLANATKEP-DIFF
    return reply, new


def main():
    ok = 0
    for tenant, q, want_link, label in CASES:
        try:
            reply, gl = ask(tenant, q)
        except Exception as e:  # noqa: BLE001
            print("  HIBA  [%s] %-45s -> %s" % (tenant, q[:45], e))
            continue
        has = MARK in reply
        good = (has == want_link)
        # a tiltott esetnél legyen kapu-log; az engedettnél NE legyen
        gate_ok = (bool(gl) if not want_link else not gl)
        mark = "OK  " if (good and gate_ok) else "BUKO"
        if good and gate_ok:
            ok += 1
        why = gl[0].split("m89 link gate:")[-1].strip()[:48] if gl else "-"
        print("  %s [%-15s] %-42s link=%-5s elvart=%-5s | %s"
              % (mark, tenant, q[:42], has, want_link, why))
    print("\nm89 E2E: %d/%d" % (ok, len(CASES)))
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())

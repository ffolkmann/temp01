"""Onboarding / funkcio-teszt a CX chatbothoz + ugyfelnek adhato HTML riport.

Hasznalat (a VPS-en, api-kontenert exec-elve):
    docker exec -i chatbot-api-prod python - < tools/onboarding_test.py            # notebookstore
    docker exec -i chatbot-api-prod python - < tools/onboarding_test.py -- copygo  # masik tenant

Kimenet: konzol PASS/FAIL tabla + /app/data/onboarding_report_<client>_<ts>.html
(a data bind-mount reven a hoston: /docker/chatbot-prod/data/). A riport
ugyfelnek szolo magyar osszefoglalot ad (kerdes, valasz-reszlet, link, statusz).

Tenant-specifikus keszlet a TESTS dict-ben; ismeretlen tenantra a GENERIC
keszlet fut. Elvart arakat NE egess be — dinamikus ar-minimum a Qdrantbol
(qdrant_min), a tobbi assert a valasz SZERKEZETET ellenorzi (link-vegzodes,
kulcsszo).
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

BASE = "http://127.0.0.1:8000"
REPORT_DIR = os.environ.get("ONB_REPORT_DIR", "/app/data")


def chat(client, msg, sid, history=None):
    body = {"client_id": client, "session_id": sid, "message": msg}
    if history:
        body["history"] = history
    req = urllib.request.Request(BASE + "/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=150).read().decode()).get("reply", "")


def link(r):
    m = re.search(r"\]\((https?://[^)]+)\)\s*$", (r or "").strip())
    return m.group(1) if m else ""


def qdrant_min(client, must_extra):
    """Dinamikus ar-minimum a Qdrantbol (available=true + extra must)."""
    body = {"filter": {"must": [
        {"key": "client_id", "match": {"value": client}},
        {"key": "available", "match": {"value": True}},
    ] + must_extra}, "limit": 1000, "with_payload": ["price"], "with_vector": False}
    req = urllib.request.Request("http://qdrant:6333/collections/cx_chatbot_v2/points/scroll",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    pts = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())["result"]["points"]
    prices = []
    for p in pts:
        try:
            v = float(p["payload"].get("price") or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            prices.append(int(v))
    return min(prices) if prices else None


def hu(n):
    return f"{n:,}".replace(",", " ") if n else ""


class Runner:
    """Teszt-futtato: konzol-kimenet + riport-sorok gyujtese."""

    def __init__(self, client):
        self.client = client
        self.rows = []  # (cat, label, ok, question, answer, note)
        # futasonkent egyedi session-prefix: az ujrahasznalt session-id
        # DB-transcriptje a m24-es embed-prependen at atszennyezne a teszteket
        self.sid_prefix = datetime.now().strftime("%H%M%S") + "-"

    def ask(self, msg, sid, history=None, sleep=2):
        r = chat(self.client, msg, self.sid_prefix + sid, history)
        if sleep:
            time.sleep(sleep)
        return r

    def check(self, cat, label, cond, question, answer, note=""):
        ok = bool(cond)
        self.rows.append((cat, label, ok, question, answer or "", note))
        print("%-3s %-40s %s  %s" % (cat, label, "PASS" if ok else "FAIL", note[:70]))
        return ok


def run_notebookstore(R):
    c = R.client
    min_uzleti = qdrant_min(c, [{"key": "usage", "match": {"any": ["uzleti"]}}])
    min_asus_uz = qdrant_min(c, [{"key": "usage", "match": {"any": ["uzleti"]}},
                                 {"key": "brand", "match": {"any": ["Asus", "ASUS", "asus"]}}])
    q1 = "Melyik a legolcsóbb üzleti notebook?"
    r1 = R.ask(q1, "onb-1")
    R.check("A", "Készlet-szuperlatívusz + szűrő-link (üzleti)",
            (hu(min_uzleti) in r1) and link(r1).endswith("felhasznalas-jellege:uzleti"),
            q1, r1, "elvárt min. ár: %s Ft" % hu(min_uzleti))
    h = [{"role": "user", "content": q1}, {"role": "assistant", "content": r1}]
    q2 = "és ASUS márkájúak közül?"
    r2 = R.ask(q2, "onb-1", h)
    R.check("B", "Follow-up márka-öröklés (ASUS)",
            (hu(min_asus_uz) in r2) and link(r2).endswith("/asus"),
            q2, r2, "elvárt min. ár: %s Ft" % hu(min_asus_uz))
    h += [{"role": "user", "content": q2}, {"role": "assistant", "content": r2}]
    q3 = "és Lenovo?"
    r3 = R.ask(q3, "onb-1", h)
    R.check("C", "Lánc 2. szint (Lenovo)", "Lenovo" in r3 and link(r3).endswith("/lenovo"), q3, r3)
    h += [{"role": "user", "content": q3}, {"role": "assistant", "content": r3}]
    q4 = "és mennyibe kerül a szállítás?"
    r4 = R.ask(q4, "onb-1", h)
    R.check("D", "Szállítási infó termékes beszélgetés után", ("DPD" in r4 or "MPL" in r4), q4, r4)

    q5 = "Melyik a legolcsóbb gamer laptop?"
    r5 = R.ask(q5, "onb-2")
    R.check("E", "Felhasználás-szűrés (gamer)", link(r5).endswith("felhasznalas-jellege:gamer"), q5, r5)
    q6 = "Melyik a legolcsóbb 17 colos laptop?"
    r6 = R.ask(q6, "onb-3")
    R.check("F", "Kijelzőméret-szűrés (17\" → 17,3\")", link(r6).endswith("kijelzo-meret:173"), q6, r6)
    q7 = "Melyik a legolcsóbb táska 17\"-os laptophoz?"
    r7 = R.ask(q7, "onb-4")
    R.check("G", "Táska colméret-szűrés", "maximalis-notebook-meret:170" in link(r7), q7, r7)
    q8 = "Melyik a legolcsóbb fekete hátizsák laptopnak?"
    r8 = R.ask(q8, "onb-5")
    R.check("H", "Táska-típus szűrés (hátizsák)", "taska-tipusa:hatizsak" in link(r8), q8, r8)

    q9 = "Melyik a legolcsóbb Acer notebook raktárról?"
    r9 = R.ask(q9, "onb-6")
    R.check("I", "Direkt márka + monitor-zaj szűrés",
            "Acer" in r9 and "uj-notebook-c100/acer" in link(r9) and "onitor" not in r9, q9, r9)
    q10 = "HP toner árak?"
    r10 = R.ask(q10, "onb-7")
    R.check("J", "Nem-laptop márka (HP toner)",
            "HP" in r10 and ("tintapatron-toner" in link(r10) or "termek-kereses" in link(r10)), q10, r10)
    q11 = "Windows 11-es laptopot keresek, mit ajánlasz?"
    r11 = R.ask(q11, "onb-8")
    R.check("K", "Windows-guard (a 11 nem colméret)", "kijelzo-meret" not in link(r11), q11, r11)

    q12 = "Mennyibe kerül a szállítás?"
    r12 = R.ask(q12, "onb-9")
    R.check("L", "Tudásbázis: szállítási díjak", ("DPD" in r12 or "MPL" in r12) and "1 590" in r12, q12, r12)
    q13 = "Mennyi garancia van a laptopokra?"
    r13 = R.ask(q13, "onb-10")
    R.check("M", "Tudásbázis: garancia", "garanci" in r13.lower(), q13, r13)
    q14 = "MSI laptopot néznék, mi a legolcsóbb?"
    r14 = R.ask(q14, "onb-11")
    R.check("N", "MSI márka (slug-alias)", "MSI" in r14, q14, r14)
    q15 = ("ne mez? Asus Vivobook Go 15 Notebook (E1504FA-BQ2345) - 15.6\" FullHD, "
           "AMD Ryzen 3-7320U, 8GB RAM, 512GB SSD")
    r15 = R.ask(q15, "onb-12", sleep=0)
    R.check("O", "Beillesztett terméknév felismerése", "kijelzo-meret" not in link(r15), q15, r15)


def run_generic(R):
    c = R.client
    q1 = "Melyik a legolcsóbb termék, ami kapható nálatok?"
    r1 = R.ask(q1, "onbg-1")
    R.check("G1", "Ár-szuperlatívusz válaszol (Ft-ár)", "Ft" in r1, q1, r1)
    R.check("G2", "Záró link jelen", bool(link(r1)), q1, r1)
    h = [{"role": "user", "content": q1}, {"role": "assistant", "content": r1}]
    q2 = "és mennyibe kerül a szállítás?"
    r2 = R.ask(q2, "onbg-1", h)
    R.check("G3", "Szállítási infó follow-upban", "szállít" in r2.lower(), q2, r2)
    q3 = "Milyen fizetési módok vannak?"
    r3 = R.ask(q3, "onbg-2", sleep=0)
    R.check("G4", "Tudásbázis: fizetési módok", len(r3) > 40, q3, r3)


TESTS = {"notebookstore": run_notebookstore}


def write_report(R):
    npass = sum(1 for r in R.rows if r[2])
    total = len(R.rows)
    ts = datetime.now()
    rows_html = []
    for cat, label, ok, q, a, note in R.rows:
        badge = ('<span class="ok">&#10003; Megfelelt</span>' if ok
                 else '<span class="bad">&#10007; Ellen\u0151rz\u00e9st ig\u00e9nyel</span>')
        lk = link(a)
        excerpt = re.sub(r"\[([^\]]*)\]\((https?://[^)]+)\)", r"\1", a).strip()
        excerpt = (excerpt[:260] + "…") if len(excerpt) > 260 else excerpt
        lk_html = '<div class="lnk">Ajánlott link: <a href="%s">%s</a></div>' % (
            html.escape(lk), html.escape(lk.replace("https://", ""))) if lk else ""
        note_html = '<div class="note">%s</div>' % html.escape(note) if note else ""
        rows_html.append(
            '<tr><td class="cat">%s</td><td><div class="q">%s</div>'
            '<div class="a">%s</div>%s%s</td><td class="st">%s</td></tr>' % (
                html.escape(cat), html.escape(q), html.escape(excerpt), lk_html, note_html, badge))
    score_cls = "ok" if npass == total else ("warn" if npass >= total - 2 else "bad")
    doc = """<!DOCTYPE html><html lang="hu"><head><meta charset="utf-8">
<title>CX Chatbot — Onboarding teszt riport: %(client)s</title>
<style>
body{font-family:'Segoe UI',Arial,sans-serif;margin:0;background:#f4f6f8;color:#1c2733}
.wrap{max-width:880px;margin:24px auto;background:#fff;border-radius:12px;
box-shadow:0 2px 12px rgba(0,0,0,.08);overflow:hidden}
header{background:#0f2740;color:#fff;padding:26px 34px}
header h1{margin:0 0 4px;font-size:21px}header .sub{opacity:.8;font-size:13px}
.score{padding:18px 34px;font-size:16px;border-bottom:1px solid #e6eaee}
.score b{font-size:22px}.score .ok{color:#1a8a4a}.score .warn{color:#c07b00}.score .bad{color:#c22}
table{width:100%%;border-collapse:collapse;font-size:13.5px}
td{padding:12px 14px;border-bottom:1px solid #eef1f4;vertical-align:top}
td.cat{width:34px;font-weight:700;color:#5b6b7c}
td.st{width:150px;white-space:nowrap}
.q{font-weight:600;margin-bottom:5px}
.a{color:#42505e;line-height:1.45}
.lnk{margin-top:5px;font-size:12.5px}.lnk a{color:#0b62b8;text-decoration:none}
.note{margin-top:4px;font-size:12px;color:#7b8794}
.ok{color:#1a8a4a;font-weight:700}.bad{color:#c22;font-weight:700}
footer{padding:16px 34px;font-size:12px;color:#7b8794}
</style></head><body><div class="wrap">
<header><h1>CX Chatbot — Onboarding teszt riport</h1>
<div class="sub">Webáruház: <b>%(client)s</b> &nbsp;•&nbsp; Dátum: %(date)s &nbsp;•&nbsp; Éles rendszeren futtatva</div></header>
<div class="score">Eredmény: <b class="%(scls)s">%(npass)d / %(total)d</b> teszteset megfelelt</div>
<table><tbody>%(rows)s</tbody></table>
<footer>A tesztek a chatbot éles API-ján futottak, valós termék- és tudásbázis-adatokkal.
Az ár-elvárások a futás pillanatában érvényes készletadatból számolódnak.
Codexpress — CX AI Chatbot • codexpress.hu</footer>
</div></body></html>""" % {
        "client": html.escape(R.client), "date": ts.strftime("%Y-%m-%d %H:%M"),
        "npass": npass, "total": total, "rows": "".join(rows_html), "scls": score_cls,
    }
    path = os.path.join(REPORT_DIR, "onboarding_report_%s_%s.html" % (R.client, ts.strftime("%Y%m%d-%H%M")))
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path, npass, total


if __name__ == "__main__":
    client = sys.argv[-1] if len(sys.argv) > 1 and not sys.argv[-1].endswith(".py") and sys.argv[-1] != "--" else "notebookstore"
    print("=== CX onboarding teszt: %s ===" % client)
    R = Runner(client)
    TESTS.get(client, run_generic)(R)
    path, npass, total = write_report(R)
    print()
    print("OSSZESEN: %d/%d PASS" % (npass, total))
    print("RIPORT:", path)
    sys.exit(0 if npass == total else 1)

"""m84 PATCH: egyseges keszlet-jel a sync payloadban.

A Qdrant `available_only` szuroje CSAK a bool `available` mezore megy, a `stock`
viszont STRING payload (nincs range-szuro rajta) -> SR/Unas tenantoknal a
m60/m64/m73 keszlet-agai nemak voltak (mert available=None). Ha a platform nem
ad available-t, szarmaztassuk a szamszeru stockbol -- ugyanazzal a logikaval,
amit a `superlative.availability()` kliens-oldalon mar hasznal.

Horgonyzott, sor-szintu csere assert-tel. Futtatas a repo gyokerebol:
  python3 tools/m84_patch.py
"""
import sys

CHANGED = []


def patch_models():
    p = "app/sync/models.py"
    s = open(p, encoding="utf-8").read()

    helper = '''def derive_available(available, stock_str: str = ""):
    """m84: EGYSEGES keszlet-jel — a Qdrant `available_only` szuroje csak a bool
    `available` mezore megy, a `stock` viszont string payload (range-szuro nincs
    rajta). Ha a platform nem ad available-t (Shoprenter/Unas), a szamszeru
    stockbol szarmaztatjuk — ugyanaz a szabaly, mint a superlative.availability().
    Ures vagy nem szamszeru stock -> None: NEM irunk mezot (nincs keszlet-adat).
    """
    if available is not None:
        return bool(available)
    raw = str(stock_str or "").replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw) > 0
    except ValueError:
        return None


def build_payload('''
    anchor = "def build_payload("
    assert s.count(anchor) == 1, ("models: build_payload horgony", s.count(anchor))
    assert "def derive_available(" not in s, "models: mar patchelve"
    s = s.replace(anchor, helper)

    lines = s.split("\n")
    idx = [i for i, ln in enumerate(lines)
           if ln.strip().startswith("if p.available is not None:")]
    assert len(idx) == 1, ("models: if-horgony", idx)
    i = idx[0]
    assert lines[i + 1].strip() == 'payload["available"] = p.available', lines[i + 1]
    lines[i] = "    _av84 = derive_available(p.available, p.stock_str)  # m84"
    lines[i + 1] = '    if _av84 is not None:\n        payload["available"] = _av84'
    open(p, "w", encoding="utf-8").write("\n".join(lines))
    CHANGED.append(p)


def patch_engine():
    p = "app/sync/engine.py"
    s = open(p, encoding="utf-8").read()
    assert "derive_available" not in s, "engine: mar patchelve"

    lines = s.split("\n")
    idx = [i for i, ln in enumerate(lines)
           if ln.strip().startswith("if p.available is not None:")]
    assert len(idx) == 1, ("engine: if-horgony", idx)
    i = idx[0]
    assert lines[i + 1].strip() == 'payload["available"] = p.available', lines[i + 1]
    lines[i] = ("    _av84 = derive_available(p.available, p.stock_str)  # m84: "
                "SR/Unas stockbol is legyen bool keszlet-jel")
    lines[i + 1] = '    if _av84 is not None:\n        payload["available"] = _av84'
    s = "\n".join(lines)

    fn = 'def _ps_payload(p) -> dict:'
    assert s.count(fn) == 1, "engine: _ps_payload horgony"
    doc_end = s.index(fn)
    # lokalis import a fuggveny elejere (a modul-szintu import-kort elkerulve)
    marker = 'payload = {"price": p.price, "text": p.text, "ps_hash": p.ps_hash_str}'
    assert s.count(marker) == 1, "engine: payload-dict horgony"
    s = s.replace(marker,
                  "from app.sync.models import derive_available  # m84\n    " + marker)
    assert doc_end >= 0
    open(p, "w", encoding="utf-8").write(s)
    CHANGED.append(p)


patch_models()
patch_engine()
print("PATCHELVE:", ", ".join(CHANGED))

# gyors on-ellenorzes: a szarmaztatas logikaja
sys.path.insert(0, ".")
from app.sync.models import derive_available  # noqa: E402

cases = [(None, "3", True), (None, "0", False), (None, "", None), (None, "abc", None),
         (True, "0", True), (False, "5", False), (None, "1,5", True), (None, " 2 ", True)]
bad = [c for c in cases if derive_available(c[0], c[1]) is not c[2]]
print("derive_available onteszt: %d/%d" % (len(cases) - len(bad), len(cases)),
      ("HIBA: %s" % bad) if bad else "OK")

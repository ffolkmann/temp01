"""AI-szovegiro: a szuro/boost feltetelek SOSEM valtozhatnak."""
import importlib.util as _ilu
import pathlib as _pl

_P = _pl.Path(__file__).resolve().parents[1] / "app" / "services" / "konftext.py"
_spec = _ilu.spec_from_file_location("konftext_k3", _P)
konftext = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(konftext)

CFG = {
    "ui": {"title": "Nyomtato-valaszto", "unit": "nyomtato"},
    "questions": [{
        "id": "szin", "title": "Szinkezeles - melyik felel meg?", "type": "single",
        "options": [
            {"id": "szines", "label": "Szines",
             "filter": [{"param": "szinkezeles", "op": "eq", "value": "Szines"}]},
            {"id": "mono", "label": "Mono",
             "filter": [{"param": "szinkezeles", "op": "eq", "value": "Mono"}],
             "boost": [{"param": "technologia", "op": "eq", "value": "Lezer", "w": 20}]},
        ]}]
}


def test_prompt_tartalmazza_a_felteteleket():
    p = konftext.build_user_prompt(CFG)
    assert "szinkezeles = Mono" in p
    assert "elorebb sorol" in p and "technologia = Lezer" in p
    assert "id=mono" in p


def test_parse_es_apply_nem_nyul_a_feltetelekhez():
    resp = ('```json\n{"questions":[{"id":"szin","title":"Kell szines nyomtatas?",'
            '"help":"Reszletes magyarazat a dontesrol.",'
            '"options":[{"id":"mono","label":"Eleg a fekete-feher","sub":"olcsobb"}]}]}\n```')
    texts = konftext.parse_result(resp, CFG)
    out = konftext.apply_texts(CFG, texts)
    q = out["questions"][0]
    assert q["title"] == "Kell szines nyomtatas?"
    assert q["help"].startswith("Reszletes")
    assert q["options"][1]["label"] == "Eleg a fekete-feher"
    assert q["options"][1]["sub"] == "olcsobb"
    # a feltetelek bitre ugyanazok
    assert q["options"][1]["filter"] == CFG["questions"][0]["options"][1]["filter"]
    assert q["options"][1]["boost"] == CFG["questions"][0]["options"][1]["boost"]
    # az erintetlen opcio cimkeje marad
    assert q["options"][0]["label"] == "Szines"
    # az eredeti config valtozatlan (masolaton dolgozunk)
    assert CFG["questions"][0]["title"] == "Szinkezeles - melyik felel meg?"


def test_ismeretlen_id_kiesik():
    resp = '{"questions":[{"id":"HAMIS","title":"x","options":[{"id":"y","label":"z"}]}]}'
    assert konftext.parse_result(resp, CFG) == {}


def test_hibas_valasz_ures():
    assert konftext.parse_result("nem json", CFG) == {}
    assert konftext.parse_result("", CFG) == {}
    assert konftext.parse_result(None, CFG) == {}


def test_hosszkorlatok():
    resp = ('{"questions":[{"id":"szin","title":"' + "T" * 400 + '","help":"' + "H" * 2000 +
            '","options":[{"id":"mono","label":"' + "L" * 400 + '"}]}]}')
    t = konftext.parse_result(resp, CFG)["szin"]
    assert len(t["title"]) == konftext.MAX_TITLE
    assert len(t["help"]) == konftext.MAX_HELP
    assert len(t["options"]["mono"]["label"]) == konftext.MAX_LABEL

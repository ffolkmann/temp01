"""m82d: a facets-szures a NEM-szuperlativusz termek-kerdesekre is fut.

Miert kell: elomeres (tools/m82d_nonsuper.py, notebookstore, 12 kerdes) szerint a mai
szuretlen top-24-bol atlagosan CSAK 20% felelt meg annak a bolti szuronek, amit a kerdes
megnevezett -- a "gamer laptop" es az "otthoni notebook" kerdesnel 0/24. A modell tehat
olyan halmazbol valaszolt, amiben egyetlen megfelelo termek sem volt.

Amit ez a fajl rogzit:
  1. plain (nem-szuperlativusz) termek-kerdes -> FUT a facets-szures, a pool merete
     a megszokott top-k (nem szelesitunk, csak a TARTALMAT csereljuk)
  2. plain modban a KB/doksi-talalatok a poolban MARADNAK (vegyes kerdes vedelme)
  3. policy-kerdes -> a facets-szures SOHA nem fut (a `facets` must kizarna a KB-t)
  4. ures szurt talalat -> valtozatlan pool (fail-safe)
  5. szuperlativusz -> valtozatlan m82b viselkedes: szeles pool + TELJES csere

TESZT-GOTCHA (dragan tanultuk, 2026-08-05): a sys.modules-t MODUL-SZINTEN piszkalni
tilos. Az elso valtozat import-idoben (= collection kozben) purge-olta az `app.*`-ot,
amivel ket masik tesztfajl collectionjet torte el (test_stream, test_webdoc_order) --
azok a suite altal korabban betoltott app-modulokra epulnek. Ezert a fake-elt kornyezet
CONTEXT MANAGERBEN el, es a finally mindent visszaallit.

A retrieval.py app.core.* fuggosegeit fake modulok fedik; a facetdict / policy_filter /
superlative VALODI -- a kapu-logikat epp azokkal egyutt merjuk.
"""

import asyncio
import contextlib
import sys
import types

CAT = "Laptop, Notebook > UJ Notebook"
CATALOG = [CAT, "Monitor, Projektor, TV > Monitor"]

FMAP = {
    "categories": {
        "uj-notebook": {
            "url": "/laptop-notebook/uj-notebook-c100",
            "facets": {
                "felhasznalas-jellege": {"gamer": 90, "uzleti": 200, "otthoni": 150},
                "memoria-meret": {"16gb": 300, "32gb": 120},
            },
        }
    }
}


def _prod(i, tags):
    return {
        "id": "p%d" % i,
        "score": 0.9 - i / 1000.0,
        "payload": {
            "type": "product", "name": "Gep %d" % i, "price": 100000 + i * 1000,
            "sku": "SKU%d" % i, "category": CAT, "facets": list(tags),
            "url": "/termek/p%d" % i, "available": True,
        },
    }


def _doc(i):
    return {
        "id": "d%d" % i, "score": 0.5,
        "payload": {"type": "doc", "text": "Szallitasi es atveteli modok", "category": ""},
    }


POOL_PLAIN = [_prod(1, []), _prod(2, []), _prod(3, ["felhasznalas-jellege:uzleti"]), _doc(9)]
POOL_GAMER = [_prod(11, ["felhasznalas-jellege:gamer"]), _prod(12, ["felhasznalas-jellege:gamer"])]


class _FakeQ:
    def __init__(self, responder):
        self.calls = []
        self._r = responder

    async def search(self, vector, client_id, limit=30, product_only=True,
                     available_only=False, usage=None, extra_must=None):
        call = {"limit": limit, "product_only": product_only,
                "available_only": available_only, "extra_must": list(extra_must or [])}
        self.calls.append(call)
        return list(self._r(call))

    async def facet_values(self, key, client_id):
        return list(CATALOG)

    def facet_calls(self):
        """A `facets` must-feltetelt tartalmazo keresesek."""
        return [c for c in self.calls
                if any(str(m.get("key")) == "facets" for m in c["extra_must"])]


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


@contextlib.contextmanager
def _sandbox(responder):
    """Fake app.core.* + fake rerank/paramextract/linkfacet, majd friss retrieval-import.

    A sys.modules `app.*` reszet a belepeskor elmentjuk es a kilepeskor VISSZAALLITJUK --
    a suite tobbi fajlja a sajat betoltott app-moduljaira epul.
    """
    snap = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in list(snap):
        del sys.modules[k]
    q = _FakeQ(responder)

    async def _embed(_s):
        return [0.0, 0.1]

    class _S:
        retrieval_top_k = 24
        context_top_n = 8

    try:
        _mod("app.core")
        _mod("app.core.embeddings", embed_query=_embed)
        _mod("app.core.qdrant", get_qdrant=lambda: q)
        _mod("app.core.settings", get_settings=lambda: _S())
        _mod("app.services.rerank",
             rerank=lambda message, hits, page_url="", page_url_norm="", top_n=8: list(hits)[:top_n])
        _mod("app.services.paramextract",
             detect_constraints=lambda m: {},
             build_filter_conditions=lambda c, *a, **k: [])
        _mod("app.services.linkfacet", load_map=lambda cid: FMAP)
        _mod("app.services.query_cleanup", product_query_cleanup=lambda s: s)

        import app.services.retrieval as retr
        retr._catalog_cache.clear()
        yield retr, q
    finally:
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(snap)


def _responder(call):
    if any(str(m.get("key")) == "facets" for m in call["extra_must"]):
        return POOL_GAMER
    if call["available_only"]:
        return POOL_GAMER
    return POOL_PLAIN


def _empty_responder(call):
    if any(str(m.get("key")) == "facets" for m in call["extra_must"]):
        return []
    if call["available_only"]:
        return []
    return POOL_PLAIN


def test_plain_kerdes_facets_szurt_poolt_kap():
    """1+2: sima termek-kerdesnel fut a szures, es a doksi-talalat bennmarad."""
    with _sandbox(_responder) as (retr, q):
        msg = "Gamer laptopot szeretnek venni"
        out, _score, _mode = asyncio.run(retr.retrieve(msg, msg, "notebookstore"))

        fc = q.facet_calls()
        assert len(fc) == 1, "pontosan egy facets-szurt keresesnek kell futnia"
        assert fc[0]["limit"] == 24, "plain modban a pool merete a megszokott top-k marad"

        ids = [h["id"] for h in out]
        assert "p11" in ids and "p12" in ids, "a szurt (gamer) termekek bekerulnek"
        assert "p1" not in ids and "p2" not in ids, "a nem-megfelelo termekek kiesnek"
        assert "d9" in ids, "a KB/doksi-talalat plain modban a poolban marad"


def test_policy_kerdesnel_nincs_facet_szures():
    """3: a policy-ut erintetlen -- a facets must kizarna a KB-chunkokat."""
    with _sandbox(_responder) as (retr, q):
        msg = "Mennyibe kerul a szallitas?"
        out, _score, _mode = asyncio.run(retr.retrieve(msg, msg, "notebookstore"))

        assert q.facet_calls() == [], "policy-kerdesre soha nem futhat facets-szures"
        assert [h["id"] for h in out] == ["d9"], "policy-kerdesnel csak a doksi marad"


def test_ures_szurt_talalat_fail_safe():
    """4: ha a szures 0 talalatot ad, a pool valtozatlan."""
    with _sandbox(_empty_responder) as (retr, q):
        msg = "Gamer laptopot szeretnek venni"
        out, _score, _mode = asyncio.run(retr.retrieve(msg, msg, "notebookstore"))

        assert len(q.facet_calls()) == 2, "kategoria-kapuval, majd anelkul is probal"
        ids = [h["id"] for h in out]
        assert "p1" in ids and "d9" in ids, "ures szures -> valtozatlan pool"


def test_szuperlativusz_valtozatlan_m82b_viselkedes():
    """5: szeles pool + TELJES csere (a doksi is kiesik, ott ar szerint rendezunk)."""
    with _sandbox(_responder) as (retr, q):
        msg = "Melyik a legolcsobb gamer laptop?"
        out, _score, _mode = asyncio.run(retr.retrieve(msg, msg, "notebookstore"))

        fc = q.facet_calls()
        assert fc and fc[0]["limit"] == 120, "szuperlativusznal szeles pool (WIDE_LIMIT)"
        assert out, "az ar-rendezett kontextus nem lehet ures"
        assert all((h.get("payload") or {}).get("type") == "product" for h in out), \
            "szuperlativusznal a pool teljesen cserelodik (csak termek)"

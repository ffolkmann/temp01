# -*- coding: utf-8 -*-
"""m117: zaro kereso-link keresoszava a katalogusban (lexmatch.term_in_catalog)."""
import importlib.util
import os
import time

_P = os.path.join(os.path.dirname(__file__), "..", "app", "services", "lexmatch.py")
_spec = importlib.util.spec_from_file_location("lexmatch_m117", _P)
lx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lx)

CAT = [(1, lx.fold("Dell Latitude 5540 notebook 15,6\""), "", True),
       (2, lx.fold("Lenovo ThinkVision T34WD-40 monitor"), "", True),
       (3, lx.fold("Horgászfotel karfával"), "", True)]


def _with_cat(cid="t117"):
    lx._cache[cid] = (time.monotonic(), CAT)
    lx._TERM_CACHE.clear()
    return cid


def test_junk_term_rejected():
    cid = _with_cat()
    assert lx.term_in_catalog(cid, "Cégünk számára") is False
    assert lx.term_in_catalog(cid, "Vannak akciós") is False
    assert lx.term_in_catalog(cid, "Utca") is False


def test_product_term_kept():
    cid = _with_cat()
    assert lx.term_in_catalog(cid, "Dell notebook") is True
    assert lx.term_in_catalog(cid, "monitort") is True        # toldalek
    assert lx.term_in_catalog(cid, "horgászfotelt") is True   # toldalekos osszetett szo
    assert lx.term_in_catalog(cid, "Cégünk Dell") is True     # eleg egy szo


def test_no_content_tokens_true():
    cid = _with_cat()
    assert lx.term_in_catalog(cid, "a az") is True


def test_catalog_missing_fail_open():
    lx._cache.pop("nincs_ilyen_m117", None)
    lx._building.add("nincs_ilyen_m117")  # ne inditson hatter-epitest
    try:
        assert lx.term_in_catalog("nincs_ilyen_m117", "Cégünk számára") is None
    finally:
        lx._building.discard("nincs_ilyen_m117")


def test_chat_wiring():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "api", "chat.py"),
               encoding="utf-8").read()
    assert src.count("term_in_catalog") == 2 and "m117 link gate" in src

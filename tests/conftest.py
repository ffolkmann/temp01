"""Elore betoltjuk a valos app-modulokat, mielott a test_sync_parity
modul-szintu app.__path__-uritese (izolacios trukk) elerhetetlenne tenne oket
a kesobb kollektalt tesztek szamara. Az import a sys.modules-cache-be kerul,
onnan a kesobbi importok mar path-fuggetlenul kiszolgalhatok. (m26)"""
import app.services.live_product  # noqa: F401

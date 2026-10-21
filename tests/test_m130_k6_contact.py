# -*- coding: utf-8 -*-
"""m130 (K6): szovegben kert elerhetoseg urlap nelkul -> requested_contact() + bekotes a m116 blokkba."""
import importlib.util
import os

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _load():
    p = os.path.join(_ROOT, "app", "services", "formpromise.py")
    spec = importlib.util.spec_from_file_location("m130_formpromise", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fp = _load()
rc = fp.requested_contact


def test_imperative_email_and_phone():
    assert rc("Ha szeretnéd, add meg az e-mail-címedet és a telefonszámodat, és egy kolléga felveszi veled a kapcsolatot.")


def test_imperative_variants():
    assert rc("Írd meg az e-mail-címed, és kollégánk utánanéz.")
    assert rc("Hagyd itt az e-mail-címedet (és a telefonszámodat), és egy kolléga jelentkezik.")
    assert rc("Csak küldd el az e-mail-címedet, és kollégánk utánanéz.")
    assert rc("Add meg itt az elérhetőséged, és visszahívnak!")
    assert rc("Oszd meg az e-mail-címedet, valamint írd meg, melyik termékről van szó.")


def test_conditional_variants():
    assert rc("Ehhez elég, ha megadod az e-mail-címed!")
    assert rc("Ha megadod az e-mail-címedet vagy a telefonszámodat, egy kolléga is felveheti veled a kapcsolatot.")


def test_shop_own_contact_is_not_a_request():
    assert not rc("Az ügyfélszolgálatot a +36 20 218 48 84 számon vagy az info@example.hu címen éred el.")
    assert not rc("Küldd el e-mailben az ügyfélszolgálatnak: info@example.hu – írd mellé a tokmány méretét.")
    assert not rc("Írj az info@example.hu címre, és ők válaszolnak.")


def test_negated_request_ignored():
    assert not rc("Ha a levélben bankkártyaadatot vagy jelszót kértek, azt ne add meg.")
    assert not rc("A telefonszámodat ne add meg idegeneknek.")


def test_link_text_ignored():
    assert not rc("Itt tudod megadni: [add meg az e-mail-címed](https://example.hu/kapcsolat)")


def test_plain_product_answer_no_request():
    assert not rc("A Ryobi RAC351 pótkés szett raktáron van, 8 970 Ft. Ide kattintva rendelheted.")
    assert not rc("Írd meg, melyik termék érdekel, és megnézem a szállítási idejét.")


def test_promised_form_unchanged():
    assert fp.promised_form("A megjelenő űrlapon add meg a rendelésszámot és az e-mail-címet.") == "order"
    assert fp.promised_form("Add meg az e-mail-címedet, és egy kolléga jelentkezik.") is None


def test_chat_wiring_m130():
    src = open(os.path.join(_ROOT, "app", "api", "chat.py"), encoding="utf-8").read()
    i = src.index("requested_contact as _rc130")
    assert src.index("_k116 = _pf116(parsed.reply)") < i
    assert src.index('_k116 = "lead"', i) > i
    assert src.index("m130 elerhetoseg-keres -> lead-urlap") > i
    assert i < src.index('if _k116 == "order":')

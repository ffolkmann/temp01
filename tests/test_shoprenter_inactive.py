"""Tests for ShoprenterBuilder inactive-product filtering."""
import base64

import pytest

from app.sync.builders import ShoprenterBuilder


def _make_item(status: str, name: str = "Teszt termék") -> dict:
    """Minimal Shoprenter /productExtend item dict."""
    desc_id = base64.b64encode(b"language_id=1").decode()
    return {
        "status": status,
        "productDescriptions": [
            {
                "id": desc_id,
                "name": name,
                "shortDescription": "",
                "description": "",
                "parameters": "",
            }
        ],
        "productPrices": [],
        "stock1": None,
        "orderable": "0",
        "urlAliases": [],
        "productAttributeExtend": [],
        "productRelatedProductRelations": [],
        "productCollateralProductRelations": [],
        "manufacturer": {},
        "sku": "TST-001",
    }


def test_active_product_is_included_by_default():
    """An active product (status='1') must always be indexed."""
    builder = ShoprenterBuilder(client_id="test", public_url="https://example.com/")
    builder.index([_make_item("1")])
    results = builder.build([_make_item("1")])
    assert len(results) == 1
    assert results[0].name == "Teszt termék"


def test_inactive_product_excluded_by_default():
    """An inactive product (status='0') must be skipped when include_inactive=False (default)."""
    builder = ShoprenterBuilder(client_id="test", public_url="https://example.com/")
    builder.index([_make_item("0")])
    results = builder.build([_make_item("0")])
    assert len(results) == 0


def test_inactive_product_included_when_flag_set():
    """An inactive product must be included when include_inactive=True."""
    builder = ShoprenterBuilder(
        client_id="test",
        public_url="https://example.com/",
        include_inactive=True,
    )
    builder.index([_make_item("0")])
    results = builder.build([_make_item("0")])
    assert len(results) == 1
    assert results[0].name == "Teszt termék"

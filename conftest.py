"""Shared pytest fixtures: realistic catalogue data and API clients."""

import itertools
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

D = Decimal


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def make_product(db):
    from inventory.models import Product

    counter = itertools.count(1)

    def _make(length="10", width="10", height="10", weight="1", **overrides):
        n = next(counter)
        fields = {
            "name": f"Test product {n}",
            "sku": f"TEST-{n}",
            "length": D(str(length)),
            "width": D(str(width)),
            "height": D(str(height)),
            "weight": D(str(weight)),
        }
        fields.update(overrides)
        return Product.objects.create(**fields)

    return _make


@pytest.fixture
def make_box(db):
    from inventory.models import ShippingBox

    counter = itertools.count(1)

    def _make(length="30", width="30", height="30", max_weight="20", cost="30", **overrides):
        n = next(counter)
        fields = {
            "name": f"Test box {n}",
            "box_code": f"BOX-{n}",
            "internal_length": D(str(length)),
            "internal_width": D(str(width)),
            "internal_height": D(str(height)),
            "max_weight": D(str(max_weight)),
            "cost": D(str(cost)),
        }
        fields.update(overrides)
        return ShippingBox.objects.create(**fields)

    return _make


@pytest.fixture
def make_order(db):
    from orders.services import create_order

    def _make(*lines, order_number=None):
        """``make_order((laptop, 2), (mouse, 1))``"""
        return create_order(list(lines), order_number=order_number)

    return _make


@pytest.fixture
def catalog(make_box, make_product):
    """A realistic small catalogue (cm / kg / INR), resembling a real warehouse."""
    boxes = {
        "small": make_box(25, 20, 10, max_weight=5, cost=20, name="Small", box_code="SMALL"),
        "medium": make_box(40, 30, 20, max_weight=15, cost=35, name="Medium", box_code="MEDIUM"),
        "medium_flat": make_box(50, 40, 10, max_weight=15, cost=35, name="Medium Flat", box_code="MEDIUM-FLAT"),
        "large": make_box(60, 40, 40, max_weight=25, cost=55, name="Large", box_code="LARGE"),
        "retired": make_box(100, 100, 100, max_weight=100, cost=1, name="Retired", box_code="RETIRED", is_active=False),
    }
    products = {
        "laptop": make_product(33, 23, 2, weight="1.4", name="Laptop", sku="LAPTOP"),
        "mouse": make_product(12, 7, 4, weight="0.1", name="Mouse", sku="MOUSE"),
        "headphones": make_product(22, 18, 9, weight="0.35", name="Headphones", sku="HEADPHONES"),
        "monitor": make_product(70, 45, 15, weight="7.5", name="Monitor", sku="MONITOR"),
        "dumbbell": make_product(20, 10, 10, weight="10", name="Dumbbell", sku="DUMBBELL"),
    }
    return {"boxes": boxes, "products": products}

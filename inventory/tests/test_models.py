from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from inventory.models import Product, ShippingBox
from inventory.services import active_boxes

pytestmark = pytest.mark.django_db


def test_product_volume_and_str(make_product):
    product = make_product("10.5", "2", "3", sku="ABC", name="Thing")
    assert product.volume == Decimal("63.0000")
    assert str(product) == "ABC – Thing"


def test_box_volume_and_str(make_box):
    box = make_box("40", "30", "20", box_code="M", name="Medium")
    assert box.internal_volume == Decimal("24000")
    assert str(box) == "M – Medium"


def test_sku_and_box_code_are_unique(make_product, make_box):
    make_product(sku="DUP")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_product(sku="DUP")
    make_box(box_code="DUP")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_box(box_code="DUP")


def test_active_boxes_excludes_inactive_and_sorts_by_cost(make_box):
    make_box(cost=50, box_code="B")
    make_box(cost=10, box_code="A")
    make_box(cost=1, box_code="OFF", is_active=False)
    assert [b.box_code for b in active_boxes()] == ["A", "B"]


def test_box_ordering_default_is_cheapest_first(make_box):
    make_box(cost=9, box_code="Y")
    make_box(cost=3, box_code="X")
    assert list(ShippingBox.objects.values_list("box_code", flat=True)) == ["X", "Y"]
    assert Product._meta.ordering == ["id"]

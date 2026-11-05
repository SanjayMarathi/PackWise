"""Edge cases across layers: DB constraints, error handling, logging, odd inputs."""

import json
import logging
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.http import QueryDict
from rest_framework.exceptions import ValidationError

from common.exceptions import ConflictError, api_exception_handler
from common.logging import JsonFormatter
from common.query import parse_bool_param
from inventory.models import Product, ShippingBox
from orders.models import Order, OrderItem
from packing.services.recommendation_service import recommend_box_for_order

D = Decimal


# ---------------------------------------------------------------- database constraints


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["length", "width", "height", "weight"])
def test_database_rejects_non_positive_product_values(field):
    values = {"name": "x", "sku": "X", "length": 1, "width": 1, "height": 1, "weight": 1, field: 0}
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.create(**values)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [("internal_length", 0), ("internal_width", -1), ("internal_height", 0), ("max_weight", 0), ("cost", -1)],
)
def test_database_rejects_invalid_box_values(field, value):
    values = {
        "name": "x",
        "box_code": "X",
        "internal_length": 1,
        "internal_width": 1,
        "internal_height": 1,
        "max_weight": 1,
        "cost": 0,
        field: value,
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        ShippingBox.objects.create(**values)


@pytest.mark.django_db
def test_database_rejects_invalid_quantity_and_status(make_product):
    order = Order.objects.create(order_number="X-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderItem.objects.create(order=order, product=make_product(), quantity=0)
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.objects.filter(pk=order.pk).update(status="shipped")


@pytest.mark.django_db
def test_same_product_cannot_appear_twice_in_an_order(make_product):
    product = make_product()
    order = Order.objects.create(order_number="X-2")
    OrderItem.objects.create(order=order, product=product, quantity=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderItem.objects.create(order=order, product=product, quantity=2)


@pytest.mark.django_db
def test_products_in_orders_are_protected_from_deletion(make_product, make_order):
    product = make_product()
    make_order((product, 1))
    with pytest.raises(ProtectedError):
        product.delete()


# ---------------------------------------------------------------- recommendation corner cases


@pytest.mark.django_db
def test_free_box_wins_under_lowest_cost(make_box, make_product, make_order):
    make_box(cost=0, box_code="FREE")
    make_box(cost=5, box_code="PAID")
    order = make_order((make_product(), 1))
    assert recommend_box_for_order(order).selected.box.box_code == "FREE"


@pytest.mark.django_db
def test_many_small_units_are_all_placed(make_box, make_product, make_order):
    make_box(30, 30, 30, max_weight=100)
    order = make_order((make_product(5, 5, 5, weight="0.2"), 100), (make_product(10, 10, 5, weight="0.5"), 10))
    selected = recommend_box_for_order(order).selected
    assert len(selected.packing_details["placements"]) == 110


@pytest.mark.django_db
def test_box_cost_is_snapshotted_at_recommendation_time(make_box, make_product, make_order):
    box = make_box(cost="40")
    order = make_order((make_product(), 1))
    rec = recommend_box_for_order(order).selected
    ShippingBox.objects.filter(pk=box.pk).update(cost=D("99"))
    rec.refresh_from_db()
    assert rec.box_cost == D("40.00")


@pytest.mark.django_db
def test_deactivated_products_in_existing_orders_can_still_be_packed(make_box, make_product, make_order):
    make_box()
    product = make_product()
    order = make_order((product, 1))
    Product.objects.filter(pk=product.pk).update(is_active=False)
    assert recommend_box_for_order(order).selected is not None


@pytest.mark.django_db
def test_model_string_representations(make_box, make_product, make_order):
    box = make_box()
    product = make_product(sku="STR-1")
    order = make_order((product, 2), order_number="STR-ORDER")
    selected = recommend_box_for_order(order).selected
    assert str(order) == "STR-ORDER"
    assert str(order.items.get()) == f"2 x {product.pk} in order {order.pk}"
    assert str(selected) == f"Order {order.pk} → box {box.pk} (rank 1)"


def test_box_with_more_precision_than_the_engine_is_rejected():
    from packing.algorithms import InvalidPackingInput
    from packing.services.validation_service import box_to_container

    box = ShippingBox(
        pk=1, box_code="ODD", internal_length=D("10.005"), internal_width=1, internal_height=1, max_weight=1, cost=0
    )
    with pytest.raises(InvalidPackingInput, match="ODD"):
        box_to_container(box)


def test_packer_verification_can_be_disabled():
    from packing.algorithms import Container, Item, PackerConfig, pack

    items = [Item("a#1", "a", 6, 6, 6, 1), Item("b#1", "b", 6, 6, 6, 1)]
    unverified = pack(items, Container("c", 10, 10, 10, 100), PackerConfig(verify=False))
    assert unverified.status.value == "heuristic_failure"
    assert pack(items[:1], Container("c", 10, 10, 10, 100), PackerConfig(verify=False)).feasible


# ---------------------------------------------------------------- error handler


def test_handler_maps_domain_errors():
    response = api_exception_handler(ConflictError("busy", code="locked", details={"a": 1}), {})
    assert response.status_code == 409
    assert response.data == {"status": "error", "error": {"code": "locked", "message": "busy", "details": {"a": 1}}}


def test_handler_maps_integrity_and_protected_errors():
    assert api_exception_handler(IntegrityError("dup key"), {}).status_code == 409
    assert api_exception_handler(ProtectedError("in use", set()), {}).data["error"]["code"] == "resource_in_use"


def test_handler_maps_django_validation_errors():
    response = api_exception_handler(DjangoValidationError({"sku": ["bad"]}), {})
    assert response.status_code == 400
    assert response.data["error"]["details"] == {"sku": ["bad"]}
    flat = api_exception_handler(DjangoValidationError("bad value"), {})
    assert flat.data["error"]["details"] == ["bad value"]


def test_handler_lets_django_show_debug_page_in_debug_mode(settings):
    settings.DEBUG = True
    assert api_exception_handler(RuntimeError("boom"), {}) is None


# ---------------------------------------------------------------- helpers


def test_json_formatter_includes_extra_fields_and_exceptions():
    record = logging.LogRecord("packwise.test", logging.INFO, __file__, 1, "order_created", (), None)
    record.order_id = 42
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "order_created"
    assert payload["order_id"] == 42
    assert payload["level"] == "INFO"
    assert "timestamp" in payload

    try:
        raise ValueError("bad")
    except ValueError:
        import sys

        error_record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    assert "ValueError: bad" in json.loads(JsonFormatter().format(error_record))["exc_info"]


@pytest.mark.parametrize(
    ("raw", "expected"), [("true", True), ("1", True), ("FALSE", False), ("no", False), ("", None)]
)
def test_parse_bool_param(raw, expected):
    assert parse_bool_param(QueryDict(f"flag={raw}"), "flag") is expected


def test_parse_bool_param_rejects_garbage():
    with pytest.raises(ValidationError):
        parse_bool_param(QueryDict("flag=perhaps"), "flag")
    assert parse_bool_param(QueryDict(""), "flag") is None

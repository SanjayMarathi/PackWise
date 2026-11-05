import pytest
from django.db import IntegrityError

from common.exceptions import UnprocessableError
from orders.models import Order, OrderItem
from orders.services import create_order, generate_order_number


@pytest.mark.django_db
def test_create_order_writes_order_and_items(make_product):
    a, b = make_product(), make_product()
    order = create_order([(a, 2), (b, 1)], order_number="WEB-7")
    assert order.order_number == "WEB-7"
    assert order.status == Order.Status.PENDING
    assert sorted(order.items.values_list("product_id", "quantity")) == sorted([(a.pk, 2), (b.pk, 1)])


@pytest.mark.django_db
def test_order_creation_is_atomic(make_product, monkeypatch):
    product = make_product()

    def broken_bulk_create(*args, **kwargs):
        raise IntegrityError("simulated failure while writing items")

    monkeypatch.setattr(OrderItem.objects, "bulk_create", broken_bulk_create)
    with pytest.raises(IntegrityError):
        create_order([(product, 1)])
    assert not Order.objects.exists()  # the order row was rolled back too


@pytest.mark.django_db
def test_create_order_requires_lines():
    with pytest.raises(UnprocessableError, match="at least one item") as excinfo:
        create_order([])
    assert excinfo.value.code == "empty_order"


def test_generated_order_numbers_are_unique_and_well_formed():
    numbers = {generate_order_number() for _ in range(500)}
    assert len(numbers) == 500
    assert all(n.startswith("ORD-") and len(n) == len("ORD-20260101-ABCDEF12") for n in numbers)

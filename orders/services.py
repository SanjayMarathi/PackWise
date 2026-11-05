"""Order business operations."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Sequence

from django.db import transaction
from django.utils import timezone

from common.exceptions import UnprocessableError
from inventory.models import Product

from .models import Order, OrderItem

logger = logging.getLogger("packwise.orders")


def generate_order_number() -> str:
    """E.g. ``ORD-20261105-9F2C41AB``. 32 random bits per day make collisions negligible."""
    return f"ORD-{timezone.now():%Y%m%d}-{secrets.token_hex(4).upper()}"


@transaction.atomic
def create_order(lines: Sequence[tuple[Product, int]], order_number: str | None = None) -> Order:
    """Create an order and its items atomically: either all rows are written or none."""
    if not lines:
        raise UnprocessableError("An order must contain at least one item.", code="empty_order")
    order = Order.objects.create(order_number=order_number or generate_order_number())
    OrderItem.objects.bulk_create(
        [OrderItem(order=order, product=product, quantity=quantity) for product, quantity in lines]
    )
    logger.info(
        "order_created",
        extra={
            "order_id": order.pk,
            "order_number": order.order_number,
            "lines": len(lines),
            "units": sum(q for _, q in lines),
        },
    )
    return order

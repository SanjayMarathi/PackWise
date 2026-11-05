"""Order- and catalogue-level validation before anything reaches the engine.

The engine's dataclasses validate individual values themselves. This layer
adds the business rules (non-empty order, unit limits) and converts Django
model instances into engine inputs, reporting problems as API-friendly
``UnprocessableError``s rather than engine exceptions.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal

from django.conf import settings

from common.exceptions import UnprocessableError
from inventory.models import ShippingBox
from orders.models import OrderItem
from packing.algorithms import Container, InvalidPackingInput, ItemLine

from .units import cm_to_units, kg_to_units


class OrderValidationError(UnprocessableError):
    default_code = "invalid_order"


def validate_order_items(order_items: Sequence[OrderItem]) -> list[ItemLine]:
    """Check an order's lines and convert them to engine ``ItemLine``s."""
    if not order_items:
        raise OrderValidationError("Order has no items; there is nothing to pack.", code="empty_order")

    max_units = settings.PACKWISE["MAX_ITEMS_PER_ORDER"]
    units = sum(item.quantity for item in order_items)
    if units > max_units:
        raise OrderValidationError(
            f"Order has {units} units; at most {max_units} can be packed per request.",
            code="order_too_large",
        )

    lines: list[ItemLine] = []
    errors: dict[str, str] = {}
    for order_item in order_items:
        product = order_item.product
        try:
            lines.append(
                ItemLine(
                    product_id=product.pk,
                    sku=product.sku,
                    length=cm_to_units(product.length),
                    width=cm_to_units(product.width),
                    height=cm_to_units(product.height),
                    weight=kg_to_units(product.weight),
                    quantity=order_item.quantity,
                )
            )
        except (InvalidPackingInput, ValueError) as exc:
            errors[product.sku] = str(exc)
    if errors:
        raise OrderValidationError("Order contains products with invalid data.", code="invalid_product", details=errors)
    return lines


def box_to_container(box: ShippingBox) -> Container:
    """Convert a box to an engine ``Container``. Raises ``InvalidPackingInput`` if invalid."""
    try:
        return Container(
            container_id=box.pk,
            length=cm_to_units(box.internal_length),
            width=cm_to_units(box.internal_width),
            height=cm_to_units(box.internal_height),
            max_weight=kg_to_units(box.max_weight),
        )
    except ValueError as exc:  # InvalidPackingInput is a ValueError
        raise InvalidPackingInput(f"Box {box.box_code}: {exc}") from exc


def validate_box(box: ShippingBox) -> list[str]:
    """Return configuration errors for a box (empty list = usable).

    Database constraints already enforce these rules. This is a second line
    of defence for rows written by raw SQL or created before a constraint
    existed.
    """
    errors = []
    for field in ("internal_length", "internal_width", "internal_height", "max_weight"):
        if getattr(box, field) is None or getattr(box, field) <= 0:
            errors.append(f"{field} must be positive.")
    if box.cost is None or box.cost < Decimal("0"):
        errors.append("cost must not be negative.")
    return errors


def usable_boxes(boxes: Iterable[ShippingBox]) -> tuple[list[ShippingBox], list[tuple[ShippingBox, list[str]]]]:
    """Split boxes into (usable, [(invalid box, errors)])."""
    usable, invalid = [], []
    for box in boxes:
        errors = validate_box(box)
        if errors:
            invalid.append((box, errors))
        else:
            usable.append(box)
    return usable, invalid

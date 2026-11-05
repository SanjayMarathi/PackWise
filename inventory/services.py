"""Catalogue business operations used by the API views and other apps."""

import logging

from django.db.models import ProtectedError, QuerySet

from common.exceptions import ConflictError

from .models import Product, ShippingBox

logger = logging.getLogger("packwise.inventory")


def active_boxes() -> QuerySet[ShippingBox]:
    """Boxes eligible for recommendation, cheapest first (uses ``box_active_cost_idx``)."""
    return ShippingBox.objects.filter(is_active=True).order_by("cost", "id")


def delete_product(product: Product) -> None:
    """Hard-delete an unused product. One that is referenced by orders is kept for history."""
    product_id = product.pk  # Django clears pk after delete()
    try:
        product.delete()
    except ProtectedError as exc:
        raise ConflictError(
            'Product is referenced by existing orders. Deactivate it instead with PATCH {"is_active": false}.',
            code="product_in_use",
        ) from exc
    logger.info("product_deleted", extra={"product_id": product_id})


def delete_box(box: ShippingBox) -> None:
    box_id = box.pk
    try:
        box.delete()
    except ProtectedError as exc:
        raise ConflictError(
            'Box is referenced by stored recommendations. Deactivate it instead with PATCH {"is_active": false}.',
            code="box_in_use",
        ) from exc
    logger.info("box_deleted", extra={"box_id": box_id})

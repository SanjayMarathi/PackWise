from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint

from common.models import TimeStampedModel


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending recommendation"
    RECOMMENDED = "recommended", "Box recommended"
    NO_FEASIBLE_BOX = "no_feasible_box", "No feasible box"


class Order(TimeStampedModel):
    Status = OrderStatus  # so callers can write Order.Status.RECOMMENDED

    order_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # A nested Meta cannot see names from the class body, hence the module-level enum.
            CheckConstraint(condition=Q(status__in=OrderStatus.values), name="order_status_valid"),
        ]

    def __str__(self) -> str:
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # PROTECT: a product that appears in an order can never be deleted out from under it.
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["id"]
        constraints = [
            UniqueConstraint(fields=["order", "product"], name="orderitem_unique_product_per_order"),
            CheckConstraint(condition=Q(quantity__gte=1), name="orderitem_quantity_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product_id} in order {self.order_id}"

    @property
    def line_weight(self) -> Decimal:
        return self.product.weight * self.quantity

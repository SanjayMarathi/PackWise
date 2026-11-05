"""Catalogue models. Units: dimensions in cm, weight in kg, cost in INR."""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, Q

from common.models import TimeStampedModel

MIN_DIMENSION = Decimal("0.01")  # 0.1 mm, the resolution of the packing engine
MIN_WEIGHT = Decimal("0.001")  # 1 g


def dimension_field(help_text: str) -> models.DecimalField:
    return models.DecimalField(
        max_digits=7,  # up to 99,999.99 cm
        decimal_places=2,
        validators=[MinValueValidator(MIN_DIMENSION)],
        help_text=help_text,
    )


def weight_field(help_text: str) -> models.DecimalField:
    return models.DecimalField(
        max_digits=8,  # up to 99,999.999 kg
        decimal_places=3,
        validators=[MinValueValidator(MIN_WEIGHT)],
        help_text=help_text,
    )


class Product(TimeStampedModel):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64, unique=True, help_text="Stock-keeping unit, stored upper-case.")
    length = dimension_field("Length in cm.")
    width = dimension_field("Width in cm.")
    height = dimension_field("Height in cm.")
    weight = weight_field("Weight in kg.")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            CheckConstraint(
                condition=Q(length__gt=0) & Q(width__gt=0) & Q(height__gt=0),
                name="product_dimensions_positive",
            ),
            CheckConstraint(condition=Q(weight__gt=0), name="product_weight_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.sku} – {self.name}"

    @property
    def volume(self) -> Decimal:
        """Volume in cm³."""
        return self.length * self.width * self.height


class ShippingBox(TimeStampedModel):
    name = models.CharField(max_length=100)
    box_code = models.CharField(max_length=32, unique=True, help_text="Stored upper-case.")
    internal_length = dimension_field("Internal length in cm.")
    internal_width = dimension_field("Internal width in cm.")
    internal_height = dimension_field("Internal height in cm.")
    max_weight = weight_field("Maximum load in kg.")
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Cost per box in INR.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["cost", "id"]
        verbose_name_plural = "shipping boxes"
        constraints = [
            CheckConstraint(
                condition=Q(internal_length__gt=0) & Q(internal_width__gt=0) & Q(internal_height__gt=0),
                name="box_dimensions_positive",
            ),
            CheckConstraint(condition=Q(max_weight__gt=0), name="box_max_weight_positive"),
            CheckConstraint(condition=Q(cost__gte=0), name="box_cost_non_negative"),
        ]
        indexes = [
            # The recommendation engine's query: active boxes, cheapest first.
            models.Index(fields=["is_active", "cost"], name="box_active_cost_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.box_code} – {self.name}"

    @property
    def internal_volume(self) -> Decimal:
        """Internal volume in cm³."""
        return self.internal_length * self.internal_width * self.internal_height

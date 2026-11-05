from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint


class BoxRecommendation(models.Model):
    """One feasible box for an order, as ranked by the latest recommendation run.

    Each run replaces the order's previous rows inside a transaction that holds
    a row lock on the order. Two database constraints back this up, so even a
    bug or a race can never leave an order with duplicate boxes or with two
    selected recommendations.
    """

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="recommendations")
    box = models.ForeignKey("inventory.ShippingBox", on_delete=models.PROTECT, related_name="recommendations")
    rank = models.PositiveSmallIntegerField(help_text="1 = recommended box, 2.. = ranked alternatives.")
    strategy = models.CharField(max_length=32, help_text="Ranking strategy used for this run.")
    total_weight = models.DecimalField(max_digits=10, decimal_places=3, help_text="Order weight in kg.")
    box_cost = models.DecimalField(max_digits=10, decimal_places=2, help_text="Box cost (INR) at recommendation time.")
    utilization_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    packing_details = models.JSONField(default=dict, help_text="Placements (cm) and algorithm metadata.")
    is_selected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order_id", "rank"]
        constraints = [
            UniqueConstraint(fields=["order", "box"], name="recommendation_unique_box_per_order"),
            UniqueConstraint(fields=["order", "rank"], name="recommendation_unique_rank_per_order"),
            UniqueConstraint(
                fields=["order"],
                condition=Q(is_selected=True),
                name="recommendation_one_selected_per_order",
            ),
            CheckConstraint(
                condition=Q(utilization_percentage__gte=0) & Q(utilization_percentage__lte=100),
                name="recommendation_utilization_range",
            ),
            CheckConstraint(condition=Q(rank__gte=1), name="recommendation_rank_positive"),
        ]

    def __str__(self) -> str:
        return f"Order {self.order_id} → box {self.box_id} (rank {self.rank})"

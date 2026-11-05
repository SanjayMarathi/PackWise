"""Request validation and response shapes for the recommendation endpoints.

Responses are built as plain dicts and passed through these serializers, so
the OpenAPI schema drf-spectacular generates matches what is actually
returned.
"""

from __future__ import annotations

from collections.abc import Sequence

from rest_framework import serializers

from common.serializers import StrictFieldsMixin
from orders.models import Order
from packing.algorithms import RANKING_STRATEGIES

from .models import BoxRecommendation
from .services.recommendation_service import RecommendationOutcome


class RecommendRequestSerializer(StrictFieldsMixin, serializers.Serializer):
    strategy = serializers.ChoiceField(
        choices=sorted(RANKING_STRATEGIES),
        required=False,
        help_text="Ranking strategy; defaults to the server's PACKWISE_RANKING_STRATEGY (lowest_cost).",
    )


class XYZSerializer(serializers.Serializer):
    x = serializers.FloatField()
    y = serializers.FloatField()
    z = serializers.FloatField()


class DimensionsSerializer(serializers.Serializer):
    length = serializers.FloatField()
    width = serializers.FloatField()
    height = serializers.FloatField()


class PlacementSerializer(serializers.Serializer):
    sequence = serializers.IntegerField(help_text="Loading order.")
    item_id = serializers.CharField(help_text="<product_id>#<unit number>")
    product_id = serializers.IntegerField()
    sku = serializers.CharField()
    position = XYZSerializer(help_text="Minimum corner in cm, from the box's inner bottom-left-back corner.")
    dimensions = DimensionsSerializer(help_text="Extents along x/y/z in cm after rotation.")
    orientation = serializers.CharField(help_text="Original dimensions along x,y,z, e.g. 'WLH'.")
    rotated = serializers.BooleanField()


class BoxOptionSerializer(serializers.Serializer):
    recommendation_id = serializers.IntegerField()
    rank = serializers.IntegerField()
    box_id = serializers.IntegerField()
    box_code = serializers.CharField()
    box_name = serializers.CharField()
    cost = serializers.FloatField(help_text="INR")
    total_weight = serializers.FloatField(help_text="kg")
    utilization = serializers.FloatField(help_text="Percentage of box volume occupied.")
    packing_feasible = serializers.BooleanField()
    box_dimensions = DimensionsSerializer()
    box_volume_cm3 = serializers.FloatField()
    used_volume_cm3 = serializers.FloatField()
    sort_strategy = serializers.CharField(allow_null=True)
    execution_time_ms = serializers.FloatField()
    placements = PlacementSerializer(many=True)


class RejectedBoxSerializer(serializers.Serializer):
    box_id = serializers.IntegerField()
    box_code = serializers.CharField()
    box_name = serializers.CharField()
    feasibility = serializers.ChoiceField(
        choices=["proven_infeasible", "heuristic_failure", "invalid_configuration"],
        help_text="proven_infeasible = mathematically impossible; heuristic_failure = not found, may exist.",
    )
    reasons = serializers.ListField(child=serializers.CharField())


class SummarySerializer(serializers.Serializer):
    total_units = serializers.IntegerField()
    total_weight = serializers.FloatField(help_text="kg")
    boxes_evaluated = serializers.IntegerField()
    feasible_boxes = serializers.IntegerField()
    execution_time_ms = serializers.FloatField()


class RecommendationResponseSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    order_number = serializers.CharField()
    status = serializers.ChoiceField(choices=["success", "no_feasible_box"])
    order_status = serializers.ChoiceField(choices=Order.Status.values)
    strategy = serializers.CharField()
    generated_at = serializers.DateTimeField(allow_null=True)
    recommendation = BoxOptionSerializer(allow_null=True)
    alternatives = BoxOptionSerializer(many=True)
    rejected_boxes = RejectedBoxSerializer(many=True)
    summary = SummarySerializer()


class StoredRecommendationsSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    order_number = serializers.CharField()
    status = serializers.ChoiceField(choices=["success", "no_feasible_box", "not_generated"])
    order_status = serializers.ChoiceField(choices=Order.Status.values)
    strategy = serializers.CharField(allow_null=True)
    generated_at = serializers.DateTimeField(allow_null=True)
    recommendation = BoxOptionSerializer(allow_null=True)
    alternatives = BoxOptionSerializer(many=True)


# ---------------------------------------------------------------- payload builders


def box_option_payload(rec: BoxRecommendation) -> dict:
    details = rec.packing_details
    return {
        "recommendation_id": rec.pk,
        "rank": rec.rank,
        "box_id": rec.box.pk,
        "box_code": rec.box.box_code,
        "box_name": rec.box.name,
        "cost": rec.box_cost,
        "total_weight": rec.total_weight,
        "utilization": rec.utilization_percentage,
        "packing_feasible": True,
        "box_dimensions": details["box_dimensions"],
        "box_volume_cm3": details["box_volume_cm3"],
        "used_volume_cm3": details["used_volume_cm3"],
        "sort_strategy": details.get("sort_strategy"),
        "execution_time_ms": details.get("execution_time_ms", 0.0),
        "placements": details["placements"],
    }


def outcome_payload(outcome: RecommendationOutcome) -> dict:
    rows = outcome.recommendations
    return {
        "order_id": outcome.order.pk,
        "order_number": outcome.order.order_number,
        "status": "success" if rows else "no_feasible_box",
        "order_status": outcome.order.status,
        "strategy": outcome.strategy,
        "generated_at": rows[0].created_at if rows else None,
        "recommendation": box_option_payload(rows[0]) if rows else None,
        "alternatives": [box_option_payload(r) for r in rows[1:]],
        "rejected_boxes": [
            {
                "box_id": ev.box.pk,
                "box_code": ev.box.box_code,
                "box_name": ev.box.name,
                "feasibility": ev.status,
                "reasons": list(ev.reasons),
            }
            for ev in outcome.rejected
        ],
        "summary": {
            "total_units": outcome.total_units,
            "total_weight": outcome.total_weight,
            "boxes_evaluated": outcome.boxes_evaluated,
            "feasible_boxes": len(rows),
            "execution_time_ms": outcome.execution_time_ms,
        },
    }


def stored_payload(order: Order, rows: Sequence[BoxRecommendation]) -> dict:
    if rows:
        status = "success"
    elif order.status == Order.Status.NO_FEASIBLE_BOX:
        status = "no_feasible_box"
    else:
        status = "not_generated"
    return {
        "order_id": order.pk,
        "order_number": order.order_number,
        "status": status,
        "order_status": order.status,
        "strategy": rows[0].strategy if rows else None,
        "generated_at": rows[0].created_at if rows else None,
        "recommendation": box_option_payload(rows[0]) if rows else None,
        "alternatives": [box_option_payload(r) for r in rows[1:]],
    }

"""Box recommendation pipeline.

1. Load the order with its products and validate it.
2. Fetch the active shipping boxes and drop any with invalid configuration.
3. Compute the order's total weight and expand quantities into physical units.
4. Pre-filter each box with the engine's *provable* necessary conditions
   (weight capacity, per-item rotation fit, total volume).
5. Run the 3D packer on the boxes that survive.
6. Rank the feasible boxes with the configured strategy.
7. Persist the ranking atomically under a row lock on the order. Concurrent
   requests for the same order are serialised, and the unique constraints on
   ``BoxRecommendation`` make duplicate rows impossible regardless.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from common.exceptions import UnprocessableError
from inventory.models import ShippingBox
from inventory.services import active_boxes
from orders.models import Order
from packing.algorithms import (
    ALGORITHM_NAME,
    ENGINE_VERSION,
    RANKING_STRATEGIES,
    ItemLine,
    PackerConfig,
    PackingResult,
    PackingStatus,
    Placement,
    RankableBox,
    Reason,
    ReasonCode,
    expand_quantities,
    necessary_condition_violations,
    pack,
    rank_boxes,
)
from packing.models import BoxRecommendation

from .units import units_to_cm, units_to_kg, volume_units_to_cm3
from .validation_service import box_to_container, usable_boxes, validate_order_items

logger = logging.getLogger("packwise.recommendations")

INVALID_CONFIGURATION = "invalid_configuration"


@dataclass(frozen=True, slots=True)
class BoxEvaluation:
    box: ShippingBox
    status: str  # a PackingStatus value, or "invalid_configuration"
    result: PackingResult | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecommendationOutcome:
    order: Order
    strategy: str
    recommendations: tuple[BoxRecommendation, ...]  # persisted rows, rank order
    rejected: tuple[BoxEvaluation, ...]
    total_units: int
    total_weight: Decimal
    boxes_evaluated: int
    execution_time_ms: float

    @property
    def selected(self) -> BoxRecommendation | None:
        return self.recommendations[0] if self.recommendations else None


# ---------------------------------------------------------------- configuration


def resolve_strategy(requested: str | None = None) -> str:
    strategy = requested or settings.PACKWISE["RANKING_STRATEGY"]
    if strategy not in RANKING_STRATEGIES:
        raise UnprocessableError(
            f"Unknown ranking strategy {strategy!r}. Choose one of {sorted(RANKING_STRATEGIES)}.",
            code="invalid_strategy",
        )
    return strategy


def packer_config() -> PackerConfig:
    return PackerConfig(min_support_ratio=settings.PACKWISE["MIN_SUPPORT_RATIO"])


# ---------------------------------------------------------------- evaluation (no database writes)


def evaluate_boxes(
    lines: Sequence[ItemLine],
    boxes: Iterable[ShippingBox],
    *,
    strategy: str,
    config: PackerConfig | None = None,
    labels: Mapping[object, str] | None = None,
) -> tuple[list[BoxEvaluation], list[BoxEvaluation]]:
    """Return ``(feasible boxes in rank order, rejected boxes)``."""
    config = config or packer_config()
    labels = labels or {}
    items = expand_quantities(lines)
    usable, invalid = usable_boxes(boxes)

    rejected = [BoxEvaluation(box, INVALID_CONFIGURATION, None, tuple(errors)) for box, errors in invalid]
    feasible: list[BoxEvaluation] = []
    for box in usable:
        container = box_to_container(box)
        proofs = necessary_condition_violations(items, container)
        if proofs:  # step 4: the box provably cannot work, so skip the expensive packer
            rejected.append(
                BoxEvaluation(box, PackingStatus.PROVEN_INFEASIBLE.value, None, describe_reasons(proofs, labels))
            )
            continue
        result = pack(items, container, config)
        if result.feasible:
            feasible.append(BoxEvaluation(box, result.status.value, result))
        else:
            rejected.append(BoxEvaluation(box, result.status.value, result, describe_reasons(result.reasons, labels)))

    ranked = rank_boxes(
        [
            RankableBox(ev.box.pk, ev.box.cost, ev.result.utilization_ratio, ev.result.container_volume)
            for ev in feasible
            if ev.result is not None
        ],
        strategy,
    )
    by_id = {ev.box.pk: ev for ev in feasible}
    return [by_id[r.box_id] for r in ranked], rejected


def describe_reasons(reasons: Iterable[Reason], labels: Mapping[object, str]) -> tuple[str, ...]:
    return tuple(describe_reason(r, labels) for r in reasons)


def describe_reason(reason: Reason, labels: Mapping[object, str]) -> str:
    names = ", ".join(labels.get(pid, f"product {pid}") for pid in reason.product_ids)
    if reason.code is ReasonCode.WEIGHT_EXCEEDED:
        return (
            f"Order weight {units_to_kg(reason.required or 0)} kg exceeds the box limit of "
            f"{units_to_kg(reason.available or 0)} kg."
        )
    if reason.code is ReasonCode.ITEM_TOO_LARGE:
        return f"{names} cannot fit inside the box in any orientation."
    if reason.code is ReasonCode.VOLUME_EXCEEDED:
        return (
            f"Total item volume {volume_units_to_cm3(reason.required or 0)} cm³ exceeds the box volume of "
            f"{volume_units_to_cm3(reason.available or 0)} cm³."
        )
    return (
        f"The packing heuristic could not place {reason.required} unit(s) of {names}. "
        "This does not prove that no arrangement exists."
    )


# ---------------------------------------------------------------- persistence


def placement_payload(sequence: int, placement: Placement) -> dict:
    return {
        "sequence": sequence,  # loading order: place items in this sequence
        "item_id": placement.item.item_id,
        "product_id": placement.item.product_id,
        "sku": placement.item.sku,
        "position": {
            "x": units_to_cm(placement.x),
            "y": units_to_cm(placement.y),
            "z": units_to_cm(placement.z),
        },
        "dimensions": {
            "length": units_to_cm(placement.length),
            "width": units_to_cm(placement.width),
            "height": units_to_cm(placement.height),
        },
        "orientation": placement.orientation_label,
        "rotated": placement.rotated,
    }


def packing_details(result: PackingResult) -> dict:
    c = result.container
    return {
        "algorithm": ALGORITHM_NAME,
        "engine_version": ENGINE_VERSION,
        "status": result.status.value,
        "sort_strategy": result.sort_strategy,
        "attempts": result.attempts,
        "execution_time_ms": result.execution_time_ms,
        "units": {"length": "cm", "weight": "kg", "volume": "cm3"},
        "box_dimensions": {
            "length": units_to_cm(c.length),
            "width": units_to_cm(c.width),
            "height": units_to_cm(c.height),
        },
        "box_volume_cm3": volume_units_to_cm3(result.container_volume),
        "used_volume_cm3": volume_units_to_cm3(result.used_volume),
        "placements": [placement_payload(n, p) for n, p in enumerate(result.placements, start=1)],
    }


@transaction.atomic
def _persist(
    order_id: int, ranked: Sequence[BoxEvaluation], strategy: str, total_weight: Decimal
) -> tuple[Order, list[BoxRecommendation]]:
    # SELECT ... FOR UPDATE. A concurrent run for the same order waits here
    # until this transaction commits, then replaces these rows with its own.
    order = Order.objects.select_for_update().get(pk=order_id)
    BoxRecommendation.objects.filter(order=order).delete()
    rows = [
        BoxRecommendation(
            order=order,
            box=ev.box,
            rank=rank,
            strategy=strategy,
            total_weight=total_weight,
            box_cost=ev.box.cost,
            utilization_percentage=Decimal(str(ev.result.utilization_percentage)),
            packing_details=packing_details(ev.result),
            is_selected=rank == 1,
        )
        for rank, ev in enumerate(ranked, start=1)
        if ev.result is not None
    ]
    BoxRecommendation.objects.bulk_create(rows)
    order.status = Order.Status.RECOMMENDED if rows else Order.Status.NO_FEASIBLE_BOX
    order.save(update_fields=["status", "updated_at"])
    return order, rows


# ---------------------------------------------------------------- entry point


def recommend_box_for_order(order: Order | int, strategy: str | None = None) -> RecommendationOutcome:
    started = time.perf_counter()
    strategy = resolve_strategy(strategy)
    order_id = order.pk if isinstance(order, Order) else order
    order = Order.objects.prefetch_related("items__product").get(pk=order_id)

    order_items = list(order.items.all())
    lines = validate_order_items(order_items)
    labels = {
        oi.product.pk: f"{oi.product.sku} ({oi.product.length}×{oi.product.width}×{oi.product.height} cm)"
        for oi in order_items
    }
    total_weight = sum((oi.product.weight * oi.quantity for oi in order_items), Decimal("0"))
    total_units = sum(oi.quantity for oi in order_items)

    boxes = list(active_boxes())
    ranked, rejected = evaluate_boxes(lines, boxes, strategy=strategy, labels=labels)
    order, rows = _persist(order.pk, ranked, strategy, total_weight)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    logger.info(
        "recommendation_generated",
        extra={
            "order_id": order.pk,
            "strategy": strategy,
            "boxes_evaluated": len(boxes),
            "feasible_boxes": len(rows),
            "selected_box_id": rows[0].box_id if rows else None,
            "duration_ms": elapsed_ms,
        },
    )
    return RecommendationOutcome(
        order=order,
        strategy=strategy,
        recommendations=tuple(rows),
        rejected=tuple(rejected),
        total_units=total_units,
        total_weight=total_weight,
        boxes_evaluated=len(boxes),
        execution_time_ms=elapsed_ms,
    )

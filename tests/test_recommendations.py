"""Business-logic tests for the recommendation service (real PostgreSQL)."""

import threading
from decimal import Decimal

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import override_settings

from common.exceptions import UnprocessableError
from inventory.models import Product, ShippingBox
from orders.models import Order, OrderItem
from packing.models import BoxRecommendation
from packing.services.recommendation_service import recommend_box_for_order, resolve_strategy
from packing.services.validation_service import (
    OrderValidationError,
    usable_boxes,
    validate_box,
    validate_order_items,
)

pytestmark = pytest.mark.django_db


def box_codes(outcome):
    return [r.box.box_code for r in outcome.recommendations]


def rejected_by_code(outcome):
    return {ev.box.box_code: ev for ev in outcome.rejected}


# ---------------------------------------------------------------- selection and ranking


def test_cheapest_feasible_box_is_selected(catalog, make_order):
    p = catalog["products"]
    order = make_order((p["laptop"], 1), (p["mouse"], 2))  # 33 cm laptop needs more than SMALL

    outcome = recommend_box_for_order(order)

    assert outcome.selected.box.box_code in {"MEDIUM", "MEDIUM-FLAT"}  # both cost 35
    assert outcome.selected.box_cost == Decimal("35")
    assert box_codes(outcome)[-1] == "LARGE"
    assert "SMALL" in rejected_by_code(outcome)
    assert rejected_by_code(outcome)["SMALL"].status == "proven_infeasible"


def test_equal_cost_boxes_are_ranked_by_utilization(catalog, make_order):
    p = catalog["products"]
    order = make_order((p["laptop"], 1))
    outcome = recommend_box_for_order(order)

    medium, flat = (next(r for r in outcome.recommendations if r.box.box_code == c) for c in ("MEDIUM", "MEDIUM-FLAT"))
    # MEDIUM is 24,000 cm³ and MEDIUM-FLAT is 20,000 cm³: same items, so the smaller box is fuller.
    assert flat.utilization_percentage > medium.utilization_percentage
    assert box_codes(outcome)[:2] == ["MEDIUM-FLAT", "MEDIUM"]


def test_inactive_boxes_are_ignored(catalog, make_order):
    order = make_order((catalog["products"]["monitor"], 1))
    outcome = recommend_box_for_order(order)

    considered = {r.box.box_code for r in outcome.recommendations} | set(rejected_by_code(outcome))
    assert "RETIRED" not in considered  # cheapest and biggest, but inactive
    assert outcome.boxes_evaluated == 4


def test_weight_capacity_exceeded_rejects_box_with_proof(catalog, make_order):
    order = make_order((catalog["products"]["dumbbell"], 2))  # 20 kg: only LARGE (25 kg) can carry it
    outcome = recommend_box_for_order(order)

    assert box_codes(outcome) == ["LARGE"]
    medium = rejected_by_code(outcome)["MEDIUM"]
    assert medium.status == "proven_infeasible"
    assert any("20.0 kg exceeds the box limit of 15.0 kg" in r for r in medium.reasons)


def test_no_feasible_box_found(catalog, make_order):
    order = make_order((catalog["products"]["dumbbell"], 3))  # 30 kg > every active box

    outcome = recommend_box_for_order(order)

    assert outcome.recommendations == ()
    assert outcome.selected is None
    assert len(outcome.rejected) == 4
    order.refresh_from_db()
    assert order.status == Order.Status.NO_FEASIBLE_BOX
    assert not BoxRecommendation.objects.filter(order=order).exists()


def test_strategy_can_be_chosen_per_request(make_box, make_product, make_order):
    cheap_big = make_box(50, 50, 50, cost=10, box_code="CHEAP-BIG")
    snug = make_box(11, 11, 11, cost=40, box_code="SNUG")
    order = make_order((make_product(10, 10, 10), 1))

    assert box_codes(recommend_box_for_order(order, "lowest_cost"))[0] == cheap_big.box_code
    assert box_codes(recommend_box_for_order(order, "best_utilization"))[0] == snug.box_code
    assert box_codes(recommend_box_for_order(order, "smallest_box"))[0] == snug.box_code


def test_default_strategy_comes_from_settings(make_box, make_product, make_order, settings):
    make_box(50, 50, 50, cost=10, box_code="CHEAP-BIG")
    make_box(11, 11, 11, cost=40, box_code="SNUG")
    order = make_order((make_product(10, 10, 10), 1))
    settings.PACKWISE = {**settings.PACKWISE, "RANKING_STRATEGY": "smallest_box"}

    outcome = recommend_box_for_order(order)
    assert outcome.strategy == "smallest_box"
    assert box_codes(outcome)[0] == "SNUG"


def test_unknown_strategy_is_rejected():
    with pytest.raises(UnprocessableError) as excinfo:
        resolve_strategy("random")
    assert excinfo.value.code == "invalid_strategy"


def test_heuristic_failure_is_reported_separately_from_proofs(make_box, make_product, make_order):
    make_box(10, 10, 10, cost=5, box_code="CUBE-10")  # two 6 cm cubes pass every cheap check, but cannot fit
    make_box(20, 10, 10, cost=9, box_code="LONG")
    order = make_order((make_product(6, 6, 6), 2))

    outcome = recommend_box_for_order(order)

    assert box_codes(outcome) == ["LONG"]
    cube = rejected_by_code(outcome)["CUBE-10"]
    assert cube.status == "heuristic_failure"
    assert "does not prove" in cube.reasons[0]


def test_product_that_only_fits_rotated_is_packed_rotated(make_box, make_product, make_order):
    make_box(10, 40, 10, cost=10, box_code="TUBE")
    order = make_order((make_product(40, 10, 10), 1))

    selected = recommend_box_for_order(order).selected
    (placement,) = selected.packing_details["placements"]
    assert placement["rotated"] is True
    assert placement["dimensions"] == {"length": 10.0, "width": 40.0, "height": 10.0}


def test_min_support_ratio_setting_reaches_the_engine(make_box, make_product, make_order, settings):
    # Instance from a seeded search (seed 1162): the footprints (7 + 12 + 10 = 29 cm²) exceed the
    # 28 cm² floor, so one item must sit on top, and no sort order finds a >= 50%-supported spot.
    make_box(7, 4, 2, cost=10, box_code="SHALLOW")
    order = make_order((make_product(7, 1, 1), 1), (make_product(4, 3, 1), 1), (make_product(5, 2, 1), 1))

    assert box_codes(recommend_box_for_order(order)) == ["SHALLOW"]  # overhang allowed by default
    settings.PACKWISE = {**settings.PACKWISE, "MIN_SUPPORT_RATIO": 0.5}
    outcome = recommend_box_for_order(order)
    assert box_codes(outcome) == []
    assert rejected_by_code(outcome)["SHALLOW"].status == "heuristic_failure"


# ---------------------------------------------------------------- persistence


def test_recommendations_are_persisted_with_ranks_and_details(catalog, make_order):
    p = catalog["products"]
    order = make_order((p["laptop"], 2), (p["mouse"], 3))

    outcome = recommend_box_for_order(order)

    rows = list(BoxRecommendation.objects.filter(order=order).order_by("rank"))
    assert [r.rank for r in rows] == list(range(1, len(rows) + 1))
    assert [r.is_selected for r in rows] == [True] + [False] * (len(rows) - 1)
    assert rows[0].pk == outcome.selected.pk
    assert rows[0].total_weight == Decimal("3.100")  # 2 x 1.4 + 3 x 0.1
    details = rows[0].packing_details
    assert len(details["placements"]) == 5
    assert details["algorithm"] == "maximal-empty-spaces/best-short-side-fit"
    assert details["status"] == "feasible"
    order.refresh_from_db()
    assert order.status == Order.Status.RECOMMENDED


def test_rerunning_replaces_previous_recommendations(catalog, make_order):
    order = make_order((catalog["products"]["laptop"], 1))
    first = recommend_box_for_order(order)
    second = recommend_box_for_order(order)

    assert BoxRecommendation.objects.filter(order=order).count() == len(second.recommendations)
    assert BoxRecommendation.objects.filter(order=order, is_selected=True).count() == 1
    assert not BoxRecommendation.objects.filter(pk__in=[r.pk for r in first.recommendations]).exists()


def test_database_forbids_two_selected_recommendations(catalog, make_order):
    order = make_order((catalog["products"]["laptop"], 1))
    boxes = catalog["boxes"]
    common = {"order": order, "strategy": "lowest_cost", "total_weight": 1, "box_cost": 1, "utilization_percentage": 1}
    BoxRecommendation.objects.create(box=boxes["medium"], rank=1, is_selected=True, **common)
    with pytest.raises(IntegrityError), transaction.atomic():
        BoxRecommendation.objects.create(box=boxes["large"], rank=2, is_selected=True, **common)


def test_database_forbids_duplicate_box_per_order(catalog, make_order):
    order = make_order((catalog["products"]["laptop"], 1))
    common = {"order": order, "box": catalog["boxes"]["medium"], "strategy": "x", "total_weight": 1, "box_cost": 1}
    BoxRecommendation.objects.create(rank=1, utilization_percentage=1, **common)
    with pytest.raises(IntegrityError), transaction.atomic():
        BoxRecommendation.objects.create(rank=2, utilization_percentage=1, **common)


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_do_not_create_duplicates(catalog, make_order):
    """Several threads (each with its own DB connection) recommend the same order at once."""
    order = make_order((catalog["products"]["laptop"], 1), (catalog["products"]["mouse"], 1))
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def worker():
        try:
            barrier.wait()
            recommend_box_for_order(order.pk)
        except BaseException as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    close_old_connections()

    assert errors == []
    rows = BoxRecommendation.objects.filter(order=order)
    assert rows.filter(is_selected=True).count() == 1
    assert rows.count() == rows.values("box").distinct().count() == 3  # MEDIUM, MEDIUM-FLAT, LARGE


# ---------------------------------------------------------------- validation


def test_empty_order_is_rejected(db):
    order = Order.objects.create(order_number="EMPTY-1")  # e.g. created through the admin
    with pytest.raises(OrderValidationError) as excinfo:
        recommend_box_for_order(order)
    assert excinfo.value.code == "empty_order"
    assert excinfo.value.status_code == 422


def test_order_with_too_many_units_is_rejected(make_product, make_order, settings, make_box):
    make_box()
    order = make_order((make_product(1, 1, 1), 11))
    settings.PACKWISE = {**settings.PACKWISE, "MAX_ITEMS_PER_ORDER": 10}
    with pytest.raises(OrderValidationError) as excinfo:
        recommend_box_for_order(order)
    assert excinfo.value.code == "order_too_large"


def test_invalid_product_dimensions_are_rejected_before_packing():
    # Rows like this cannot be saved (CHECK constraint), but the service must still refuse them.
    bad = Product(pk=99, sku="BAD", name="Bad", length=Decimal("0"), width=1, height=1, weight=1)
    with pytest.raises(OrderValidationError) as excinfo:
        validate_order_items([OrderItem(product=bad, quantity=1)])
    assert excinfo.value.code == "invalid_product"
    assert "BAD" in excinfo.value.details


def test_invalid_box_dimensions_are_excluded():
    good = ShippingBox(
        pk=1, box_code="OK", internal_length=1, internal_width=1, internal_height=1, max_weight=1, cost=0
    )
    bad = ShippingBox(
        pk=2, box_code="BAD", internal_length=0, internal_width=1, internal_height=1, max_weight=1, cost=-1
    )
    assert validate_box(good) == []
    assert validate_box(bad) == ["internal_length must be positive.", "cost must not be negative."]
    usable, invalid = usable_boxes([good, bad])
    assert usable == [good]
    assert invalid[0][0] is bad


def test_no_active_boxes_means_no_feasible_box(make_product, make_order):
    order = make_order((make_product(), 1))
    outcome = recommend_box_for_order(order)
    assert outcome.recommendations == ()
    assert outcome.boxes_evaluated == 0


@override_settings(PACKWISE={"RANKING_STRATEGY": "nope", "MAX_ITEMS_PER_ORDER": 10, "MIN_SUPPORT_RATIO": 0})
def test_misconfigured_default_strategy_is_reported():
    with pytest.raises(UnprocessableError):
        resolve_strategy(None)

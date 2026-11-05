"""Engine <-> Django integration: unit conversion and exact decimal boundaries.

These tests use unsaved model instances, so they need no database.
"""

from decimal import Decimal

import pytest

from inventory.models import Product, ShippingBox
from orders.models import OrderItem
from packing.algorithms import PackingStatus, Reason, ReasonCode
from packing.services.recommendation_service import describe_reason, evaluate_boxes, packing_details
from packing.services.units import cm_to_units, kg_to_units, units_to_cm, units_to_kg, volume_units_to_cm3
from packing.services.validation_service import box_to_container, validate_order_items

D = Decimal


def product(pk, length, width, height, weight="1", sku=None):
    return Product(
        pk=pk, sku=sku or f"P{pk}", name=f"P{pk}", length=D(length), width=D(width), height=D(height), weight=D(weight)
    )


def shipping_box(pk, length, width, height, max_weight="10", cost="10"):
    return ShippingBox(
        pk=pk,
        box_code=f"B{pk}",
        name=f"Box {pk}",
        internal_length=D(length),
        internal_width=D(width),
        internal_height=D(height),
        max_weight=D(max_weight),
        cost=D(cost),
    )


def evaluate(products_and_qty, boxes, strategy="lowest_cost"):
    lines = validate_order_items([OrderItem(product=p, quantity=q) for p, q in products_and_qty])
    return evaluate_boxes(lines, boxes, strategy=strategy)


# ---------------------------------------------------------------- units


def test_unit_conversion_is_exact():
    assert cm_to_units(D("12.34")) == 1234
    assert cm_to_units(D("0.01")) == 1
    assert kg_to_units(D("1.234")) == 1234
    assert kg_to_units(D("0.001")) == 1
    assert units_to_cm(1234) == 12.34
    assert units_to_kg(1500) == 1.5
    assert volume_units_to_cm3(1_000_000) == 1.0


def test_unit_conversion_refuses_to_round_silently():
    with pytest.raises(ValueError, match="precision"):
        cm_to_units(D("1.005"))
    with pytest.raises(ValueError, match="precision"):
        kg_to_units(D("0.0005"))


def test_box_to_container_scales_dimensions():
    container = box_to_container(shipping_box(1, "40.5", "30", "20.25", max_weight="15.5"))
    assert container.dims == (4050, 3000, 2025)
    assert container.max_weight == 15500
    assert container.container_id == 1


# ---------------------------------------------------------------- exact boundaries in real units


def test_product_exactly_the_box_size_fits():
    feasible, rejected = evaluate([(product(1, "40.00", "30.00", "20.00"), 1)], [shipping_box(1, "40", "30", "20")])
    assert [ev.box.pk for ev in feasible] == [1]
    assert feasible[0].result.utilization_percentage == 100.0
    assert rejected == []


def test_product_one_hundredth_of_a_cm_too_long_does_not_fit():
    feasible, rejected = evaluate([(product(1, "40.01", "30", "20"), 1)], [shipping_box(1, "40", "30", "20")])
    assert feasible == []
    assert rejected[0].status == PackingStatus.PROVEN_INFEASIBLE
    assert "P1 (40.01×30×20 cm) cannot fit" not in rejected[0].reasons[0]  # labels come from the service
    assert "cannot fit inside the box in any orientation" in rejected[0].reasons[0]


def test_weight_exactly_at_capacity_is_accepted_in_kg():
    feasible, _ = evaluate(
        [(product(1, "1", "1", "1", weight="2.5"), 4)], [shipping_box(1, "10", "10", "10", max_weight="10")]
    )
    assert len(feasible) == 1


def test_weight_one_gram_over_capacity_is_rejected():
    feasible, rejected = evaluate(
        [(product(1, "1", "1", "1", weight="2.5"), 3), (product(2, "1", "1", "1", weight="2.501"), 1)],
        [shipping_box(1, "10", "10", "10", max_weight="10")],
    )
    assert feasible == []
    assert rejected[0].reasons == ("Order weight 10.001 kg exceeds the box limit of 10.0 kg.",)


def test_two_halves_fill_the_box_with_decimal_dimensions():
    feasible, _ = evaluate([(product(1, "20.25", "30", "20"), 2)], [shipping_box(1, "40.5", "30", "20")])
    assert feasible[0].result.utilization_percentage == 100.0


# ---------------------------------------------------------------- details and descriptions


def test_packing_details_are_reported_in_centimetres():
    feasible, _ = evaluate([(product(7, "12.5", "10", "5", sku="WIDGET"), 2)], [shipping_box(1, "25", "10", "5")])
    details = packing_details(feasible[0].result)
    assert details["box_dimensions"] == {"length": 25.0, "width": 10.0, "height": 5.0}
    assert details["box_volume_cm3"] == 1250.0
    assert details["used_volume_cm3"] == 1250.0
    first, second = details["placements"]
    assert first["sequence"] == 1 and second["sequence"] == 2
    assert first["product_id"] == 7 and first["sku"] == "WIDGET"
    assert {first["position"]["x"], second["position"]["x"]} == {0.0, 12.5}
    assert first["dimensions"] == {"length": 12.5, "width": 10.0, "height": 5.0}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            Reason(ReasonCode.WEIGHT_EXCEEDED, required=15500, available=15000),
            "15.5 kg exceeds the box limit of 15.0 kg",
        ),
        (
            Reason(ReasonCode.VOLUME_EXCEEDED, required=2_000_000, available=1_000_000),
            "2.0 cm³ exceeds the box volume of 1.0 cm³",
        ),
        (Reason(ReasonCode.ITEM_TOO_LARGE, product_ids=(1,)), "LAPTOP cannot fit"),
        (Reason(ReasonCode.HEURISTIC_FAILURE, product_ids=(2,), required=3), "could not place 3 unit(s) of product 2"),
    ],
)
def test_reasons_are_described_in_real_units(reason, expected):
    assert expected in describe_reason(reason, {1: "LAPTOP"})


def test_ranking_with_unsaved_boxes_uses_lowest_cost():
    boxes = [shipping_box(1, "50", "50", "50", cost="30"), shipping_box(2, "20", "20", "20", cost="12")]
    feasible, _ = evaluate([(product(1, "10", "10", "10"), 1)], boxes)
    assert [ev.box.pk for ev in feasible] == [2, 1]

import random

import pytest

from packing.algorithms import (
    Container,
    InvalidPackingInput,
    Item,
    ItemLine,
    PackerConfig,
    PackingStatus,
    ReasonCode,
    expand_quantities,
    find_violations,
    necessary_condition_violations,
    pack,
)

from .helpers import box, item, items


def placements_by_id(result):
    return {p.item.item_id: p for p in result.placements}


# ---------------------------------------------------------------- basic feasibility


def test_single_product_fits():
    result = pack(items((4, 3, 2)), box(10, 10, 10))
    assert result.status is PackingStatus.FEASIBLE
    assert result.feasible
    (p,) = result.placements
    assert (p.x, p.y, p.z) == (0, 0, 0)
    assert result.unplaced == ()
    assert result.used_volume == 24
    assert result.container_volume == 1000
    assert result.utilization_percentage == 2.4
    assert result.attempts == 1
    assert result.sort_strategy == "volume_desc"
    assert result.execution_time_ms >= 0


def test_multiple_products_fit_without_overlap():
    container = box(10, 10, 10)
    result = pack(items((10, 10, 5), (5, 10, 5), (5, 5, 5), (5, 5, 5)), container)
    assert result.feasible
    assert len(result.placements) == 4
    assert find_violations(result.placements, container, ["p0#1", "p1#1", "p2#1", "p3#1"]) == []
    assert result.utilization_percentage == 100.0


def test_eight_cubes_fill_the_box_exactly():
    container = box(10, 10, 10)
    result = pack([item(f"cube#{n}", 5, 5, 5) for n in range(1, 9)], container)
    assert result.feasible
    assert result.utilization_percentage == 100.0
    corners = {(p.x, p.y, p.z) for p in result.placements}
    assert corners == {(x, y, z) for x in (0, 5) for y in (0, 5) for z in (0, 5)}


def test_twenty_seven_unit_cubes_fill_three_cubed_box():
    result = pack([item(f"u#{n}", 1, 1, 1) for n in range(27)], box(3, 3, 3))
    assert result.feasible
    assert result.used_volume == 27


# ---------------------------------------------------------------- rotation


def test_product_fits_only_after_rotation():
    result = pack(items((30, 10, 10)), box(10, 30, 10))
    assert result.feasible
    (p,) = result.placements
    assert (p.length, p.width, p.height) == (10, 30, 10)
    assert p.rotated
    assert p.orientation_label == "WLH"


def test_product_must_stand_upright_to_fit():
    result = pack(items((30, 10, 5)), box(10, 5, 30))
    (p,) = result.placements
    assert (p.length, p.width, p.height) == (10, 5, 30)
    assert p.orientation_label == "WHL"


def test_two_items_that_each_need_rotation():
    container = box(10, 20, 10)
    result = pack(items((20, 10, 5), (20, 10, 5)), container)
    assert result.feasible
    for p in result.placements:
        assert (p.length, p.width) == (10, 20)
        assert p.rotated
    assert sorted(p.z for p in result.placements) == [0, 5]


def test_unrotated_item_keeps_identity_orientation():
    (p,) = pack(items((5, 4, 3)), box(10, 10, 10)).placements
    assert not p.rotated
    assert p.orientation_label == "LWH"


# ---------------------------------------------------------------- proofs of infeasibility


def test_product_that_fits_no_orientation_is_proven_infeasible():
    # 25x25x1 is thin, but in a 30x20x20 box any orientation needs two sides >= 25.
    result = pack(items((25, 25, 1)), box(30, 20, 20))
    assert result.status is PackingStatus.PROVEN_INFEASIBLE
    assert result.placements == ()
    assert [i.item_id for i in result.unplaced] == ["p0#1"]
    (reason,) = result.reasons
    assert reason.code is ReasonCode.ITEM_TOO_LARGE
    assert reason.product_ids == ("p0",)
    assert reason.is_proof


def test_weight_capacity_exceeded_is_proven_infeasible():
    result = pack(items((1, 1, 1), (1, 1, 1), weight=600), box(10, 10, 10, max_weight=1000))
    assert result.status is PackingStatus.PROVEN_INFEASIBLE
    (reason,) = result.reasons
    assert reason.code is ReasonCode.WEIGHT_EXCEEDED
    assert (reason.required, reason.available) == (1200, 1000)


def test_weight_exactly_at_capacity_is_allowed():
    result = pack(items((1, 1, 1), (1, 1, 1), weight=500), box(10, 10, 10, max_weight=1000))
    assert result.feasible
    assert result.total_weight == 1000


def test_total_volume_exceeded_is_proven_infeasible():
    result = pack([item(f"c#{n}", 5, 5, 5) for n in range(9)], box(10, 10, 10))
    assert result.status is PackingStatus.PROVEN_INFEASIBLE
    assert [r.code for r in result.reasons] == [ReasonCode.VOLUME_EXCEEDED]


def test_all_violated_conditions_are_reported_together():
    reasons = necessary_condition_violations(
        # a is too long; a + b exceed the 1000-unit volume; 20 > 5 weight.
        [item("a#1", 50, 1, 1, weight=10), item("b#1", 10, 10, 10, weight=10)],
        box(10, 10, 10, max_weight=5),
    )
    assert [r.code for r in reasons] == [
        ReasonCode.WEIGHT_EXCEEDED,
        ReasonCode.ITEM_TOO_LARGE,
        ReasonCode.VOLUME_EXCEEDED,
    ]


def test_heuristic_failure_is_not_reported_as_proof():
    """Two 6-cubes cannot share a 10-cube, but the cheap necessary conditions all pass.

    The engine must say "heuristic failure", not "proven infeasible".
    """
    result = pack(items((6, 6, 6), (6, 6, 6)), box(10, 10, 10))
    assert result.status is PackingStatus.HEURISTIC_FAILURE
    assert not result.feasible
    assert len(result.placements) == 1
    assert len(result.unplaced) == 1
    (reason,) = result.reasons
    assert reason.code is ReasonCode.HEURISTIC_FAILURE
    assert not reason.is_proof
    assert reason.required == 1
    assert result.attempts == 3
    # The partial packing it reports is still physically valid.
    assert find_violations(result.placements, result.container) == []


# ---------------------------------------------------------------- exact boundaries


def test_item_exactly_the_size_of_the_box_fits():
    result = pack(items((10, 20, 30)), box(10, 20, 30))
    assert result.feasible
    assert result.utilization_percentage == 100.0


def test_item_one_unit_too_long_does_not_fit():
    result = pack(items((10, 20, 31)), box(10, 20, 30))
    assert result.status is PackingStatus.PROVEN_INFEASIBLE


def test_items_exactly_filling_one_axis_touch_but_do_not_overlap():
    container = box(10, 10, 10)
    result = pack(items((5, 10, 10), (5, 10, 10)), container)
    assert result.feasible
    a, b = sorted(result.placements, key=lambda p: (p.x, p.y, p.z))
    assert a.cuboid.x2 == b.x or a.cuboid.y2 == b.y or a.cuboid.z2 == b.z
    assert not a.cuboid.intersects(b.cuboid)


# ---------------------------------------------------------------- quantities and identity


def test_quantities_are_expanded_into_individual_items():
    expanded = expand_quantities(
        [
            ItemLine("laptop", 35, 24, 3, 2000, quantity=2, sku="LAP"),
            ItemLine("mouse", 12, 7, 4, 100, quantity=3, sku="MOU"),
        ]
    )
    assert [i.item_id for i in expanded] == ["laptop#1", "laptop#2", "mouse#1", "mouse#2", "mouse#3"]
    assert {i.product_id for i in expanded} == {"laptop", "mouse"}
    assert expanded[0].sku == "LAP"


def test_duplicate_order_lines_are_rejected():
    line = ItemLine(1, 1, 1, 1, 1, quantity=1)
    with pytest.raises(InvalidPackingInput, match="Duplicate"):
        expand_quantities([line, line])


def test_every_item_is_placed_exactly_once():
    lines = [ItemLine("a", 4, 4, 4, 1, quantity=5), ItemLine("b", 2, 2, 2, 1, quantity=7)]
    expanded = expand_quantities(lines)
    container = box(12, 12, 12)
    result = pack(expanded, container)
    assert result.feasible
    placed_ids = [p.item.item_id for p in result.placements]
    assert sorted(placed_ids) == sorted(i.item_id for i in expanded)
    assert len(placed_ids) == len(set(placed_ids)) == 12
    assert find_violations(result.placements, container, placed_ids) == []


# ---------------------------------------------------------------- determinism


def test_results_are_deterministic_regardless_of_input_order():
    expanded = expand_quantities(
        [
            ItemLine("a", 7, 3, 2, 1, quantity=3),
            ItemLine("b", 4, 4, 4, 1, quantity=2),
            ItemLine("c", 9, 2, 2, 1, quantity=2),
        ]
    )
    container = box(12, 10, 8)
    reference = pack(expanded, container)
    shuffled = list(expanded)
    for seed in range(5):
        random.Random(seed).shuffle(shuffled)
        again = pack(shuffled, container)
        assert placements_by_id(again) == placements_by_id(reference)


# ---------------------------------------------------------------- multi-start


def test_falls_back_to_another_sort_order_when_the_first_fails():
    """Volume-first ordering cannot pack this order; longest-edge-first can.

    Instance found by a seeded search (seed 75). It shows the multi-start
    fallback rescuing a case the primary ordering misses.
    """
    container = box(7, 8, 5)
    order = items((1, 8, 3), (1, 6, 1), (7, 5, 3))
    only_volume = pack(order, container, PackerConfig(sort_strategies=("volume_desc",)))
    assert only_volume.status is PackingStatus.HEURISTIC_FAILURE

    with_fallback = pack(order, container)
    assert with_fallback.feasible
    assert with_fallback.attempts == 2
    assert with_fallback.sort_strategy == "longest_edge_desc"
    assert find_violations(with_fallback.placements, container, [i.item_id for i in order]) == []


# ---------------------------------------------------------------- support constraint


def test_overhang_is_allowed_by_default_but_can_be_forbidden():
    """An 8x8 plate can only go on top of a 5x5 cube, covering 39% of its base."""
    container = box(10, 10, 6)
    order = items((5, 5, 5), (8, 8, 1))
    config = PackerConfig(sort_strategies=("volume_desc",))
    relaxed = pack(order, container, config)
    assert relaxed.feasible
    plate = placements_by_id(relaxed)["p1#1"]
    assert plate.z == 5

    strict = pack(order, container, PackerConfig(sort_strategies=("volume_desc",), min_support_ratio=0.5))
    assert strict.status is PackingStatus.HEURISTIC_FAILURE
    assert [i.item_id for i in strict.unplaced] == ["p1#1"]


def test_fully_supported_stack_passes_strict_support_check():
    result = pack(items((10, 10, 2), (10, 10, 2), (4, 4, 4)), box(10, 10, 8), PackerConfig(min_support_ratio=1.0))
    assert result.feasible
    for p in result.placements:
        below = [q for q in result.placements if q.cuboid.z2 == p.z]
        assert p.z == 0 or below


# ---------------------------------------------------------------- input validation


@pytest.mark.parametrize("bad", [0, -5, 2.5, True, "10", None])
def test_invalid_item_dimensions_are_rejected(bad):
    with pytest.raises(InvalidPackingInput):
        Item("x#1", "x", bad, 1, 1, 1)


@pytest.mark.parametrize("bad", [0, -1, 1.5])
def test_invalid_weights_and_quantities_are_rejected(bad):
    with pytest.raises(InvalidPackingInput):
        Item("x#1", "x", 1, 1, 1, bad)
    with pytest.raises(InvalidPackingInput):
        ItemLine("x", 1, 1, 1, 1, quantity=bad)


@pytest.mark.parametrize("field", ["length", "width", "height", "max_weight"])
def test_invalid_container_values_are_rejected(field):
    values = {"length": 10, "width": 10, "height": 10, "max_weight": 10}
    values[field] = 0
    with pytest.raises(InvalidPackingInput):
        Container("box", **values)


def test_empty_item_list_is_rejected():
    with pytest.raises(InvalidPackingInput, match="At least one item"):
        pack([], box(1, 1, 1))


def test_duplicate_item_ids_are_rejected():
    with pytest.raises(InvalidPackingInput, match="unique"):
        pack([item("a#1", 1, 1, 1), item("a#1", 1, 1, 1)], box(5, 5, 5))


def test_empty_item_id_is_rejected():
    with pytest.raises(InvalidPackingInput):
        Item("", "x", 1, 1, 1, 1)


@pytest.mark.parametrize(
    "kwargs",
    [{"sort_strategies": ()}, {"sort_strategies": ("nope",)}, {"min_support_ratio": 1.5}],
)
def test_invalid_packer_config_is_rejected(kwargs):
    with pytest.raises(InvalidPackingInput):
        PackerConfig(**kwargs)

from decimal import Decimal
from fractions import Fraction

import pytest

from packing.algorithms import (
    Cuboid,
    InvalidPackingInput,
    RankableBox,
    best_short_side_fit,
    rank_boxes,
)


def test_bssf_returns_sorted_leftovers():
    space = Cuboid(0, 0, 0, 10, 20, 30)
    assert best_short_side_fit(space, (10, 15, 5)) == (0, 5, 25)
    assert best_short_side_fit(space, (10, 20, 30)) == (0, 0, 0)


def test_bssf_prefers_the_snugger_fit():
    tight = best_short_side_fit(Cuboid(0, 0, 0, 5, 9, 9), (5, 5, 5))
    loose = best_short_side_fit(Cuboid(0, 0, 0, 9, 9, 9), (5, 5, 5))
    assert tight < loose


def rb(box_id, cost, used, volume):
    return RankableBox(box_id, Decimal(cost), Fraction(used, volume), volume)


def test_lowest_cost_strategy_picks_cheapest_then_fullest():
    boxes = [rb(1, "50", 100, 1000), rb(2, "30", 100, 4000), rb(3, "30", 100, 2000)]
    assert [b.box_id for b in rank_boxes(boxes, "lowest_cost")] == [3, 2, 1]


def test_equal_cost_and_equal_volume_falls_back_to_box_id():
    boxes = [rb(9, "30", 100, 2000), rb(4, "30", 100, 2000)]
    assert [b.box_id for b in rank_boxes(boxes)] == [4, 9]


def test_best_utilization_strategy():
    boxes = [rb(1, "10", 100, 4000), rb(2, "90", 100, 1000), rb(3, "50", 100, 1000)]
    assert [b.box_id for b in rank_boxes(boxes, "best_utilization")] == [3, 2, 1]


def test_smallest_box_strategy():
    boxes = [rb(1, "10", 100, 4000), rb(2, "90", 100, 1000), rb(3, "50", 100, 1500)]
    assert [b.box_id for b in rank_boxes(boxes, "smallest_box")] == [2, 3, 1]


def test_unknown_strategy_is_rejected():
    with pytest.raises(InvalidPackingInput, match="Unknown ranking strategy"):
        rank_boxes([], "random")

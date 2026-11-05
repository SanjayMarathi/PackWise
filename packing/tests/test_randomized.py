"""Seeded randomized checks: the packer must never produce an invalid packing.

Each seed builds a random order and box. Whatever the outcome, the result must
be consistent with an *independent* recomputation of the physical constraints.
Seeds are fixed, so failures are reproducible.
"""

import random

import pytest

from packing.algorithms import (
    Container,
    PackingStatus,
    ReasonCode,
    find_violations,
    fits_in_some_orientation,
    pack,
)

from .helpers import item


def random_case(seed: int):
    rng = random.Random(seed)
    container = Container(
        "box",
        rng.randint(5, 40),
        rng.randint(5, 40),
        rng.randint(5, 40),
        max_weight=rng.randint(20, 400),
    )
    order = [
        item(f"p{n}#1", rng.randint(1, 20), rng.randint(1, 20), rng.randint(1, 20), weight=rng.randint(1, 40))
        for n in range(rng.randint(1, 15))
    ]
    return container, order


@pytest.mark.parametrize("seed", range(300))
def test_random_orders_never_produce_invalid_packings(seed):
    container, order = random_case(seed)
    result = pack(order, container)

    assert find_violations(result.placements, container) == []
    placed = {p.item.item_id for p in result.placements}
    unplaced = {i.item_id for i in result.unplaced}
    assert placed.isdisjoint(unplaced)
    assert placed | unplaced == {i.item_id for i in order}

    weight_ok = sum(i.weight for i in order) <= container.max_weight
    dims_ok = all(fits_in_some_orientation(i.dims, container.dims) for i in order)
    volume_ok = sum(i.volume for i in order) <= container.volume

    if result.status is PackingStatus.FEASIBLE:
        assert unplaced == set()
        assert weight_ok and dims_ok and volume_ok
        assert result.used_volume == sum(i.volume for i in order)
    elif result.status is PackingStatus.PROVEN_INFEASIBLE:
        codes = {r.code for r in result.reasons}
        assert (ReasonCode.WEIGHT_EXCEEDED in codes) == (not weight_ok)
        assert (ReasonCode.ITEM_TOO_LARGE in codes) == (not dims_ok)
        assert (ReasonCode.VOLUME_EXCEEDED in codes) == (not volume_ok)
    else:
        # A heuristic failure is only allowed when no cheap proof applies.
        assert weight_ok and dims_ok and volume_ok
        assert unplaced


def test_engine_handles_a_large_order_quickly():
    """150 mixed items. A guard against accidental super-quadratic blow-ups."""
    rng = random.Random(42)
    order = [item(f"p{n}#1", rng.randint(2, 8), rng.randint(2, 8), rng.randint(2, 8)) for n in range(150)]
    result = pack(order, Container("big", 60, 60, 60, max_weight=10_000))
    assert result.feasible
    assert result.execution_time_ms < 15_000

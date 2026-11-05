"""Scoring rules: how to place an item, and how to rank feasible boxes."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .domain import InvalidPackingInput
from .geometry import Cuboid


def best_short_side_fit(space: Cuboid, dims: tuple[int, int, int]) -> tuple[int, int, int]:
    """Best Short Side Fit score for putting an item with ``dims`` into ``space``.

    Returns the leftover gap on each axis, sorted ascending as
    ``(short, middle, long)``. Lower is better when compared
    lexicographically. The item goes where its tightest side fits most
    snugly, with ties broken on the next-tightest side. This is the natural
    3D extension of 2D BSSF. The caller must already have checked that the
    item fits.
    """
    a, b, c = sorted((space.length - dims[0], space.width - dims[1], space.height - dims[2]))
    return (a, b, c)


@dataclass(frozen=True, slots=True)
class RankableBox:
    """The facts about one feasible box that the ranking strategies need."""

    box_id: Hashable
    cost: Decimal
    utilization: Fraction  # exact, so equal-volume ties are real ties
    volume: int


RankKey = Callable[[RankableBox], tuple]

#: Box ranking strategies. Each key sorts ascending, and the last element
#: (box_id) guarantees a deterministic total order.
RANKING_STRATEGIES: dict[str, RankKey] = {
    # Cheapest box. For equal cost, prefer the fuller box, then the smaller box.
    "lowest_cost": lambda b: (b.cost, -b.utilization, b.volume, b.box_id),
    # Fullest box (least void fill). For equal utilisation, prefer the cheaper box.
    "best_utilization": lambda b: (-b.utilization, b.cost, b.volume, b.box_id),
    # Physically smallest box (e.g. dimensional-weight couriers). Then the cheaper box.
    "smallest_box": lambda b: (b.volume, b.cost, -b.utilization, b.box_id),
}

DEFAULT_RANKING_STRATEGY = "lowest_cost"


def rank_boxes(boxes: Iterable[RankableBox], strategy: str = DEFAULT_RANKING_STRATEGY) -> list[RankableBox]:
    try:
        key = RANKING_STRATEGIES[strategy]
    except KeyError:
        choices = ", ".join(sorted(RANKING_STRATEGIES))
        raise InvalidPackingInput(f"Unknown ranking strategy {strategy!r}; choose one of: {choices}.") from None
    return sorted(boxes, key=key)

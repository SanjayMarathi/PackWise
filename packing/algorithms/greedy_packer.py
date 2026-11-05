"""Greedy 3D bin-packing: Maximal Empty Spaces + Best Short Side Fit.

Pipeline for one container (see ``pack``):

1. Validate input (done by the domain dataclasses) and require unique item ids.
2. **Necessary-condition checks.** If the total weight exceeds capacity, any
   item fits no orientation, or the total item volume exceeds the box volume,
   then no arrangement can exist. The result is ``PROVEN_INFEASIBLE``.
3. **Greedy passes.** Sort the items deterministically (largest and
   hardest-to-place first). For each item, try every free space and every
   unique orientation, and pick the Best Short Side Fit placement at the
   space's minimum corner. Then update the maximal empty spaces.
4. If a pass cannot place every item, retry with the next sort order
   (volume, then longest edge, then footprint). Cheap multi-start rescues
   many cases a single order misses.
5. **Verification.** The final placements are checked by an independent AABB
   collision checker before being reported as ``FEASIBLE``.

A ``HEURISTIC_FAILURE`` means only that this heuristic found no
arrangement. 3D bin packing is NP-hard, and the engine never presents a
heuristic failure as proof of impossibility.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from .collision import assert_valid_packing
from .domain import (
    Container,
    InvalidPackingInput,
    Item,
    ItemLine,
    PackingResult,
    PackingStatus,
    Placement,
    Reason,
    ReasonCode,
)
from .free_space import MaximalSpaceManager
from .geometry import Cuboid, overlap_area_xy
from .orientations import fits_in_some_orientation, unique_orientations
from .scoring import best_short_side_fit

ALGORITHM_NAME = "maximal-empty-spaces/best-short-side-fit"
ENGINE_VERSION = "1.0.0"

SortKey = Callable[[Item], tuple]


def _identity(item: Item) -> tuple[str, str]:
    return (str(item.product_id), item.item_id)


#: Deterministic item orderings. Larger and harder-to-place items go first.
#: Ties end on (product_id, item_id), so the order is always total.
SORT_STRATEGIES: dict[str, SortKey] = {
    "volume_desc": lambda i: (-i.volume, -i.sorted_dims[2], -i.sorted_dims[1], *_identity(i)),
    "longest_edge_desc": lambda i: (
        -i.sorted_dims[2],
        -i.sorted_dims[1],
        -i.volume,
        *_identity(i),
    ),
    "base_area_desc": lambda i: (
        -(i.sorted_dims[2] * i.sorted_dims[1]),
        -i.volume,
        *_identity(i),
    ),
}


@dataclass(frozen=True, slots=True)
class PackerConfig:
    #: Item orderings to try, in order. The first one that packs everything wins.
    sort_strategies: tuple[str, ...] = tuple(SORT_STRATEGIES)
    #: Minimum share of an item's base that must rest on the floor or on other
    #: items' top faces. 0 disables the check. E-commerce boxes are usually
    #: void-filled, so overhang is allowed by default.
    min_support_ratio: float = 0.0
    #: Re-verify the result with the independent collision checker.
    verify: bool = True

    def __post_init__(self) -> None:
        if not self.sort_strategies:
            raise InvalidPackingInput("At least one sort strategy is required.")
        unknown = [s for s in self.sort_strategies if s not in SORT_STRATEGIES]
        if unknown:
            raise InvalidPackingInput(f"Unknown sort strategies: {unknown}.")
        if not 0.0 <= self.min_support_ratio <= 1.0:
            raise InvalidPackingInput("min_support_ratio must be between 0 and 1.")


DEFAULT_CONFIG = PackerConfig()


def expand_quantities(lines: Iterable[ItemLine]) -> list[Item]:
    """Turn order lines into one ``Item`` per physical unit.

    ``Laptop x2, Mouse x3`` becomes five items whose ids (``"<product>#<n>"``)
    keep a reference to their product.
    """
    items: list[Item] = []
    seen: set[object] = set()
    for line in lines:
        if line.product_id in seen:
            raise InvalidPackingInput(f"Duplicate order line for product {line.product_id}.")
        seen.add(line.product_id)
        for n in range(1, line.quantity + 1):
            items.append(
                Item(
                    item_id=f"{line.product_id}#{n}",
                    product_id=line.product_id,
                    sku=line.sku,
                    length=line.length,
                    width=line.width,
                    height=line.height,
                    weight=line.weight,
                )
            )
    return items


def necessary_condition_violations(items: Sequence[Item], container: Container) -> list[Reason]:
    """Reasons that **prove** the items cannot be packed into ``container``.

    An empty list does *not* prove that a packing exists. It only means these
    cheap necessary conditions hold.
    """
    reasons: list[Reason] = []

    total_weight = sum(i.weight for i in items)
    if total_weight > container.max_weight:
        reasons.append(Reason(ReasonCode.WEIGHT_EXCEEDED, required=total_weight, available=container.max_weight))

    too_large = [i for i in items if not fits_in_some_orientation(i.dims, container.dims)]
    if too_large:
        product_ids = tuple(dict.fromkeys(i.product_id for i in too_large))
        reasons.append(Reason(ReasonCode.ITEM_TOO_LARGE, product_ids=product_ids))

    total_volume = sum(i.volume for i in items)
    if total_volume > container.volume:
        reasons.append(Reason(ReasonCode.VOLUME_EXCEEDED, required=total_volume, available=container.volume))
    return reasons


def pack(items: Sequence[Item], container: Container, config: PackerConfig = DEFAULT_CONFIG) -> PackingResult:
    """Try to pack ``items`` into ``container``. See the module docstring."""
    started = time.perf_counter()
    items = tuple(items)
    if not items:
        raise InvalidPackingInput("At least one item is required.")
    item_ids = [i.item_id for i in items]
    if len(set(item_ids)) != len(item_ids):
        raise InvalidPackingInput("Item ids must be unique.")

    total_weight = sum(i.weight for i in items)
    total_volume = sum(i.volume for i in items)

    def result(status, placements, unplaced, reasons=(), strategy=None, attempts=0):
        return PackingResult(
            container=container,
            status=status,
            placements=tuple(placements),
            unplaced=tuple(unplaced),
            total_weight=total_weight,
            total_item_volume=total_volume,
            reasons=tuple(reasons),
            sort_strategy=strategy,
            attempts=attempts,
            execution_time_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    proofs = necessary_condition_violations(items, container)
    if proofs:
        return result(PackingStatus.PROVEN_INFEASIBLE, (), items, proofs)

    best: tuple[str, list[Placement], list[Item]] | None = None
    for attempt, strategy in enumerate(config.sort_strategies, start=1):
        ordered = sorted(items, key=SORT_STRATEGIES[strategy])
        placements, unplaced = _greedy_pass(ordered, container, config.min_support_ratio)
        if not unplaced:
            if config.verify:
                assert_valid_packing(placements, container, expected_item_ids=item_ids)
            return result(PackingStatus.FEASIBLE, placements, (), (), strategy, attempt)
        if best is None or _placed_volume(placements) > _placed_volume(best[1]):
            best = (strategy, placements, unplaced)

    if best is None:  # unreachable: PackerConfig guarantees at least one strategy
        raise InvalidPackingInput("No sort strategy was attempted.")
    strategy, placements, unplaced = best
    if config.verify:
        assert_valid_packing(placements, container)
    failure = Reason(
        ReasonCode.HEURISTIC_FAILURE,
        product_ids=tuple(dict.fromkeys(i.product_id for i in unplaced)),
        required=len(unplaced),
    )
    return result(
        PackingStatus.HEURISTIC_FAILURE,
        placements,
        unplaced,
        (failure,),
        strategy,
        len(config.sort_strategies),
    )


def _placed_volume(placements: Sequence[Placement]) -> int:
    return sum(p.item.volume for p in placements)


def _greedy_pass(
    ordered: Sequence[Item], container: Container, min_support_ratio: float
) -> tuple[list[Placement], list[Item]]:
    spaces = MaximalSpaceManager(container.cuboid)
    placements: list[Placement] = []
    unplaced: list[Item] = []

    # suffix_min[i] = (smallest side, smallest volume) over ordered[i:]
    suffix_min: list[tuple[int, int]] = [(0, 0)] * (len(ordered) + 1)
    running: tuple[int, int] | None = None
    for i in range(len(ordered) - 1, -1, -1):
        item = ordered[i]
        current = (item.sorted_dims[0], item.volume)
        running = current if running is None else (min(running[0], current[0]), min(running[1], current[1]))
        suffix_min[i] = running

    for index, item in enumerate(ordered):
        placement = _best_placement(item, spaces.spaces, placements, min_support_ratio)
        if placement is None:
            unplaced.append(item)
            continue
        placements.append(placement)
        spaces.occupy(placement.cuboid)
        if index + 1 < len(ordered):
            min_side, min_volume = suffix_min[index + 1]
            spaces.discard_unusable(min_side, min_volume)
    return placements, unplaced


def _best_placement(
    item: Item,
    spaces: Sequence[Cuboid],
    placements: Sequence[Placement],
    min_support_ratio: float,
) -> Placement | None:
    """Best Short Side Fit over every (free space, orientation) pair.

    The key is (BSSF score, z, y, x, orientation index). Lower placements win
    ties, which keeps loads low and stable, and the key makes the choice fully
    deterministic regardless of the order in which spaces are visited.
    """
    best_key: tuple | None = None
    best_choice = None
    orientations = unique_orientations(item.dims)
    for space in spaces:
        if space.volume < item.volume:
            continue
        for index, orientation in enumerate(orientations):
            length, width, height = orientation.dims
            if not space.can_hold(length, width, height):
                continue
            if min_support_ratio > 0 and not _is_supported(
                Cuboid(space.x, space.y, space.z, length, width, height),
                placements,
                min_support_ratio,
            ):
                continue
            key = (best_short_side_fit(space, orientation.dims), space.z, space.y, space.x, index)
            if best_key is None or key < best_key:
                best_key = key
                best_choice = (space, orientation)

    if best_choice is None:
        return None
    space, orientation = best_choice
    length, width, height = orientation.dims
    return Placement(
        item=item,
        x=space.x,
        y=space.y,
        z=space.z,
        length=length,
        width=width,
        height=height,
        orientation=orientation.permutation,
    )


def _is_supported(candidate: Cuboid, placements: Sequence[Placement], ratio: float) -> bool:
    """True when enough of the candidate's base rests on the floor or on items."""
    if candidate.z == 0:
        return True
    base_area = candidate.length * candidate.width
    supported = sum(overlap_area_xy(candidate, p.cuboid) for p in placements if p.cuboid.z2 == candidate.z)
    # Items whose tops are at the same height cannot overlap each other in XY,
    # so summing the overlaps never double-counts support.
    return supported >= ratio * base_area

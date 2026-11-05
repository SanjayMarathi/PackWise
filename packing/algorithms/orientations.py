"""Axis-aligned orientations of a rectangular item."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .domain import AXIS_LABELS

# The six permutations of (L, W, H), in a fixed order so results are deterministic:
# (L,W,H) (L,H,W) (W,L,H) (W,H,L) (H,L,W) (H,W,L)
PERMUTATIONS: tuple[tuple[int, int, int], ...] = (
    (0, 1, 2),
    (0, 2, 1),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
    (2, 1, 0),
)


@dataclass(frozen=True, slots=True)
class Orientation:
    dims: tuple[int, int, int]
    """Extents along the container's x, y and z axes."""
    permutation: tuple[int, int, int]
    """``permutation[k]`` is the original dimension index placed along axis ``k``."""

    @property
    def label(self) -> str:
        return "".join(AXIS_LABELS[i] for i in self.permutation)


@lru_cache(maxsize=4096)
def unique_orientations(dims: tuple[int, int, int]) -> tuple[Orientation, ...]:
    """All distinct axis-aligned orientations of an item with extents ``dims``.

    A cuboid has at most six. Equal dimensions produce duplicate extent
    tuples, which are dropped: a cube has one orientation and a square
    prism has three. The first permutation producing a given extent tuple
    wins, so the identity orientation is always kept.
    """
    seen: set[tuple[int, int, int]] = set()
    result: list[Orientation] = []
    for perm in PERMUTATIONS:
        oriented = (dims[perm[0]], dims[perm[1]], dims[perm[2]])
        if oriented in seen:
            continue
        seen.add(oriented)
        result.append(Orientation(oriented, perm))
    return tuple(result)


def fits_in_some_orientation(item_dims: tuple[int, int, int], space_dims: tuple[int, int, int]) -> bool:
    """Exact test for whether an item fits a space in *any* axis-aligned rotation.

    Sort both dimension triples. The item fits in some orientation if and
    only if each sorted item dimension is <= the matching sorted space
    dimension. If the sorted pairing works, that pairing is itself a valid
    orientation. Conversely, if some orientation works, the k-th smallest
    item dimension is <= the k-th smallest space dimension for every k. So
    a ``False`` result is a proof, not a heuristic guess.
    """
    return all(a <= b for a, b in zip(sorted(item_dims), sorted(space_dims), strict=True))

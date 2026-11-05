"""3D Maximal Empty Spaces (MES) free-space management.

The empty region of the box is represented as a list of *maximal* empty
cuboids. These may overlap each other, but none of them contains another.
Initially the whole box is one empty space. When an item is placed:

1. Every free space that intersects the item is removed and replaced by up to
   six slabs: the parts of that space lying entirely to the left, right,
   front, back, below and above the item (``split_space``).
2. Degenerate slabs, duplicates and slabs contained in another free space are
   discarded (``remove_redundant``).

Invariants (checked by the test suite):

* no free space overlaps a placed item, so an item placed fully inside a free
  space cannot collide with anything;
* the union of the free spaces is exactly the unoccupied region of the box,
  so no usable gap is lost;
* no free space is contained in another one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .geometry import Cuboid


def split_space(space: Cuboid, obstacle: Cuboid) -> list[Cuboid]:
    """Return the maximal parts of ``space`` that do not intersect ``obstacle``.

    Each part keeps the full extent of ``space`` on the two other axes, so the
    parts overlap one another. That is what makes them maximal. None of them
    overlaps the obstacle. If the two cuboids do not intersect, ``space`` is
    returned unchanged.
    """
    if not space.intersects(obstacle):
        return [space]

    s, o = space, obstacle
    parts: list[Cuboid] = []
    if o.x > s.x:  # slab on the low-x side
        parts.append(Cuboid(s.x, s.y, s.z, o.x - s.x, s.width, s.height))
    if o.x2 < s.x2:  # slab on the high-x side
        parts.append(Cuboid(o.x2, s.y, s.z, s.x2 - o.x2, s.width, s.height))
    if o.y > s.y:
        parts.append(Cuboid(s.x, s.y, s.z, s.length, o.y - s.y, s.height))
    if o.y2 < s.y2:
        parts.append(Cuboid(s.x, o.y2, s.z, s.length, s.y2 - o.y2, s.height))
    if o.z > s.z:
        parts.append(Cuboid(s.x, s.y, s.z, s.length, s.width, o.z - s.z))
    if o.z2 < s.z2:
        parts.append(Cuboid(s.x, s.y, o.z2, s.length, s.width, s.z2 - o.z2))
    return parts


def remove_redundant(candidates: Iterable[Cuboid], existing: Sequence[Cuboid] = ()) -> list[Cuboid]:
    """Filter ``candidates`` down to the maximal ones.

    Drops degenerate cuboids, exact duplicates, and any candidate contained in
    an ``existing`` space or in another candidate. The result is sorted.
    """
    unique = sorted({c for c in candidates if not c.is_degenerate})
    kept: list[Cuboid] = []
    for index, candidate in enumerate(unique):
        if any(space.contains(candidate) for space in existing):
            continue
        # ``unique`` has no duplicates, so containment here is strict.
        if any(i != index and other.contains(candidate) for i, other in enumerate(unique)):
            continue
        kept.append(candidate)
    return kept


class MaximalSpaceManager:
    """Maintains the list of maximal empty spaces inside one container."""

    def __init__(self, container: Cuboid) -> None:
        if container.is_degenerate:
            raise ValueError("Container must have positive extents.")
        self._spaces: list[Cuboid] = [container]

    @property
    def spaces(self) -> tuple[Cuboid, ...]:
        """Current free spaces in deterministic (x, y, z, extent) order."""
        return tuple(self._spaces)

    def occupy(self, placed: Cuboid) -> None:
        """Update the free spaces after ``placed`` has been put in the box."""
        untouched: list[Cuboid] = []
        fragments: list[Cuboid] = []
        for space in self._spaces:
            if space.intersects(placed):
                fragments.extend(split_space(space, placed))
            else:
                untouched.append(space)
        # Untouched spaces were already mutually maximal. A fragment is a
        # subset of the space it came from, so it can never strictly contain
        # an untouched space. Fragments therefore only need checking against
        # the untouched spaces and against each other.
        self._spaces = sorted(untouched + remove_redundant(fragments, untouched))

    def discard_unusable(self, min_side: int, min_volume: int) -> None:
        """Drop spaces too small for any item still waiting to be packed.

        Every future free space is a subset of a current one, so a space that
        cannot hold the smallest remaining item now never will. Removing it
        is safe and keeps the space list (and the running time) small.
        """
        self._spaces = [
            s for s in self._spaces if min(s.length, s.width, s.height) >= min_side and s.volume >= min_volume
        ]

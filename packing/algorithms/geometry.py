"""Axis-aligned cuboid geometry used by the packing engine.

Coordinates and extents are integers in engine units (see
``packing.services.units``). The origin is the inner bottom-left-back corner of
the box; ``x`` runs along the box length, ``y`` along its width and ``z`` along
its height.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Cuboid:
    """An axis-aligned cuboid anchored at its minimum corner ``(x, y, z)``.

    ``order=True`` gives a total, deterministic ordering (by x, y, z, then
    extents), which the engine relies on for reproducible results.
    """

    x: int
    y: int
    z: int
    length: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.length

    @property
    def y2(self) -> int:
        return self.y + self.width

    @property
    def z2(self) -> int:
        return self.z + self.height

    @property
    def dims(self) -> tuple[int, int, int]:
        return (self.length, self.width, self.height)

    @property
    def volume(self) -> int:
        return self.length * self.width * self.height

    @property
    def is_degenerate(self) -> bool:
        """True when any extent is zero or negative (the cuboid has no volume)."""
        return self.length <= 0 or self.width <= 0 or self.height <= 0

    def intersects(self, other: Cuboid) -> bool:
        """True when the two cuboids share a region of *positive* volume.

        Strict inequalities mean that cuboids which only touch along a face,
        an edge or a corner do **not** intersect. Touching is allowed.
        """
        return (
            self.x < other.x2
            and other.x < self.x2
            and self.y < other.y2
            and other.y < self.y2
            and self.z < other.z2
            and other.z < self.z2
        )

    def contains(self, other: Cuboid) -> bool:
        """True when ``other`` lies entirely inside (or exactly on) this cuboid."""
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.z <= other.z
            and other.x2 <= self.x2
            and other.y2 <= self.y2
            and other.z2 <= self.z2
        )

    def can_hold(self, length: int, width: int, height: int) -> bool:
        """True when an item with these (already oriented) extents fits inside."""
        return length <= self.length and width <= self.width and height <= self.height


def overlap_area_xy(a: Cuboid, b: Cuboid) -> int:
    """Area of the overlap of the two cuboids' footprints on the XY plane."""
    dx = min(a.x2, b.x2) - max(a.x, b.x)
    dy = min(a.y2, b.y2) - max(a.y, b.y)
    if dx <= 0 or dy <= 0:
        return 0
    return dx * dy

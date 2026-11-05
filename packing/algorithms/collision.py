"""Independent verification of a packing (AABB collision detection).

The packer avoids overlaps by construction, through its free-space
invariants. This module checks the final placement again using only the
placements and the container, so a bug in free-space management cannot slip
through silently.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .domain import Container, Placement


class PackingIntegrityError(RuntimeError):
    """Raised when a produced packing violates a physical constraint (an engine bug)."""

    def __init__(self, violations: Sequence[Violation]) -> None:
        self.violations = tuple(violations)
        summary = "; ".join(v.message for v in self.violations[:5])
        super().__init__(f"Invalid packing ({len(self.violations)} violation(s)): {summary}")


@dataclass(frozen=True, slots=True)
class Violation:
    kind: str  # out_of_bounds | overlap | bad_orientation | duplicate | missing | unexpected
    item_ids: tuple[str, ...]
    message: str


def find_violations(
    placements: Sequence[Placement],
    container: Container,
    expected_item_ids: Iterable[str] | None = None,
) -> list[Violation]:
    """Return every constraint the placements break (an empty list means valid).

    Checks that:

    * every item lies inside the container's boundaries;
    * every placed extent is a rotation of the item's real dimensions;
    * no two items overlap with positive volume (touching faces are allowed);
    * no item is placed twice and, if ``expected_item_ids`` is given, every
      expected item is placed exactly once.
    """
    violations: list[Violation] = []
    bounds = container.cuboid

    for p in placements:
        item_id = p.item.item_id
        if not bounds.contains(p.cuboid):
            violations.append(Violation("out_of_bounds", (item_id,), f"{item_id} extends beyond the box."))
        oriented = tuple(p.item.dims[i] for i in p.orientation)
        if sorted(p.orientation) != [0, 1, 2] or oriented != (p.length, p.width, p.height):
            violations.append(
                Violation(
                    "bad_orientation",
                    (item_id,),
                    f"{item_id} extents {(p.length, p.width, p.height)} are not a rotation of {p.item.dims}.",
                )
            )

    # Sweep and prune along x: after sorting by x, b can only overlap a while b starts
    # before a ends. This avoids comparing every pair in sparse layouts.
    ordered = sorted(placements, key=lambda p: (p.x, p.item.item_id))
    for i, a in enumerate(ordered):
        a_box = a.cuboid
        for b in ordered[i + 1 :]:
            if b.x >= a_box.x2:
                break
            if a_box.intersects(b.cuboid):
                violations.append(
                    Violation(
                        "overlap",
                        (a.item.item_id, b.item.item_id),
                        f"{a.item.item_id} overlaps {b.item.item_id}.",
                    )
                )

    counts = Counter(p.item.item_id for p in placements)
    for item_id, count in sorted(counts.items()):
        if count > 1:
            violations.append(Violation("duplicate", (item_id,), f"{item_id} is placed {count} times."))

    if expected_item_ids is not None:
        expected = set(expected_item_ids)
        for item_id in sorted(expected - counts.keys()):
            violations.append(Violation("missing", (item_id,), f"{item_id} was not placed."))
        for item_id in sorted(counts.keys() - expected):
            violations.append(Violation("unexpected", (item_id,), f"{item_id} is not part of the order."))

    return violations


def assert_valid_packing(
    placements: Sequence[Placement],
    container: Container,
    expected_item_ids: Iterable[str] | None = None,
) -> None:
    violations = find_violations(placements, container, expected_item_ids)
    if violations:
        raise PackingIntegrityError(violations)

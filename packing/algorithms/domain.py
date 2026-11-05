"""Domain objects for the pure-Python packing engine.

The engine has no Django dependency. Every length and weight it receives is a
**positive integer in engine units** (the service layer converts centimetres
and kilograms; see ``packing.services.units``). With integer arithmetic,
boundary comparisons are exact: an item exactly as long as the box fits, and
one that is 0.01 cm longer does not. No floating-point epsilon is involved.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from .geometry import Cuboid

AXIS_LABELS = "LWH"
IDENTITY_ORIENTATION = (0, 1, 2)


class InvalidPackingInput(ValueError):
    """Raised when the engine receives invalid items, containers or settings."""


def require_positive_int(name: str, value: object) -> None:
    # bool is a subclass of int, but ``True`` is never a meaningful length.
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidPackingInput(f"{name} must be an integer in engine units, got {type(value).__name__}.")
    if value <= 0:
        raise InvalidPackingInput(f"{name} must be positive, got {value}.")


class PackingStatus(StrEnum):
    #: Every item was placed and the placement passed collision verification.
    FEASIBLE = "feasible"
    #: A necessary condition is violated, so *no* arrangement can exist.
    PROVEN_INFEASIBLE = "proven_infeasible"
    #: The heuristic failed to place every item. An arrangement may still exist.
    HEURISTIC_FAILURE = "heuristic_failure"


class ReasonCode(StrEnum):
    WEIGHT_EXCEEDED = "weight_exceeded"
    ITEM_TOO_LARGE = "item_too_large"
    VOLUME_EXCEEDED = "volume_exceeded"
    HEURISTIC_FAILURE = "heuristic_failure"


@dataclass(frozen=True, slots=True)
class Reason:
    """Machine-readable explanation of why a container was rejected.

    ``required`` and ``available`` are in engine units; the service layer turns
    them into human-readable centimetres and kilograms.
    """

    code: ReasonCode
    product_ids: tuple[Hashable, ...] = ()
    required: int | None = None
    available: int | None = None

    @property
    def is_proof(self) -> bool:
        return self.code is not ReasonCode.HEURISTIC_FAILURE


@dataclass(frozen=True, slots=True)
class ItemLine:
    """One order line: a product and how many units of it to pack."""

    product_id: Hashable
    length: int
    width: int
    height: int
    weight: int
    quantity: int
    sku: str = ""

    def __post_init__(self) -> None:
        for name in ("length", "width", "height", "weight", "quantity"):
            require_positive_int(f"Product {self.product_id} {name}", getattr(self, name))


@dataclass(frozen=True, slots=True)
class Item:
    """A single physical unit to be placed (an order line expanded by quantity)."""

    item_id: str
    product_id: Hashable
    length: int
    width: int
    height: int
    weight: int
    sku: str = ""

    def __post_init__(self) -> None:
        if not self.item_id:
            raise InvalidPackingInput("item_id must be a non-empty string.")
        for name in ("length", "width", "height", "weight"):
            require_positive_int(f"Item {self.item_id} {name}", getattr(self, name))

    @property
    def dims(self) -> tuple[int, int, int]:
        return (self.length, self.width, self.height)

    @property
    def sorted_dims(self) -> tuple[int, int, int]:
        a, b, c = sorted(self.dims)
        return (a, b, c)

    @property
    def volume(self) -> int:
        return self.length * self.width * self.height


@dataclass(frozen=True, slots=True)
class Container:
    """A shipping box: internal dimensions and maximum load, in engine units."""

    container_id: Hashable
    length: int
    width: int
    height: int
    max_weight: int

    def __post_init__(self) -> None:
        for name in ("length", "width", "height", "max_weight"):
            require_positive_int(f"Container {self.container_id} {name}", getattr(self, name))

    @property
    def dims(self) -> tuple[int, int, int]:
        return (self.length, self.width, self.height)

    @property
    def volume(self) -> int:
        return self.length * self.width * self.height

    @property
    def cuboid(self) -> Cuboid:
        return Cuboid(0, 0, 0, self.length, self.width, self.height)


@dataclass(frozen=True, slots=True)
class Placement:
    """Where an item sits inside the container and how it is rotated.

    ``length``/``width``/``height`` are the item's extents along the container's
    x/y/z axes **after** rotation. ``orientation[k]`` is the index of the
    item's original dimension (0=L, 1=W, 2=H) that lies along axis ``k``.
    """

    item: Item
    x: int
    y: int
    z: int
    length: int
    width: int
    height: int
    orientation: tuple[int, int, int] = IDENTITY_ORIENTATION

    @property
    def cuboid(self) -> Cuboid:
        return Cuboid(self.x, self.y, self.z, self.length, self.width, self.height)

    @property
    def orientation_label(self) -> str:
        """E.g. ``"WLH"``: the item's width lies along x, length along y."""
        return "".join(AXIS_LABELS[i] for i in self.orientation)

    @property
    def rotated(self) -> bool:
        return self.orientation != IDENTITY_ORIENTATION


@dataclass(frozen=True, slots=True)
class PackingResult:
    container: Container
    status: PackingStatus
    placements: tuple[Placement, ...]
    unplaced: tuple[Item, ...]
    total_weight: int
    total_item_volume: int
    reasons: tuple[Reason, ...] = ()
    sort_strategy: str | None = None
    attempts: int = 0
    execution_time_ms: float = 0.0

    @property
    def feasible(self) -> bool:
        return self.status is PackingStatus.FEASIBLE

    @property
    def used_volume(self) -> int:
        """Volume of the items that were actually placed."""
        return sum(p.item.volume for p in self.placements)

    @property
    def container_volume(self) -> int:
        return self.container.volume

    @property
    def utilization_ratio(self) -> Fraction:
        """Exact share of the box volume occupied, used for tie-breaking."""
        return Fraction(self.used_volume, self.container.volume)

    @property
    def utilization_percentage(self) -> float:
        return round(float(self.utilization_ratio * 100), 2)

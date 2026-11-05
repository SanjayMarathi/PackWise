"""Pure-Python 3D packing engine (no Django imports).

Public API::

    from packing.algorithms import Container, ItemLine, expand_quantities, pack

    items = expand_quantities([ItemLine("laptop", 3500, 2400, 300, 2100, quantity=2)])
    result = pack(items, Container("M", 4000, 3000, 2000, max_weight=10_000))
    result.status, result.placements, result.utilization_percentage
"""

from .collision import PackingIntegrityError, Violation, assert_valid_packing, find_violations
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
from .free_space import MaximalSpaceManager, remove_redundant, split_space
from .geometry import Cuboid
from .greedy_packer import (
    ALGORITHM_NAME,
    DEFAULT_CONFIG,
    ENGINE_VERSION,
    SORT_STRATEGIES,
    PackerConfig,
    expand_quantities,
    necessary_condition_violations,
    pack,
)
from .orientations import Orientation, fits_in_some_orientation, unique_orientations
from .scoring import (
    DEFAULT_RANKING_STRATEGY,
    RANKING_STRATEGIES,
    RankableBox,
    best_short_side_fit,
    rank_boxes,
)

__all__ = [
    "ALGORITHM_NAME",
    "DEFAULT_CONFIG",
    "DEFAULT_RANKING_STRATEGY",
    "ENGINE_VERSION",
    "RANKING_STRATEGIES",
    "SORT_STRATEGIES",
    "Container",
    "Cuboid",
    "InvalidPackingInput",
    "Item",
    "ItemLine",
    "MaximalSpaceManager",
    "Orientation",
    "PackerConfig",
    "PackingIntegrityError",
    "PackingResult",
    "PackingStatus",
    "Placement",
    "RankableBox",
    "Reason",
    "ReasonCode",
    "Violation",
    "assert_valid_packing",
    "best_short_side_fit",
    "expand_quantities",
    "find_violations",
    "fits_in_some_orientation",
    "necessary_condition_violations",
    "pack",
    "rank_boxes",
    "remove_redundant",
    "split_space",
    "unique_orientations",
]

import itertools
import random

import pytest

from packing.algorithms import Cuboid, MaximalSpaceManager, remove_redundant, split_space


def assert_mes_invariants(container: Cuboid, spaces, placed) -> None:
    """Exact check of the three Maximal-Empty-Space invariants on a unit grid."""
    for space in spaces:
        assert container.contains(space), f"{space} leaves the container"
        assert not space.is_degenerate
        for item in placed:
            assert not space.intersects(item), f"free space {space} overlaps item {item}"
    for a, b in itertools.permutations(spaces, 2):
        assert not a.contains(b), f"{b} is redundant inside {a}"
    # Coverage: every unit cell is either occupied or inside some free space, never both.
    for x, y, z in itertools.product(range(container.length), range(container.width), range(container.height)):
        cell = Cuboid(x, y, z, 1, 1, 1)
        occupied = any(item.contains(cell) for item in placed)
        free = any(space.contains(cell) for space in spaces)
        assert occupied != free, f"cell {(x, y, z)} occupied={occupied} free={free}"


def test_split_by_corner_item_gives_three_maximal_slabs():
    space = Cuboid(0, 0, 0, 10, 10, 10)
    parts = split_space(space, Cuboid(0, 0, 0, 4, 3, 2))
    assert sorted(parts) == sorted(
        [
            Cuboid(4, 0, 0, 6, 10, 10),  # right of the item
            Cuboid(0, 3, 0, 10, 7, 10),  # behind the item
            Cuboid(0, 0, 2, 10, 10, 8),  # above the item
        ]
    )


def test_split_by_central_item_gives_six_slabs():
    parts = split_space(Cuboid(0, 0, 0, 10, 10, 10), Cuboid(3, 3, 3, 4, 4, 4))
    assert sorted(parts) == sorted(
        [
            Cuboid(0, 0, 0, 3, 10, 10),
            Cuboid(7, 0, 0, 3, 10, 10),
            Cuboid(0, 0, 0, 10, 3, 10),
            Cuboid(0, 7, 0, 10, 3, 10),
            Cuboid(0, 0, 0, 10, 10, 3),
            Cuboid(0, 0, 7, 10, 10, 3),
        ]
    )


def test_split_by_item_filling_the_space_leaves_nothing():
    space = Cuboid(2, 2, 2, 5, 5, 5)
    assert split_space(space, space) == []


@pytest.mark.parametrize(
    "obstacle",
    [Cuboid(10, 0, 0, 5, 5, 5), Cuboid(0, 0, 10, 5, 5, 5), Cuboid(20, 20, 20, 1, 1, 1)],
)
def test_split_ignores_touching_or_distant_obstacles(obstacle):
    space = Cuboid(0, 0, 0, 10, 10, 10)
    assert split_space(space, obstacle) == [space]


def test_split_handles_obstacle_partially_outside_the_space():
    # Item straddles the space's x2 face: only the low-x slab and the y/z slabs survive.
    parts = split_space(Cuboid(0, 0, 0, 10, 10, 10), Cuboid(8, 0, 0, 5, 10, 4))
    assert sorted(parts) == sorted([Cuboid(0, 0, 0, 8, 10, 10), Cuboid(0, 0, 4, 10, 10, 6)])


def test_remove_redundant_drops_duplicates_contained_and_degenerate_spaces():
    big = Cuboid(0, 0, 0, 10, 10, 10)
    inner = Cuboid(1, 1, 1, 2, 2, 2)
    other = Cuboid(5, 0, 0, 10, 2, 2)  # sticks out of `big`, so it is kept
    flat = Cuboid(0, 0, 0, 5, 5, 0)
    assert remove_redundant([big, inner, big, other, flat]) == sorted([big, other])


def test_remove_redundant_respects_existing_spaces():
    existing = [Cuboid(0, 0, 0, 10, 10, 10)]
    assert remove_redundant([Cuboid(0, 0, 0, 5, 5, 5)], existing) == []
    assert remove_redundant([Cuboid(5, 5, 5, 6, 1, 1)], existing) == [Cuboid(5, 5, 5, 6, 1, 1)]


def test_manager_starts_with_the_whole_container():
    container = Cuboid(0, 0, 0, 4, 5, 6)
    assert MaximalSpaceManager(container).spaces == (container,)


def test_manager_rejects_degenerate_container():
    with pytest.raises(ValueError):
        MaximalSpaceManager(Cuboid(0, 0, 0, 0, 5, 5))


def test_occupy_two_items_side_by_side_keeps_invariants():
    container = Cuboid(0, 0, 0, 6, 4, 3)
    manager = MaximalSpaceManager(container)
    placed = [Cuboid(0, 0, 0, 3, 4, 3), Cuboid(3, 0, 0, 2, 2, 1)]
    for item in placed:
        manager.occupy(item)
        assert_mes_invariants(container, manager.spaces, placed[: placed.index(item) + 1])
    # The free region right of item 1 is split around item 2 into its three maximal slabs.
    assert len(manager.spaces) == 3
    assert Cuboid(3, 2, 0, 3, 2, 3) in manager.spaces
    assert Cuboid(5, 0, 0, 1, 4, 3) in manager.spaces
    assert Cuboid(3, 0, 1, 3, 4, 2) in manager.spaces


def test_filling_the_container_leaves_no_free_space():
    manager = MaximalSpaceManager(Cuboid(0, 0, 0, 2, 2, 2))
    for x, y, z in itertools.product((0, 1), repeat=3):
        manager.occupy(Cuboid(x, y, z, 1, 1, 1))
    assert manager.spaces == ()


def test_discard_unusable_removes_spaces_too_small_for_remaining_items():
    manager = MaximalSpaceManager(Cuboid(0, 0, 0, 10, 10, 10))
    manager.occupy(Cuboid(0, 0, 0, 9, 10, 10))  # leaves a 1-unit slab at x = 9
    assert manager.spaces == (Cuboid(9, 0, 0, 1, 10, 10),)
    manager.discard_unusable(min_side=2, min_volume=1)
    assert manager.spaces == ()


@pytest.mark.parametrize("seed", range(40))
def test_random_placements_preserve_all_invariants(seed):
    """Place random items inside random free spaces and check the invariants exactly."""
    rng = random.Random(seed)
    container = Cuboid(0, 0, 0, rng.randint(3, 7), rng.randint(3, 7), rng.randint(2, 6))
    manager = MaximalSpaceManager(container)
    placed: list[Cuboid] = []
    for _ in range(12):
        if not manager.spaces:
            break
        space = rng.choice(manager.spaces)
        item = Cuboid(
            rng.randint(space.x, space.x2 - 1),
            rng.randint(space.y, space.y2 - 1),
            rng.randint(space.z, space.z2 - 1),
            0,
            0,
            0,
        )
        item = Cuboid(
            item.x,
            item.y,
            item.z,
            rng.randint(1, space.x2 - item.x),
            rng.randint(1, space.y2 - item.y),
            rng.randint(1, space.z2 - item.z),
        )
        manager.occupy(item)
        placed.append(item)
        assert_mes_invariants(container, manager.spaces, placed)

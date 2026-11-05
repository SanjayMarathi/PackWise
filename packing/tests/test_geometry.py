import pytest

from packing.algorithms import Cuboid
from packing.algorithms.geometry import overlap_area_xy


def test_extents_volume_and_far_corner():
    c = Cuboid(1, 2, 3, 4, 5, 6)
    assert (c.x2, c.y2, c.z2) == (5, 7, 9)
    assert c.dims == (4, 5, 6)
    assert c.volume == 120
    assert not c.is_degenerate


@pytest.mark.parametrize("dims", [(0, 1, 1), (1, 0, 1), (1, 1, 0), (-1, 2, 2)])
def test_degenerate_cuboids(dims):
    assert Cuboid(0, 0, 0, *dims).is_degenerate


def test_overlapping_cuboids_intersect():
    assert Cuboid(0, 0, 0, 4, 4, 4).intersects(Cuboid(3, 3, 3, 4, 4, 4))


@pytest.mark.parametrize(
    "other",
    [
        Cuboid(4, 0, 0, 4, 4, 4),  # shares the x = 4 face
        Cuboid(0, 4, 0, 4, 4, 4),  # shares the y = 4 face
        Cuboid(0, 0, 4, 4, 4, 4),  # shares the z = 4 face
        Cuboid(4, 4, 4, 1, 1, 1),  # shares only a corner
        Cuboid(10, 10, 10, 1, 1, 1),  # far away
    ],
)
def test_touching_or_separate_cuboids_do_not_intersect(other):
    a = Cuboid(0, 0, 0, 4, 4, 4)
    assert not a.intersects(other)
    assert not other.intersects(a)


def test_containment_includes_equal_and_shared_faces():
    outer = Cuboid(0, 0, 0, 10, 10, 10)
    assert outer.contains(outer)
    assert outer.contains(Cuboid(0, 0, 0, 10, 10, 1))
    assert outer.contains(Cuboid(9, 9, 9, 1, 1, 1))
    assert not outer.contains(Cuboid(9, 9, 9, 2, 1, 1))
    assert not outer.contains(Cuboid(-1, 0, 0, 2, 2, 2))


def test_can_hold_is_inclusive_at_the_boundary():
    space = Cuboid(0, 0, 0, 10, 20, 30)
    assert space.can_hold(10, 20, 30)
    assert not space.can_hold(11, 20, 30)
    assert not space.can_hold(10, 20, 31)


def test_ordering_is_total_and_deterministic():
    a, b, c = Cuboid(1, 0, 0, 1, 1, 1), Cuboid(0, 1, 0, 1, 1, 1), Cuboid(0, 0, 1, 1, 1, 1)
    # Lexicographic on (x, y, z, length, width, height).
    assert sorted([a, b, c]) == [c, b, a]
    assert sorted([a, b, c]) == sorted([c, a, b])


def test_overlap_area_xy():
    a = Cuboid(0, 0, 0, 4, 4, 1)
    assert overlap_area_xy(a, Cuboid(2, 2, 5, 4, 4, 1)) == 4
    assert overlap_area_xy(a, Cuboid(4, 0, 0, 4, 4, 1)) == 0
    assert overlap_area_xy(a, a) == 16

import pytest

from packing.algorithms import PackingIntegrityError, Placement, assert_valid_packing, find_violations

from .helpers import box, item


def place(item_obj, x, y, z, dims=None, orientation=(0, 1, 2)):
    length, width, height = dims or item_obj.dims
    return Placement(item_obj, x, y, z, length, width, height, orientation)


def kinds(violations):
    return sorted(v.kind for v in violations)


def test_valid_packing_with_touching_faces_has_no_violations():
    container = box(10, 10, 10)
    a, b, c = item("a#1", 5, 10, 10), item("b#1", 5, 5, 10), item("c#1", 5, 5, 10)
    placements = [place(a, 0, 0, 0), place(b, 5, 0, 0), place(c, 5, 5, 0)]
    assert find_violations(placements, container, ["a#1", "b#1", "c#1"]) == []
    assert_valid_packing(placements, container)


def test_overlap_is_detected():
    container = box(10, 10, 10)
    a, b = item("a#1", 6, 6, 6), item("b#1", 6, 6, 6)
    violations = find_violations([place(a, 0, 0, 0), place(b, 4, 4, 4)], container)
    assert kinds(violations) == ["overlap"]
    assert set(violations[0].item_ids) == {"a#1", "b#1"}


def test_overlap_is_detected_even_when_items_start_far_apart_on_x():
    container = box(20, 20, 20)
    long_item, other = item("a#1", 20, 2, 2), item("b#1", 2, 2, 2)
    # `other` starts at x=15, inside the long item's x range; the sweep must not stop early.
    violations = find_violations([place(long_item, 0, 0, 0), place(other, 15, 1, 1)], container)
    assert kinds(violations) == ["overlap"]


@pytest.mark.parametrize(("x", "y", "z"), [(6, 0, 0), (0, 6, 0), (0, 0, 6), (-1, 0, 0)])
def test_out_of_bounds_is_detected(x, y, z):
    violations = find_violations([place(item("a#1", 5, 5, 5), x, y, z)], box(10, 10, 10))
    assert kinds(violations) == ["out_of_bounds"]


def test_extents_that_are_not_a_rotation_are_detected():
    a = item("a#1", 2, 3, 4)
    wrong_size = place(a, 0, 0, 0, dims=(2, 3, 5))
    wrong_permutation = place(item("b#1", 2, 3, 4), 5, 5, 5, dims=(3, 2, 4), orientation=(0, 1, 2))
    assert kinds(find_violations([wrong_size, wrong_permutation], box(10, 10, 10))) == [
        "bad_orientation",
        "bad_orientation",
    ]


def test_rotated_placement_is_valid():
    a = item("a#1", 2, 3, 4)
    assert find_violations([place(a, 0, 0, 0, dims=(4, 2, 3), orientation=(2, 0, 1))], box(5, 5, 5)) == []


def test_each_item_must_be_placed_exactly_once():
    container = box(10, 10, 10)
    a = item("a#1", 2, 2, 2)
    violations = find_violations(
        [place(a, 0, 0, 0), place(a, 5, 5, 5), place(item("x#1", 1, 1, 1), 9, 9, 9)],
        container,
        expected_item_ids=["a#1", "b#1"],
    )
    assert kinds(violations) == ["duplicate", "missing", "unexpected"]


def test_assert_valid_packing_raises_with_details():
    a, b = item("a#1", 6, 6, 6), item("b#1", 6, 6, 6)
    with pytest.raises(PackingIntegrityError) as excinfo:
        assert_valid_packing([place(a, 0, 0, 0), place(b, 1, 1, 1)], box(10, 10, 10))
    assert excinfo.value.violations[0].kind == "overlap"
    assert "overlaps" in str(excinfo.value)

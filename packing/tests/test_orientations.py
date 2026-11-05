import itertools

import pytest

from packing.algorithms import fits_in_some_orientation, unique_orientations


def test_distinct_dimensions_have_six_orientations_in_documented_order():
    labels = [o.label for o in unique_orientations((3, 2, 1))]
    assert labels == ["LWH", "LHW", "WLH", "WHL", "HLW", "HWL"]
    dims = [o.dims for o in unique_orientations((3, 2, 1))]
    assert dims == [(3, 2, 1), (3, 1, 2), (2, 3, 1), (2, 1, 3), (1, 3, 2), (1, 2, 3)]
    assert len(set(dims)) == 6


def test_square_prism_has_three_orientations():
    dims = [o.dims for o in unique_orientations((4, 4, 2))]
    assert sorted(dims) == sorted({(4, 4, 2), (4, 2, 4), (2, 4, 4)})
    assert len(dims) == 3


def test_cube_has_a_single_identity_orientation():
    orientations = unique_orientations((5, 5, 5))
    assert len(orientations) == 1
    assert orientations[0].label == "LWH"


def test_every_orientation_is_a_permutation_of_the_original():
    original = (7, 3, 5)
    for o in unique_orientations(original):
        assert tuple(original[i] for i in o.permutation) == o.dims
        assert sorted(o.dims) == sorted(original)


@pytest.mark.parametrize(
    ("item", "space", "expected"),
    [
        ((10, 20, 30), (10, 20, 30), True),  # exact fit
        ((30, 10, 20), (10, 20, 30), True),  # fits after rotation
        ((10, 20, 31), (10, 20, 30), False),  # one unit too long
        ((25, 25, 1), (30, 20, 30), True),  # fits standing on its edge (1 along y)
        ((25, 25, 1), (30, 20, 20), False),  # needs two sides >= 25 in every orientation
    ],
)
def test_fits_in_some_orientation(item, space, expected):
    assert fits_in_some_orientation(item, space) is expected


def test_sorted_dimension_lemma_matches_brute_force():
    """The O(1) sorted test agrees with trying all 6 rotations, over a full grid."""
    values = range(1, 5)
    for item in itertools.product(values, repeat=3):
        for space in itertools.product(values, repeat=3):
            brute = any(all(d <= s for d, s in zip(o.dims, space, strict=True)) for o in unique_orientations(item))
            assert fits_in_some_orientation(item, space) is brute, (item, space)

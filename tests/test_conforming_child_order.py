"""Exact historical child winding/order across all edge-split combinations."""
import numpy as np
import pytest

from diffeoforge._conforming_children import children
from diffeoforge.source_refinement import subdivide


@pytest.mark.parametrize(('edges', 'expected'), [
    ([[0, 1]], [[0, 3, 2], [3, 1, 2]]),
    ([[0, 2]], [[2, 3, 1], [3, 0, 1]]),
    ([[1, 2]], [[1, 3, 0], [3, 2, 0]]),
    ([[0, 1], [1, 2]], [[1, 4, 3], [0, 3, 2], [3, 4, 2]]),
    ([[0, 1], [0, 2]], [[0, 3, 4], [2, 4, 1], [4, 3, 1]]),
    ([[0, 2], [1, 2]], [[2, 3, 4], [1, 4, 0], [4, 3, 0]]),
    ([[0, 1], [0, 2], [1, 2]], [[0, 3, 4], [3, 1, 5], [4, 5, 2], [3, 5, 4]]),
])
def test_every_split_keeps_the_recorded_material_connectivity(edges, expected):
    result, parents = children(np.array([[0, 1, 2]]), np.array(edges), 3)
    np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(parents, np.zeros(len(expected), dtype=np.int64))


def test_no_selected_face_keeps_exact_original_arrays_and_independent_storage():
    v = np.array([[0., 0, 0], [1., 0, 0], [0., 1, 0]])
    f = np.array([[0, 1, 2]])
    a, b, p = subdivide(v, f, [False])
    assert a.tobytes() == v.tobytes() and b.tobytes() == f.tobytes()
    assert not np.shares_memory(a, v) and not np.shares_memory(b, f)
    np.testing.assert_array_equal(p, [0])

"""Keep independent repeat scores bit-identical while sharing native query startup."""
import numpy as np
import pytest

from diffeoforge import reference_attachment_comparison as comparison
from diffeoforge import reference_fit_search as search
from diffeoforge.mesh import TriangleMesh


@pytest.mark.parametrize('scale,tip', [(1., 2.), (.25, 1.)])
def test_two_repeat_comparison_matches_independent_queries_with_two_workers(
    monkeypatch, scale, tip
):
    vertices = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0],
                         [0, -1, 0], [0, 0, 1], [0, 0, -1]], float)
    faces = np.array([[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
                      [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]])
    fitted = vertices.copy() * scale
    fitted[0, 0] *= tip
    original = TriangleMesh(vertices, faces)
    result = TriangleMesh(fitted, faces)
    native, grouped = search.distances_to_surface, search.grouped_surface_distances
    # Independent native queries reproduce the earlier dispatch, not a mock
    # distance formula; keep samples, both directions, tails and warning flags.
    monkeypatch.setattr(search, 'grouped_surface_distances',
                        lambda groups, v, f: [native(g, v, f) for g in groups])
    expected = comparison.compare_geometry(original, result)
    calls = []

    def measured(points, v, f):
        calls.append(len(points))
        return native(points, v, f)

    monkeypatch.setattr(search, 'grouped_surface_distances', grouped)
    monkeypatch.setattr(search, 'distances_to_surface', measured)
    actual = comparison.compare_geometry(original, result)
    assert actual == expected
    assert calls == [2 * comparison.SAMPLES, 2 * comparison.SAMPLES]
    assert len(actual['repeats']) == 2
    assert np.array_equal(original.vertices, vertices)
    assert np.array_equal(result.vertices, fitted)

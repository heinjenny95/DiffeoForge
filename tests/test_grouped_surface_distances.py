"""Native scientific-QC parity when independent point queries share a worker."""

import numpy as np
import pytest

from diffeoforge import reference_fit_search as search


@pytest.mark.parametrize("translation", [(0, 0, 0), (25, -30, 11), (1e6, 0, 0)])
def test_grouped_queries_match_independent_native_triangle_distances_bitwise(translation):
    offset = np.asarray(translation, float)
    vertices = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], float) + offset
    faces = np.array([[0, 1, 2]])
    groups = [np.array([[2, 2, 0], [2, 2, 1], [11, 0, 0]], float) + offset,
              np.empty((0, 3)),
              np.array([[-1, -1, 0], [3, 3, -2]], float) + offset]
    independent = [search.distances_to_surface(g, vertices, faces) if len(g) else np.empty(0)
                   for g in groups]
    together = search.grouped_surface_distances(groups, vertices, faces)
    assert len(together) == len(independent)
    for a, b in zip(together, independent, strict=True):
        assert np.array_equal(a.view(np.uint64), b.view(np.uint64))
    np.testing.assert_allclose(together[0], [0, 1, 1], atol=1e-12, rtol=0)
    np.testing.assert_allclose(together[2], [np.sqrt(2), 2], atol=1e-7, rtol=0)


def test_empty_groups_need_no_worker_and_preserve_unknown_reverse_queries(monkeypatch):
    monkeypatch.setattr(search, "distances_to_surface", lambda *_: pytest.fail("Empty query"))
    assert search.grouped_surface_distances([], [], []) == []
    result = search.grouped_surface_distances([np.empty((0, 3))] * 2, [], [])
    assert len(result) == 2 and all(a.shape == (0,) for a in result)
    from diffeoforge.pilot_regions import measure

    assert measure(None, None, []) == []

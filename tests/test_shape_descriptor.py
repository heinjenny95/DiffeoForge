from dataclasses import replace

import numpy as np
import pytest
from test_reference_calibration import _recommendation

from diffeoforge.reference_calibration import select_representative_pilot_subjects
from diffeoforge.reference_recommendation import MeshGeometryObservation
from diffeoforge.shape_descriptor import normalized_shape_matrix, surface_shape_descriptor


def cube():
    vertices = np.asarray(
        [
            [-1, -1, -1],
            [1, -1, -1],
            [1, 1, -1],
            [-1, 1, -1],
            [-1, -1, 1],
            [1, -1, 1],
            [1, 1, 1],
            [-1, 1, 1],
        ],
        dtype=float,
    )
    faces = np.asarray(
        [
            [0, 1, 2],
            [0, 2, 3],
            [4, 6, 5],
            [4, 7, 6],
            [0, 4, 5],
            [0, 5, 1],
            [1, 5, 6],
            [1, 6, 2],
            [2, 6, 7],
            [2, 7, 3],
            [3, 7, 4],
            [3, 4, 0],
        ]
    )
    return vertices, faces


def test_descriptor_repeat_translation_scale_and_reordering():
    vertices, faces = cube()
    expected = surface_shape_descriptor(vertices, faces)
    assert len(expected) == 168
    assert expected == surface_shape_descriptor(vertices, faces)
    assert expected == surface_shape_descriptor(np.vstack((vertices, [1e6, 2e6, 3e6])), faces)
    assert surface_shape_descriptor(vertices * 1000 + [4, 7, -3], faces) == pytest.approx(expected)
    assert surface_shape_descriptor(vertices, faces[::-1, ::-1]) == expected
    permutation = np.asarray([4, 5, 0, 2, 7, 6, 3, 1])
    assert (
        surface_shape_descriptor(vertices[permutation], np.argsort(permutation)[faces]) == expected
    )


def test_retriangulation_is_smaller_than_real_shape_difference():
    vertices, faces = cube()
    centers = vertices[faces].mean(axis=1)
    subdivided = np.asarray(
        [
            [face[j], face[(j + 1) % 3], len(vertices) + index]
            for index, face in enumerate(faces)
            for j in range(3)
        ]
    )
    original = np.asarray(surface_shape_descriptor(vertices, faces))
    dense = np.asarray(surface_shape_descriptor(np.vstack((vertices, centers)), subdivided))
    changed = vertices.copy()
    changed[6] = [0.2, 0.3, 0.1]  # local indentation; identical overall bounding box
    local = np.asarray(surface_shape_descriptor(changed, faces))
    assert np.linalg.norm(dense - original) < np.linalg.norm(local - original) / 3
    assert dense[:29] == pytest.approx(original[:29], abs=1e-12)


def test_selection_uses_shape_not_vertex_count_and_pins_declared_cases():
    vertices, faces = cube()
    common = surface_shape_descriptor(vertices, faces)
    changed = vertices.copy()
    changed[6] = [0.2, 0.3, 0.1]
    unusual = surface_shape_descriptor(changed, faces)
    observations = tuple(
        MeshGeometryObservation(
            f"mesh-{i}.vtk",
            "a" * 64,
            100 * 10**i,
            200 * 10**i,
            np.sqrt(12),
            1.0,
            0.1,
            unusual if i == 5 else common,
        )
        for i in range(6)
    )
    recommendation = replace(_recommendation(), observations=observations)
    selected = select_representative_pilot_subjects(recommendation, requested_count=2)
    assert selected[-1].filename == "mesh-5.vtk"
    assert selected[0].selection_role == "surface-shape medoid"
    assert np.isfinite(normalized_shape_matrix([common, common])).all()


def test_invalid_and_mixed_descriptors_fail():
    vertices, faces = cube()
    with pytest.raises(ValueError):
        surface_shape_descriptor(vertices * np.nan, faces)
    with pytest.raises(ValueError):
        normalized_shape_matrix([[np.nan] * 168])
    recommendation = _recommendation()
    items = list(recommendation.observations)
    items[1] = replace(items[1], shape_descriptor=())
    with pytest.raises(ValueError, match="Mixed legacy"):
        select_representative_pilot_subjects(replace(recommendation, observations=tuple(items)))

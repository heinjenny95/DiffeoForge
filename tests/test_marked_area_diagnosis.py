"""A local suggestion follows the measured direction and leaves sparse marks open."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge.desktop.marked_area_diagnosis import diagnose
from diffeoforge.pilot_regions import EDIT_VERSION

marking_geometry = pytest.importorskip("diffeoforge.desktop.region_marking_geometry")


def plane(z, size=9):
    coordinates = np.linspace(-0.4, 0.4, size)
    vertices = [(x, y, z) for y in coordinates for x in coordinates]
    triangles = []
    for row in range(size - 1):
        for column in range(size - 1):
            a = row * size + column
            triangles.extend(((a, a + 1, a + size), (a + 1, a + size + 1, a + size)))
    return np.asarray(vertices), np.asarray(triangles)


def marking(digest, *surfaces):
    points = []
    faces = []
    offset = 0
    for vertices, triangles in surfaces:
        points.append(vertices)
        faces.append(triangles + offset)
        offset += len(vertices)
    return marking_geometry.prepare_region_marking_mesh(SimpleNamespace(
        path=Path("surface.vtk"), sha256=digest, geometry_is_proxy=False,
        vertices=np.concatenate(points), triangles=np.concatenate(faces),
    ))


def region(digest="original", radius=1.0):
    return dict(version=EDIT_VERSION, source_sha256=digest, space="original_mesh_coordinates",
                center=[0, 0, 0], radius=radius, purpose="problem", symptom="unsure")


@pytest.mark.parametrize(("original_layers", "fit_layers", "symptom", "distances"), [
    ((0.0, 0.4), (0.0,), "missing", (0.4, 0.0)),
    ((0.0,), (0.0, 0.4), "distortion", (0.0, 0.4)),
    ((0.0,), (0.4,), None, (0.4, 0.4)),
    ((0.0,), (0.0,), None, (0.0, 0.0)),
])
def test_directional_surface_evidence(original_layers, fit_layers, symptom, distances):
    original = marking("original", *(plane(z) for z in original_layers))
    fit = marking("fit", *(plane(z) for z in fit_layers))
    result = diagnose(original, fit, region())
    assert result["symptom"] == symptom
    assert result["original_to_fit_p90"] == pytest.approx(distances[0])
    assert result["fit_to_original_p90"] == pytest.approx(distances[1])
    assert 16 <= result["original_samples"] <= 128
    assert 16 <= result["fit_samples"] <= 128
    assert result["original_face_count"] == 128 * len(original_layers)
    assert result["fit_face_count"] == 128 * len(fit_layers)


def test_small_or_unmatched_mark_does_not_make_a_suggestion():
    original = marking("original", plane(0.0))
    fit = marking("fit", plane(0.6))
    result = diagnose(original, fit, region(radius=0.4))
    assert result["symptom"] is None
    assert result["original_to_fit_p90"] == pytest.approx(0.6)
    assert result["fit_to_original_p90"] is None and result["fit_samples"] == 0
    assert "too few face centres" in result["message"]

    original = marking("original", plane(0.0, size=2))
    fit = marking("fit", plane(0.4, size=2))
    result = diagnose(original, fit, region())
    assert result["symptom"] is None
    assert result["original_samples"] == 2 and result["fit_samples"] == 2


def test_area_source_binding_is_required():
    original = marking("original", plane(0.0, size=2))
    fit = marking("fit", plane(0.0, size=2))
    with pytest.raises(ValueError, match="Region source"):
        diagnose(original, fit, region(digest="different"))

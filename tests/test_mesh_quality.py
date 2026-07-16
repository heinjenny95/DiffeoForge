from __future__ import annotations

import math

import pytest

from diffeoforge.mesh_quality import (
    MeshQualityError,
    MeshQualitySettings,
    assess_triangle_mesh,
    compare_triangle_meshes,
    enforce_deformation_quality,
    enforce_mesh_quality,
)

TETRA_VERTICES = (
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)
TETRA_FACES = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3))


def test_closed_tetrahedron_has_exact_topology_and_quality() -> None:
    result = assess_triangle_mesh(TETRA_VERTICES, TETRA_FACES)

    assert result.points == 4
    assert result.triangles == 4
    assert result.unique_edges == 6
    assert result.boundary_edges == 0
    assert result.manifold_edges == 6
    assert result.nonmanifold_edges == 0
    assert result.face_connected_components == 1
    assert result.euler_characteristic == 2
    assert result.inconsistently_oriented_manifold_edges == 0
    assert result.zero_area_faces == 0
    assert result.total_surface_area == pytest.approx(1.5 + math.sqrt(3.0) / 2.0)
    assert result.triangle_area.minimum == 0.5
    assert result.minimum_angle_degrees is not None
    assert result.minimum_angle_degrees.minimum == pytest.approx(45.0)
    assert result.edge_ratio is not None
    assert result.edge_ratio.maximum == pytest.approx(math.sqrt(2.0))


def test_open_disconnected_mesh_records_boundary_components_and_isolated_vertex() -> None:
    vertices = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (2.0, 0.0, 0.0),
        (3.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (9.0, 9.0, 9.0),
    )
    result = assess_triangle_mesh(vertices, ((0, 1, 2), (3, 4, 5)))

    assert result.boundary_edges == 6
    assert result.face_connected_components == 2
    assert result.isolated_vertices == 1
    with pytest.raises(MeshQualityError, match="isolated vertices"):
        enforce_mesh_quality("disconnected", result, MeshQualitySettings())
    permissive = MeshQualitySettings(
        require_no_isolated_vertices=False,
        require_single_component=False,
        require_closed_surface=False,
    )
    enforce_mesh_quality("disconnected", result, permissive)


def test_duplicate_nonmanifold_and_inconsistent_faces_are_distinguished() -> None:
    vertices = (*TETRA_VERTICES, (0.0, -1.0, 0.0))
    duplicate = assess_triangle_mesh(vertices, ((0, 1, 2), (2, 1, 0)))
    nonmanifold = assess_triangle_mesh(vertices, ((0, 1, 2), (1, 0, 3), (0, 1, 4)))
    inconsistent = assess_triangle_mesh(vertices, ((0, 1, 2), (0, 1, 3)))

    assert duplicate.duplicate_faces == 1
    assert nonmanifold.nonmanifold_edges == 1
    assert inconsistent.inconsistently_oriented_manifold_edges == 1
    with pytest.raises(MeshQualityError, match="duplicate"):
        enforce_mesh_quality("duplicate", duplicate, MeshQualitySettings())
    with pytest.raises(MeshQualityError, match="non-manifold"):
        enforce_mesh_quality("nonmanifold", nonmanifold, MeshQualitySettings())
    with pytest.raises(MeshQualityError, match="inconsistently"):
        enforce_mesh_quality("orientation", inconsistent, MeshQualitySettings())


def test_zero_area_zero_length_and_skinny_triangle_thresholds() -> None:
    collinear = assess_triangle_mesh(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        ((0, 1, 2),),
    )
    coincident = assess_triangle_mesh(
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ((0, 1, 2),),
    )
    skinny = assess_triangle_mesh(
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.001, 0.001, 0.0)),
        ((0, 1, 2),),
    )

    assert collinear.zero_area_faces == 1
    assert coincident.zero_area_faces == coincident.zero_length_edge_faces == 1
    assert coincident.undefined_angle_faces == 1
    with pytest.raises(MeshQualityError, match="zero-area"):
        enforce_mesh_quality("collinear", collinear, MeshQualitySettings())
    with pytest.raises(MeshQualityError, match="minimum triangle angle"):
        enforce_mesh_quality(
            "skinny",
            skinny,
            MeshQualitySettings(minimum_triangle_angle_degrees=1.0),
        )
    with pytest.raises(MeshQualityError, match="edge ratio"):
        enforce_mesh_quality(
            "skinny",
            skinny,
            MeshQualitySettings(maximum_triangle_edge_ratio=100.0),
        )


def test_dimensionless_measures_are_rigid_and_scale_invariant() -> None:
    original = assess_triangle_mesh(TETRA_VERTICES, TETRA_FACES)
    transformed_vertices = tuple(
        (3.0 * (-y) + 10.0, 3.0 * x - 4.0, 3.0 * z + 8.0)
        for x, y, z in TETRA_VERTICES
    )
    transformed = assess_triangle_mesh(transformed_vertices, TETRA_FACES)

    assert transformed.connectivity_sha256 == original.connectivity_sha256
    assert transformed.minimum_angle_degrees is not None
    assert original.minimum_angle_degrees is not None
    assert transformed.minimum_angle_degrees.as_manifest() == pytest.approx(
        original.minimum_angle_degrees.as_manifest()
    )
    assert transformed.edge_ratio is not None
    assert original.edge_ratio is not None
    assert transformed.edge_ratio.as_manifest() == pytest.approx(
        original.edge_ratio.as_manifest()
    )
    assert transformed.minimum_area_over_bbox_diagonal_squared == pytest.approx(
        original.minimum_area_over_bbox_diagonal_squared
    )
    assert transformed.total_surface_area == pytest.approx(original.total_surface_area * 9.0)


def test_declared_quantile_interpolation_and_optional_topology_gates() -> None:
    vertices = (
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (10.0, 0.0, 0.0),
        (14.0, 0.0, 0.0),
        (10.0, 1.0, 0.0),
        (20.0, 0.0, 0.0),
        (26.0, 0.0, 0.0),
        (20.0, 1.0, 0.0),
    )
    result = assess_triangle_mesh(vertices, ((0, 1, 2), (3, 4, 5), (6, 7, 8)))

    assert result.triangle_area.minimum == 1.0
    assert result.triangle_area.q05 == pytest.approx(1.1)
    assert result.triangle_area.median == 2.0
    assert result.triangle_area.q95 == pytest.approx(2.9)
    assert result.triangle_area.maximum == 3.0
    with pytest.raises(MeshQualityError, match="multiple face-connected components"):
        enforce_mesh_quality(
            "components",
            result,
            MeshQualitySettings(require_single_component=True),
        )
    with pytest.raises(MeshQualityError, match="boundary edges"):
        enforce_mesh_quality(
            "open",
            result,
            MeshQualitySettings(require_closed_surface=True),
        )


def test_known_local_area_ratios_and_declared_deformation_gates() -> None:
    reference = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    doubled = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0))
    comparison = compare_triangle_meshes(reference, ((0, 1, 2),), doubled, ((0, 1, 2),))

    assert comparison.connectivity_identical is True
    assert comparison.face_area_ratio is not None
    assert comparison.face_area_ratio.minimum == comparison.face_area_ratio.maximum == 4.0
    enforce_deformation_quality(
        "doubled",
        comparison,
        MeshQualitySettings(minimum_face_area_ratio=3.0, maximum_face_area_ratio=5.0),
    )
    with pytest.raises(MeshQualityError, match="exceeds"):
        enforce_deformation_quality(
            "doubled",
            comparison,
            MeshQualitySettings(maximum_face_area_ratio=3.0),
        )


def test_invalid_settings_and_connectivity_fail_explicitly() -> None:
    with pytest.raises(ValueError, match="cannot exceed 60"):
        MeshQualitySettings(minimum_triangle_angle_degrees=61.0)
    with pytest.raises(ValueError, match="cannot exceed"):
        MeshQualitySettings(minimum_face_area_ratio=2.0, maximum_face_area_ratio=1.0)
    with pytest.raises(ValueError, match="identical ordered connectivity"):
        compare_triangle_meshes(
            TETRA_VERTICES,
            TETRA_FACES,
            TETRA_VERTICES,
            tuple(reversed(TETRA_FACES)),
        )

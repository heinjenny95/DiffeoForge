from __future__ import annotations

from pathlib import Path

import numpy as np

from diffeoforge.input_preflight import (
    HEAVY_ATTACHMENT_INTERACTION_COUNT,
    HEAVY_COHORT_FACE_COUNT,
    assess_mesh_input_metadata,
    format_mesh_input_preflight,
    inspect_mesh_input_cohort,
)
from diffeoforge.mesh import write_vtk_polydata
from diffeoforge.surface_io import SurfaceMeshMetadata


def _metadata(
    name: str,
    *,
    diagonal: float = 1.0,
    triangles: int = 4,
    bytes_: int = 256,
    encoding: str = "binary_little_endian",
) -> SurfaceMeshMetadata:
    return SurfaceMeshMetadata(
        path=str(Path("C:/cohort") / name),
        bytes=bytes_,
        sha256=(name.encode("utf-8").hex() + "0" * 64)[:64],
        source_format="ply",
        encoding=encoding,
        points=max(4, triangles // 2),
        triangles=triangles,
        bounds=(0.0, diagonal, 0.0, 0.0, 0.0, 0.0),
        bounding_box_extents=(diagonal, 0.0, 0.0),
        bounding_box_diagonal=diagonal,
        topology_note="triangular test surface",
    )


def _landmarks(diagonal: float) -> np.ndarray:
    return np.asarray(
        (
            (0.0, 0.0, 0.0),
            (diagonal, 0.0, 0.0),
            (0.0, diagonal / 2.0, 0.0),
        ),
        dtype=np.float64,
    )


def test_single_high_resolution_mesh_does_not_warn_by_itself() -> None:
    report = assess_mesh_input_metadata(
        (
            _metadata("template.ply"),
            _metadata("high-resolution.ply", triangles=1_000_000, encoding="ascii"),
            _metadata("ordinary.ply"),
        )
    )

    assert report.ready
    assert report.issues == ()
    rendered = format_mesh_input_preflight(report)
    assert "Individual face counts alone are not treated as a problem" in rendered


def test_combined_atlas_workload_warns_without_condemning_resolution() -> None:
    per_mesh = HEAVY_COHORT_FACE_COUNT // 5
    report = assess_mesh_input_metadata(
        tuple(
            _metadata(
                f"mesh-{index}.ply",
                triangles=per_mesh,
                encoding=("ascii" if index == 0 else "binary_little_endian"),
            )
            for index in range(5)
        )
    )

    assert report.ready
    assert report.blockers == ()
    assert tuple(issue.code for issue in report.warnings) == ("large_mesh_workload",)
    assert "combined atlas workload" in report.warnings[0].title.casefold()
    assert "scientific resolution is unnecessary" in report.warnings[0].summary
    assert "ASCII" in report.warnings[0].summary
    assert report.warnings[0].affected_meshes == ()


def test_template_target_interactions_warn_below_total_face_threshold() -> None:
    template_faces = 500_000
    target_faces = HEAVY_ATTACHMENT_INTERACTION_COUNT // template_faces
    report = assess_mesh_input_metadata(
        (
            _metadata("template.ply", triangles=template_faces),
            _metadata("subject-a.ply", triangles=target_faces),
            _metadata("subject-b.ply", triangles=target_faces),
        )
    )

    assert report.total_triangles < HEAVY_COHORT_FACE_COUNT
    assert report.estimated_attachment_interactions >= HEAVY_ATTACHMENT_INTERACTION_COUNT
    assert tuple(issue.code for issue in report.warnings) == ("large_mesh_workload",)


def test_mesh_only_scale_split_warns_but_does_not_guess_units() -> None:
    report = assess_mesh_input_metadata(
        (
            _metadata("small-a.ply", diagonal=1.0),
            _metadata("small-b.ply", diagonal=1.2),
            _metadata("large-a.ply", diagonal=1_000.0),
            _metadata("large-b.ply", diagonal=1_100.0),
        )
    )

    assert report.ready
    assert report.blockers == ()
    assert tuple(issue.code for issue in report.warnings) == (
        "mixed_mesh_coordinate_scales",
    )
    assert report.warnings[0].affected_meshes == ("small-a.ply", "small-b.ply")
    assert "biological size variation" in report.warnings[0].summary
    assert "cannot infer an absolute unit" in report.warnings[0].summary


def test_landmarks_identify_meshes_on_the_wrong_coordinate_scale() -> None:
    metadata = (
        _metadata("matching-a.ply", diagonal=100.0),
        _metadata("matching-b.ply", diagonal=100.0),
        _metadata("meters-a.ply", diagonal=0.1),
        _metadata("meters-b.ply", diagonal=0.1),
    )
    values = np.stack(tuple(_landmarks(100.0) for _item in metadata))

    report = assess_mesh_input_metadata(
        metadata,
        landmark_path=Path("C:/cohort/landmarks.csv"),
        landmark_labels=("LM1", "LM2", "LM3"),
        landmark_values=values,
    )

    assert not report.ready
    assert tuple(issue.code for issue in report.blockers) == (
        "landmark_mesh_coordinate_scale_mismatch",
    )
    assert report.blockers[0].affected_meshes == ("meters-a.ply", "meters-b.ply")
    assert "1e+03x" in report.blockers[0].summary


def test_matching_landmarks_and_light_meshes_pass() -> None:
    metadata = (
        _metadata("a.ply", diagonal=100.0),
        _metadata("b.ply", diagonal=105.0),
        _metadata("c.ply", diagonal=95.0),
    )
    values = np.stack(tuple(_landmarks(96.0) for _item in metadata))

    report = assess_mesh_input_metadata(
        metadata,
        landmark_path=Path("C:/cohort/landmarks.csv"),
        landmark_labels=("LM1", "LM2", "LM3"),
        landmark_values=values,
    )

    assert report.ready
    assert report.issues == ()
    rendered = format_mesh_input_preflight(report)
    assert "Checked 3 meshes" in rendered
    assert "No exceptional combined workload" in rendered


def test_unit_centroid_gpa_accepts_large_biological_or_file_scale_differences() -> None:
    metadata = (
        _metadata("small.ply", diagonal=1.0),
        _metadata("large.ply", diagonal=1_000.0),
        _metadata("medium.ply", diagonal=10.0),
    )
    values = np.stack((_landmarks(0.8), _landmarks(800.0), _landmarks(8.0)))

    report = assess_mesh_input_metadata(
        metadata,
        landmark_path=Path("C:/cohort/landmarks.csv"),
        landmark_labels=("LM1", "LM2", "LM3"),
        landmark_values=values,
        procrustes_enabled=True,
        scale_to_unit_centroid_size=True,
    )

    assert report.ready
    assert report.issues == ()
    assert report.procrustes_enabled
    assert report.scale_to_unit_centroid_size


def test_size_groups_warn_when_gpa_preserves_centroid_size() -> None:
    metadata = (
        _metadata("small.ply", diagonal=1.0),
        _metadata("large.ply", diagonal=1_000.0),
        _metadata("large-b.ply", diagonal=1_100.0),
    )
    values = np.stack((_landmarks(0.8), _landmarks(800.0), _landmarks(880.0)))

    report = assess_mesh_input_metadata(
        metadata,
        landmark_path=Path("C:/cohort/landmarks.csv"),
        landmark_labels=("LM1", "LM2", "LM3"),
        landmark_values=values,
        procrustes_enabled=True,
        scale_to_unit_centroid_size=False,
    )

    assert report.ready
    assert tuple(issue.code for issue in report.warnings) == (
        "mixed_mesh_coordinate_scales",
    )
    assert "size-and-shape mode" in report.warnings[0].summary


def test_disabled_gpa_does_not_block_on_unused_landmark_mesh_scale() -> None:
    metadata = (
        _metadata("matching.ply", diagonal=100.0),
        _metadata("meters-a.ply", diagonal=0.1),
        _metadata("meters-b.ply", diagonal=0.1),
    )
    values = np.stack(tuple(_landmarks(100.0) for _item in metadata))

    report = assess_mesh_input_metadata(
        metadata,
        landmark_path=Path("C:/cohort/landmarks.csv"),
        landmark_labels=("LM1", "LM2", "LM3"),
        landmark_values=values,
        procrustes_enabled=False,
    )

    assert report.ready
    assert report.blockers == ()
    assert tuple(issue.code for issue in report.warnings) == (
        "mixed_mesh_coordinate_scales",
    )


def test_source_mesh_topology_is_checked_before_project_creation(tmp_path: Path) -> None:
    vertices = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, -1.0, 0.0),
    )
    valid_faces = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3))
    nonmanifold_faces = ((0, 1, 2), (1, 0, 3), (0, 1, 4))
    template = write_vtk_polydata(tmp_path / "template.vtk", vertices[:4], valid_faces)
    subject = write_vtk_polydata(
        tmp_path / "subject-valid.vtk", vertices[:4], valid_faces
    )
    aberrans = write_vtk_polydata(
        tmp_path / "aberrans_s.vtk", vertices, nonmanifold_faces
    )
    progress: list[tuple[int, int, str]] = []

    report = inspect_mesh_input_cohort(
        (template, subject, aberrans),
        template_path=template,
        progress_callback=lambda completed, total, path: progress.append(
            (completed, total, path.name)
        ),
    )

    assert not report.ready
    nonmanifold = next(
        issue for issue in report.blockers if issue.code == "mesh_quality_non_manifold_edges"
    )
    assert nonmanifold.affected_meshes == ("aberrans_s.vtk",)
    rendered = format_mesh_input_preflight(report)
    assert "non-manifold edges" in rendered
    assert "aberrans_s.vtk" in rendered
    assert "DiffeoForge did not modify any input" in rendered
    assert progress == [
        (1, 3, "template.vtk"),
        (2, 3, "subject-valid.vtk"),
        (3, 3, "aberrans_s.vtk"),
    ]

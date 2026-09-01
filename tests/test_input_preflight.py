from __future__ import annotations

from pathlib import Path

import numpy as np

from diffeoforge.input_preflight import (
    DENSE_MESH_FACE_COUNT,
    assess_mesh_input_metadata,
    format_mesh_input_preflight,
)
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


def test_large_meshes_warn_without_blocking() -> None:
    report = assess_mesh_input_metadata(
        (
            _metadata(
                "dense.ply",
                triangles=DENSE_MESH_FACE_COUNT,
                encoding="ascii",
            ),
            _metadata("ordinary.ply"),
        )
    )

    assert report.ready
    assert report.blockers == ()
    assert tuple(issue.code for issue in report.warnings) == ("large_mesh_workload",)
    assert "ASCII" in report.warnings[0].summary
    assert report.warnings[0].affected_meshes == ("dense.ply",)


def test_mesh_only_scale_split_blocks_before_gpa() -> None:
    report = assess_mesh_input_metadata(
        (
            _metadata("small-a.ply", diagonal=1.0),
            _metadata("small-b.ply", diagonal=1.2),
            _metadata("large-a.ply", diagonal=1_000.0),
            _metadata("large-b.ply", diagonal=1_100.0),
        )
    )

    assert not report.ready
    assert tuple(issue.code for issue in report.blockers) == (
        "mixed_mesh_coordinate_scales",
    )
    assert report.blockers[0].affected_meshes == ("small-a.ply", "small-b.ply")
    assert "mixed coordinate units" in report.blockers[0].summary


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
    assert "No unusual workload" in rendered

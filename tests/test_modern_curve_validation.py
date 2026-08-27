from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import diffeoforge.modern_curve_validation as validation_module
from diffeoforge.mesh import TriangleMesh, sha256_file
from diffeoforge.modern_curve_validation import (
    MODERN_CURVE_VALIDATION_MANIFEST,
    MODERN_CURVE_VALIDATION_SIDECAR,
    ModernCurveValidationError,
    _closest_surface_coordinates,
    _fit_similarity,
    _resample_curve,
    _safe_preprocessing_path,
    verify_modern_curve_validation,
    write_modern_curve_validation,
)


def test_similarity_recovers_proper_scale_rotation_and_translation() -> None:
    source = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 3.0, 0.0],
            [0.0, 0.0, 4.0],
        ],
        dtype=np.float64,
    )
    rotation = np.array(
        [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    target = source * 2.5 @ rotation + np.array([7.0, -3.0, 4.0])

    fitted = _fit_similarity(source, target)

    assert fitted.scale == pytest.approx(2.5)
    assert np.linalg.det(fitted.rotation) == pytest.approx(1.0)
    assert fitted.apply(source) == pytest.approx(target)


def test_resample_curve_uses_normalized_arclength() -> None:
    curve = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 3.0, 0.0]],
        dtype=np.float64,
    )

    result = _resample_curve(curve, 5)

    assert result == pytest.approx(
        np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [1.0, 1.0, 0.0],
                [1.0, 2.0, 0.0],
                [1.0, 3.0, 0.0],
            ]
        )
    )


def test_closest_surface_coordinates_return_face_and_edge_barycentrics() -> None:
    mesh = TriangleMesh(
        vertices=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)),
        triangles=((0, 1, 2),),
    )
    points = np.array([[0.5, 0.5, 3.0], [2.0, 2.0, 0.0]], dtype=np.float64)

    distances, triangles, weights = _closest_surface_coordinates(points, mesh)

    assert distances == pytest.approx([3.0, np.sqrt(2.0)])
    assert triangles.tolist() == [0, 0]
    assert weights[0] == pytest.approx([0.5, 0.25, 0.25])
    assert weights[1] == pytest.approx([0.0, 0.5, 0.5])


def test_curve_validation_rejects_degenerate_curve() -> None:
    with pytest.raises(ModernCurveValidationError, match="zero-length"):
        _resample_curve(
            np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float64),
            4,
        )


def test_preprocessing_source_path_cannot_escape(tmp_path: Path) -> None:
    preprocessing = tmp_path / "preprocessing"
    preprocessing.mkdir()
    outside = tmp_path / "outside.vtk"
    outside.write_text("not a mesh", encoding="ascii")

    with pytest.raises(ModernCurveValidationError, match="escapes preprocessing"):
        _safe_preprocessing_path(preprocessing, "../outside.vtk", "raw mesh")


def _fake_computation(tmp_path: Path) -> tuple[dict, dict]:
    source = {
        "mapping": {"path": str(tmp_path / "mapping.csv"), "sha256": "a" * 64},
        "curve_directory": str(tmp_path / "curves"),
        "curve_inventory": [],
        "preprocessing_directory": str(tmp_path / "preprocessing"),
        "procrustes": {"path": str(tmp_path / "procrustes.json"), "sha256": "b" * 64},
        "current_landmarks": {
            "path": str(tmp_path / "landmarks.csv"),
            "sha256": "c" * 64,
        },
        "mapping_rows": [],
        "reference_bundle": {
            "bundle_directory": str(tmp_path / "reference"),
            "manifest_sha256": "d" * 64,
        },
        "comparison_bundle": {
            "bundle_directory": str(tmp_path / "comparison"),
            "manifest_sha256": "e" * 64,
        },
    }
    evidence = {
        "sample_count": 8,
        "included_subject_count": 3,
        "paired": {"subject_curve_distance_spearman": 0.95},
    }
    return source, evidence


def test_curve_validation_artifact_is_exclusive_and_recomputed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, evidence = _fake_computation(tmp_path)
    monkeypatch.setattr(validation_module, "_compute", lambda *args, **kwargs: (source, evidence))
    destination = write_modern_curve_validation(
        tmp_path / "mapping.csv",
        tmp_path / "curves",
        tmp_path / "preprocessing",
        tmp_path / "reference",
        tmp_path / "comparison",
        tmp_path / "artifact",
        sample_count=8,
        created_at="2026-08-27T08:00:00+00:00",
    )

    verified = verify_modern_curve_validation(destination)

    assert verified.manifest["evidence"] == evidence
    assert {path.name for path in destination.iterdir()} == {
        MODERN_CURVE_VALIDATION_MANIFEST,
        MODERN_CURVE_VALIDATION_SIDECAR,
    }
    with pytest.raises(FileExistsError, match="already exists"):
        write_modern_curve_validation(
            tmp_path / "mapping.csv",
            tmp_path / "curves",
            tmp_path / "preprocessing",
            tmp_path / "reference",
            tmp_path / "comparison",
            destination,
            sample_count=8,
        )


def test_curve_validation_rejects_changed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, evidence = _fake_computation(tmp_path)
    monkeypatch.setattr(validation_module, "_compute", lambda *args, **kwargs: (source, evidence))
    destination = write_modern_curve_validation(
        tmp_path / "mapping.csv",
        tmp_path / "curves",
        tmp_path / "preprocessing",
        tmp_path / "reference",
        tmp_path / "comparison",
        tmp_path / "artifact",
        sample_count=8,
    )
    manifest_path = destination / MODERN_CURVE_VALIDATION_MANIFEST
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["evidence"]["included_subject_count"] = 4
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (destination / MODERN_CURVE_VALIDATION_SIDECAR).write_text(
        sha256_file(manifest_path) + "\n", encoding="ascii"
    )

    with pytest.raises(ModernCurveValidationError, match="exact recomputation"):
        verify_modern_curve_validation(destination)

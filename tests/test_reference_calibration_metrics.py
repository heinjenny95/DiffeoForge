import json
import weakref
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.mesh import TriangleMesh, write_vtk_polydata
from diffeoforge.reference_calibration_metrics import (
    atlas_rms_distance,
    symmetric_nearest_vertex_distances,
)


def _triangle(offset: float = 0.0) -> TriangleMesh:
    return TriangleMesh(
        vertices=(
            (offset, 0.0, 0.0),
            (offset, 1.0, 0.0),
            (offset, 0.0, 1.0),
        ),
        triangles=((0, 1, 2),),
    )


def test_symmetric_surface_distance_is_deterministic_and_zero_for_identity() -> None:
    mesh = _triangle()

    first = symmetric_nearest_vertex_distances(mesh, mesh)
    second = symmetric_nearest_vertex_distances(mesh, mesh)

    assert np.array_equal(first, second)
    assert first.tolist() == [0.0] * 6


def test_symmetric_surface_distance_reports_known_rigid_offset() -> None:
    distances = symmetric_nearest_vertex_distances(_triangle(), _triangle(2.0))

    assert distances.tolist() == pytest.approx([2.0] * 6)


def test_atlas_rms_uses_ordered_vertex_displacement(tmp_path: Path) -> None:
    first = _triangle()
    second = _triangle(2.0)
    first_path = write_vtk_polydata(
        tmp_path / "first.vtk",
        first.vertices,
        first.triangles,
    )
    second_path = write_vtk_polydata(
        tmp_path / "second.vtk",
        second.vertices,
        second.triangles,
    )

    assert atlas_rms_distance(first_path, second_path) == pytest.approx(2.0)


def test_streaming_qc_preserves_metrics_and_releases_meshes(tmp_path, monkeypatch) -> None:
    from test_reference_pca import _completed_reference_run

    import diffeoforge.reference_calibration_metrics as metrics

    run = _completed_reference_run(tmp_path)
    original_read = metrics.read_vtk_polydata
    references = []
    peak = 0

    def observed_read(path):
        nonlocal peak
        mesh = original_read(path)
        references.append(weakref.ref(mesh))
        peak = max(peak, sum(ref() is not None for ref in references))
        return mesh

    monkeypatch.setattr(metrics, "read_vtk_polydata", observed_read)
    progress = []
    result = metrics.collect_reference_calibration_run_metrics(
        run, progress_callback=lambda *event: progress.append(event)
    )
    # Values recorded from the pre-streaming collector on this public fixture.
    assert result.residual_p95 == pytest.approx(0.1224935837467765, abs=1e-14)
    assert result.residual_median == pytest.approx(0.06618590560140142, abs=1e-14)
    assert result.resampling_sensitivity == pytest.approx(0.004178237626624071, abs=1e-14)
    assert result.distortion_p95 == 0.0
    assert result.invalid_face_count == 0
    assert result.subject_reconstruction_count == 5
    assert result.converged is True
    assert result.metric_version == "0.2"
    assert peak <= 3  # Initial template plus current reconstruction and target.
    assert not any(ref() is not None for ref in references)
    assert [(c, t) for c, t, _ in progress] == [(c, 5) for c in range(6)]
    assert [p[2] for p in progress[1:]] == [s for s, _ in result.subject_residual_p95]


def test_streaming_qc_still_rejects_changed_source(tmp_path) -> None:
    from test_reference_pca import _completed_reference_run

    from diffeoforge.config import ConfigurationError
    from diffeoforge.reference_calibration_metrics import collect_reference_calibration_run_metrics

    run = _completed_reference_run(tmp_path)
    path = next((run / "input" / "subjects").glob("*.vtk"))
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ConfigurationError):
        collect_reference_calibration_run_metrics(run)


def test_streaming_distortion_matches_independent_nonzero_area_ratio(tmp_path) -> None:
    from test_reference_pca import _completed_reference_run

    from diffeoforge.mesh import read_vtk_polydata, sha256_file
    from diffeoforge.reference_calibration_metrics import collect_reference_calibration_run_metrics

    run = _completed_reference_run(tmp_path)
    inventory_path = run / "output-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected = []
    scales = iter((0.7, 0.9, 1.1, 1.2, 1.4, 1.8))
    for record in inventory["files"]:
        path = run / "output" / record["path"]
        if path.suffix != ".vtk":
            continue
        mesh = read_vtk_polydata(path)
        scale = next(scales)
        vertices = tuple(tuple(scale * coordinate for coordinate in v) for v in mesh.vertices)
        path.unlink()  # Replace only this test's generated synthetic output.
        write_vtk_polydata(path, vertices, mesh.triangles)
        record.update(bytes=path.stat().st_size, sha256=sha256_file(path))
        # Uniform linear scaling multiplies every triangle area by scale squared.
        expected.extend([abs(2 * np.log(scale))] * len(mesh.triangles))
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    result_path = run / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["outputs"].update(
        inventory_sha256=sha256_file(inventory_path),
        total_bytes=sum(record["bytes"] for record in inventory["files"]),
    )
    result_path.write_text(json.dumps(result), encoding="utf-8")
    observed = collect_reference_calibration_run_metrics(run)
    assert observed.distortion_p95 == pytest.approx(np.quantile(expected, 0.95), abs=1e-14)
    assert observed.invalid_face_count == 0

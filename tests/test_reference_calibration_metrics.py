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


def test_regional_area_qc_uses_bound_conforming_source_grid_and_rejects_tampering(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from diffeoforge import reference_calibration_metrics as metrics
    from diffeoforge import regional_fit
    from diffeoforge.mesh import sha256_file

    for name in ('input', 'input/regional', 'output', 'logs'):
        (tmp_path/name).mkdir(exist_ok=True)
    original = _triangle()
    template = write_vtk_polydata(tmp_path/'input/original.vtk',
                                  original.vertices, original.triangles)
    vertices = (*original.vertices, (0, .5, 0), (0, .5, .5), (0, 0, .5))
    faces = ((0, 3, 5), (3, 1, 4), (5, 4, 2), (3, 4, 5))
    grid = write_vtk_polydata(tmp_path/'input/regional/grid.vtk', vertices, faces)
    subject = write_vtk_polydata(tmp_path/'input/a.vtk', vertices, faces)
    atlas = write_vtk_polydata(tmp_path/'output/S__EstimatedParameters__Template_surface.vtk',
                              vertices, faces)
    reconstruction = write_vtk_polydata(
        tmp_path/'output/S__Reconstruction__surface__subject_a.vtk.vtk', vertices, faces)
    def input_row(path, role):
        return dict(staged_path=path.relative_to(tmp_path).as_posix(), role=role,
                    geometry=dict(bytes=path.stat().st_size, sha256=sha256_file(path)))
    report = SimpleNamespace(run_directory=tmp_path,
        result=dict(status='completed', duration_seconds=1), max_iterations=1,
        inventory=[dict(path=p.name) for p in (atlas, reconstruction)],
        convergence=[SimpleNamespace(iteration=1, regularity=-1, attachment=-2)],
        manifest=dict(inputs=[input_row(template, 'template'), input_row(subject, 'subject')],
            effective_config=dict(model=dict(object_id='surface'),
                project=dict(parameter_provenance=dict(regional_fit=dict(version='fixture'))))))
    (tmp_path/'logs/deformetrica.log').write_text('Tolerance threshold met.')
    bound = dict(copy=grid.name, sha256=sha256_file(grid))
    monkeypatch.setattr(regional_fit, 'read_plan',
                        lambda _: dict(residual=dict(original_source_grid=bound)))
    value = metrics._collect_reference_calibration_metrics_from_report(report)
    assert value.distortion_p95 == 0 and value.invalid_face_count == 0
    assert any('conforming original-source' in note for note in value.notes)
    # This exception remains for ordinary changed-connectivity atlas outputs.
    report.manifest['effective_config']['project']['parameter_provenance'].clear()
    with pytest.raises(ValueError, match='connectivity differs'):
        metrics._collect_reference_calibration_metrics_from_report(report)
    report.manifest['effective_config']['project']['parameter_provenance']['regional_fit'] = {}
    report.manifest['effective_config']['project']['parameter_provenance']['regional_fit'] = dict(
        version='fixture')
    grid.write_text(grid.read_text()+'\n')
    with pytest.raises(ValueError, match='source grid changed'):
        metrics._collect_reference_calibration_metrics_from_report(report)


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

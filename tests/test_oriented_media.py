"""Complete renderer contract using small synthetic, already-computed native samples."""

import json
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("vtk")
pytest.importorskip("PySide6")
pytest.importorskip("matplotlib")
pytest.importorskip("imageio_ffmpeg")

from diffeoforge import oriented_media as oriented
from diffeoforge.desktop.mesh_view import preset_views
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.pca_media import _record, _render_media, verify_media
from diffeoforge.reference_pca_deformations import DEFAULT_RESULT_DIRECTORY


def seal(root, run, sources, pca):
    data = {
        "version": "2",
        "status": "complete",
        "source_run": str(run),
        "sources": sources,
        "files": [
            {**_record(p), "path": p.relative_to(root).as_posix()}
            for p in sorted(root.rglob("*"))
            if p.is_file()
        ],
        "specimen_labels": list(pca.sample_labels),
        "pca_method": "Synthetic renderer fixture",
        "subject_count": 2,
    }
    manifest = root / "media.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    (root / "media.sha256").write_text(sha256_file(manifest))


def synthetic_media(tmp_path):
    run, base = tmp_path / "run", tmp_path / "views" / "base"
    endpoint_root = run / DEFAULT_RESULT_DIRECTORY
    endpoint_root.mkdir(parents=True)
    sample_root = base / "native-display-samples"
    (sample_root / "output").mkdir(parents=True)
    mean = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.2, 0.3, 0.8]])
    faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
    np.save(base / "proxy-source-vertex-ids.npy", np.arange(4))
    endpoints, reconstructions = [], []
    mean_path = endpoint_root / "mean.vtk"
    write_vtk_polydata(mean_path, mean, faces)
    endpoints.append({**_record(mean_path), "role": "mean"})
    for pc in range(1, 4):
        for sd in np.linspace(-2, 2, 17):
            values = mean.copy()
            values[3, pc - 1] += sd * 0.1
            index = (pc - 1) * 17 + round((sd + 2) * 4)
            write_vtk_polydata(
                sample_root / f"output/Shooting_{index}__endpoint.vtk", values, faces
            )
            if sd in (-2.0, 2.0):
                direction = "minus" if sd < 0 else "plus"
                path = endpoint_root / f"PC{pc}-{direction}.vtk"
                write_vtk_polydata(path, values, faces)
                endpoints.append(
                    {**_record(path), "role": "axis", "component": pc, "direction": direction}
                )
    (sample_root / "samples.json").write_text(
        json.dumps(
            {
                "return_code": 0,
                "components": [1, 2, 3],
                "anchor_tolerance": 1e-10,
            }
        )
    )
    pca = SimpleNamespace(
        scores=np.array([[-1.0, 2.0, 3.0], [1.0, -2.0, -3.0]]),
        explained_variance_ratio=np.array([0.6, 0.3, 0.1]),
        sample_labels=("A", "B"),
        number_of_components=3,
    )
    for index, label in enumerate(pca.sample_labels):
        path = run / f"Atlas__Reconstruction__shape__subject_{label}.vtk"
        write_vtk_polydata(path, mean * (1 + 0.1 * index), faces)
        reconstructions.append(_record(path))
    _render_media(
        base,
        pca,
        reconstructions,
        endpoints,
        lambda _: None,
        threading.Event(),
        endpoint_root=endpoint_root,
        config=None,
        sample_source=base,
    )
    seal(base, run, reconstructions + endpoints, pca)
    return run, base, endpoint_root, endpoints, pca


def test_every_medium_rerenders_without_native_execution_or_changed_scores(tmp_path, monkeypatch):
    from diffeoforge import reference_pca_samples

    monkeypatch.setattr(
        reference_pca_samples,
        "native_axis_samples",
        lambda *a, **kw: pytest.fail("Orientation must never execute Shooting"),
    )
    run, base, endpoint_root, endpoints, pca = synthetic_media(tmp_path)
    before = {p: sha256_file(p) for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        oriented, "verify_reference_pca_bundle", lambda *a, **kw: SimpleNamespace(pca=pca)
    )
    result = {
        "result_version": "0.2",
        "endpoints": [
            {**record, "path": Path(record["path"]).relative_to(endpoint_root).as_posix()}
            for record in endpoints
        ],
    }
    monkeypatch.setattr(
        oriented, "verify_reference_pca_deformation_result", lambda *a, **kw: result
    )
    target = oriented.prepare_oriented_media(base, preset_views()[2][1], "Chosen surface")
    data = verify_media(target, source_run=run)
    assert data["mesh_view"]["scope"] == "all visualizations"
    assert {p: sha256_file(p) for p in before} == before
    for relative in (
        "PCA-Gallery/thumbnails/1.png",
        "PCA-Gallery/figures/PC1-SD.png",
        "PCA-Gallery/figures/PC1-plus-displacement.png",
        "PCA-Gallery/figures/PC1-plus-normal-displacement.png",
        "PCA-Gallery/videos/PC1-six-views.mp4",
    ):
        assert sha256_file(target / relative) != sha256_file(base / relative)
    rows = json.loads((target / "PCA-Gallery/mesh-pca.json").read_text())
    np.testing.assert_array_equal([row["scores"] for row in rows], pca.scores)
    assert [row["label"] for row in rows] == ["A", "B"]
    original = json.loads((base / "rendering.json").read_text())
    rendering = json.loads((target / "rendering.json").read_text())
    for key in ("camera_bounds", "displacement_range", "normal_component_range", "movie_frames"):
        assert rendering[key] == original[key]
    np.testing.assert_array_equal(rendering["views"][0][1], preset_views()[2][1][2])
    assert len(rendering["views"]) == 6
    with zipfile.ZipFile(target / "PCA-Gallery.zip") as archive:
        assert not any(
            name.endswith((".vtk", ".npy", ".npz", ".log")) for name in archive.namelist()
        )
        assert (
            json.loads(archive.read("PCA-Gallery/mesh-view.json"))["scope"] == "all visualizations"
        )
    assert oriented.prepare_oriented_media(base, preset_views()[2][1], "Chosen surface") == target
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        oriented.prepare_oriented_media(base, preset_views()[0][1], "Cancelled", cancelled)
    assert not list(target.parent.glob(".*.tmp-*"))

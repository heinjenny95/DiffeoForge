import json
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from diffeoforge.analysis.pca_shape_plate import shape_plate


def test_pc_shape_plate_marks_only_extrapolated_examples(monkeypatch):
    labels = []
    draw_text = ImageDraw.ImageDraw.text

    def record(self, xy, text, *args, **kwargs):
        labels.append(text)
        return draw_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)
    frames = [Image.new("RGBA", (420, 360), "teal")] * 3
    scores = np.array([-6.0, 1.0, 2.0, 3.0])
    shape_plate(1, scores, (-4, 0, 4), ("−2 SD", "Mean", "+2 SD"),
                frames, ImageFont.load_default(), standard_deviation=2)
    assert "Observed PC scores · 4 specimens · -6 to 3" in labels
    assert "+2 SD · score 4" in labels
    assert labels.count("Outside observed range") == 1
    labels.clear()
    shape_plate(1, scores, (-6, 0, 3), ("Observed minimum", "Mean", "Observed maximum"),
                frames, ImageFont.load_default(), standard_deviation=2)
    assert "Observed minimum · score -6" in labels
    assert "Observed maximum · score 3" in labels
    assert "Outside observed range" not in labels


def test_native_display_sample_extrema_use_exact_saved_scores(tmp_path, monkeypatch):
    pytest.importorskip("vtk")
    from diffeoforge import reference_pca_samples as samples
    from diffeoforge.mesh import write_vtk_polydata

    origin = tmp_path / "verified-endpoints"
    for name in ("source", "engine"):
        (origin / name).mkdir(parents=True)
    (origin / "source/control-points.txt").write_text("0 0 0")
    (origin / "engine/model.xml").write_text("<model/>")
    (origin / "engine/optimization_parameters.xml").write_text("<optimization-parameters/>")
    template = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    faces = np.array([[0, 1, 2]])
    template_path = tmp_path / "template.vtk"
    write_vtk_polydata(template_path, template, faces)
    mesh = samples.read_mesh(template_path)
    pca = SimpleNamespace(
        scores=np.array([[-6.0], [1.0], [2.0], [3.0]]),
        mean=np.array([2.0, 0.0, 0.0]),
        explained_variance=np.array([4.0]),
        components=np.array([[1.0, 0.0, 0.0]]),
    )
    root = tmp_path / "display-shooting"
    fields = []
    write_momenta = samples._write_momenta

    def capture(path, values):
        fields.extend(values)
        write_momenta(path, values)

    def endpoint(momentum):
        points = template.copy()
        points[2, 2] += float(momentum) / 100
        return points

    def runner(*_args, **_kwargs):
        for i, field in enumerate(fields):
            write_vtk_polydata(root / f"output/Shooting_{i}__endpoint.vtk",
                               endpoint(field[0, 0]), faces)
            (root / f"output/Shooting_{i}__grid.json").write_text("{}")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(samples, "_write_momenta", capture)
    monkeypatch.setattr(samples, "_number_of_time_points", lambda _: 37)
    monkeypatch.setattr(samples, "_verify_grid", lambda *args: None)
    monkeypatch.setattr(samples, "_backend_process_working_directory", lambda *_: root)
    monkeypatch.setattr(
        samples, "build_shooting_command",
        lambda *_args, **_kwargs: SimpleNamespace(argv=[], environment={}, working_directory=root),
    )
    grid, observed = samples.native_axis_samples(
        root, endpoint_root=origin, pca=pca, config={"runtime": {"precision": "float64"}},
        template_proxy=mesh, components=[1],
        anchors={(1, "minus"): endpoint(-2), (1, "mean"): endpoint(2),
                 (1, "plus"): endpoint(6)}, scale=2.0, process_runner=runner,
    )
    assert grid.shape == (1, 17, 3, 3)
    assert len(fields) == 19
    np.testing.assert_array_equal(observed[1, "minimum"], endpoint(-4))
    np.testing.assert_array_equal(observed[1, "maximum"], endpoint(5))
    receipt = json.loads((root / "samples.json").read_text())
    assert receipt["observed_endpoints"] == [
        {"pc": 1, "side": "minimum", "score": -6.0, "sd": -3.0, "output_index": 17},
        {"pc": 1, "side": "maximum", "score": 3.0, "sd": 1.5, "output_index": 18},
    ]


def test_pc_shape_selection_switches_verified_export_source(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop import visualization_panel as ui

    application = QApplication.instance() or QApplication([])
    panel = ui.VisualizationPanel()
    panel.directory = tmp_path
    figures = tmp_path / "PCA-Gallery" / "figures"
    figures.mkdir(parents=True)
    standard, observed = figures / "PC1-SD.png", figures / "PC1-observed.png"
    for path, color in ((standard, "teal"), (observed, "purple")):
        Image.new("RGB", (80, 60), color).save(path)
    panel.sd_combo.addItem("PC1", standard)
    assert not panel.sd_range_combo.isEnabled()
    panel._records = {
        p.relative_to(tmp_path).as_posix(): {"path": p.name}
        for p in (standard, observed)
    }
    panel._show_pc_shapes()
    panel.tabs.setCurrentIndex(1)
    panel.sd_range_combo.setCurrentIndex(1)
    assert panel.sd_range_combo.isEnabled()
    assert panel.sd_combo.currentData() == observed
    sources = []
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName",
                        lambda *args: (str(tmp_path / "export.png"), "PNG"))
    monkeypatch.setattr(panel, "_start_export",
                        lambda _target, **kwargs: sources.append(kwargs["source"]))
    panel._export_current()
    assert sources == [observed]
    panel.sd_range_combo.setCurrentIndex(0)
    assert panel.sd_combo.currentData() == standard
    panel.close()
    application.processEvents()


def test_old_media_is_preserved_and_retry_publishes_one_new_cache(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from diffeoforge import media_runtime, pca_media
    from diffeoforge.desktop import widgets
    from diffeoforge.mesh import sha256_file

    run = tmp_path / "runs" / "saved"
    bundle = run / pca_media.DEFAULT_REFERENCE_PCA_DIRECTORY
    result = run / pca_media.DEFAULT_RESULT_DIRECTORY
    design = run / "analysis" / widgets.DEFAULT_REFERENCE_PCA_DEFORMATION_DESIGN_DIRECTORY
    for directory in (bundle, result, design, run / "output"):
        directory.mkdir(parents=True, exist_ok=True)
    for path in (
        bundle / pca_media.REFERENCE_PCA_MANIFEST, result / pca_media.RESULT_NAME,
        run / "manifest.json", run / "result.json", run / "output-inventory.json",
        result / "mean.vtk", run / "output/Atlas__Reconstruction__subject_A.vtk",
    ):
        path.write_text(path.name)

    identity = sha256((
        sha256_file(bundle / pca_media.REFERENCE_PCA_MANIFEST)
        + sha256_file(result / pca_media.RESULT_NAME)
    ).encode()).hexdigest()
    old = tmp_path / "visualizations" / f"pca-{identity[:20]}-v3"
    old.mkdir(parents=True)
    original = old / "old-shapes.png"
    original.write_bytes(b"Earlier visualization")
    old_manifest = old / "media.json"
    old_manifest.write_text(json.dumps({
        "version": "3", "status": "complete", "source_run": str(run),
        "sources": [pca_media._record(run / "manifest.json")],
        "files": [{**pca_media._record(original), "path": original.name}],
    }))
    (old / "media.sha256").write_text(sha256_file(old_manifest))
    old_hashes = {path: sha256_file(path) for path in old.iterdir()}

    pca = SimpleNamespace(number_of_components=1, sample_labels=["A"], method="test")
    mean_record = {**pca_media._record(result / "mean.vtk"), "path": "mean.vtk"}

    def verify_bundle(*_args, **_kwargs):
        return SimpleNamespace(pca=pca)

    def verify_result(*_args, **_kwargs):
        return {"result_version": "0.2", "endpoints": [mean_record]}

    for module in (pca_media, widgets):
        monkeypatch.setattr(module, "verify_reference_pca_bundle", verify_bundle)
        monkeypatch.setattr(module, "verify_reference_pca_deformation_result", verify_result)
    monkeypatch.setattr(media_runtime, "verify_media_runtime", lambda: None)
    monkeypatch.setattr(widgets, "verify_reference_pca_deformation_design", lambda *a, **k: None)
    monkeypatch.setattr(
        widgets, "execute_reference_pca_deformation_design",
        lambda *a, **k: pytest.fail("The saved full native endpoints must be reused"),
    )
    reconstruction = run / "output/Atlas__Reconstruction__subject_A.vtk"
    run_report = SimpleNamespace(
        inventory=[{**pca_media._record(reconstruction), "path": reconstruction.name}],
        manifest={"effective_config": {}},
    )
    monkeypatch.setattr(
        pca_media, "load_reference_momenta",
        lambda *_: SimpleNamespace(run_report=run_report),
    )
    preparations = []

    def render(directory, *args, **kwargs):
        preparations.append(directory)
        (directory / "observed.png").write_bytes(b"Exact observed example")

    monkeypatch.setattr(pca_media, "_render_media", render)
    succeeded, failed = [], []
    for _ in range(2):
        worker = widgets._ReferencePCADeformationWorker(run)
        worker.signals.succeeded.connect(succeeded.append)
        worker.signals.failed.connect(failed.append)
        worker.run()
    assert failed == []
    assert len(preparations) == 1
    assert len(succeeded) == 2 and succeeded[0] == succeeded[1]
    assert succeeded[0].name.endswith(f"-v{pca_media.MEDIA_VERSION}")
    assert pca_media.verify_media(old, source_run=run)["version"] == "3"
    assert {path: sha256_file(path) for path in old.iterdir()} == old_hashes

import hashlib
import os
from types import SimpleNamespace

import numpy as np
import pytest
from pilot_view_helpers import wait_pilot_view

from diffeoforge.iteration_budget import recommend_iteration_budget
from diffeoforge.mesh import write_vtk_polydata
from diffeoforge.reference_pca_deformations import ReferencePCADeformationError, _verify_grid


def test_full_geometry_cache_avoids_reparse_but_hashes_changed_bytes(tmp_path, monkeypatch):
    from diffeoforge.desktop import mesh_preview as preview

    source = tmp_path / "mesh.vtk"
    other = tmp_path / "other.vtk"
    write_vtk_polydata(source, [(0, 0, 0), (1, 0, 0), (0, 1, 1)], [(0, 1, 2)])
    other.write_bytes(source.read_bytes())
    preview.clear_mesh_preview_cache()
    loader, loads = preview.load_surface_mesh, []

    def measured(path):
        loads.append(path)
        return loader(path)

    monkeypatch.setattr(preview, "load_surface_mesh", measured)
    first = preview.load_mesh_preview(source)
    second = preview.load_mesh_preview(source)
    copied = preview.load_mesh_preview(other)
    assert len(loads) == 1 and first == second and copied.path == other
    stat = source.stat()
    original = source.read_bytes()
    source.write_bytes(original.replace(b"0 1 1", b"0 1 2"))
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = preview.load_mesh_preview(source)
    assert len(loads) == 2 and changed.sha256 != first.sha256
    assert changed.vertices != first.vertices


def test_native_grid_receipt_rejects_intermediate_time_and_wrong_momenta():
    field = np.zeros((3, 3), dtype=np.float32)
    grid = {
        "times": np.linspace(0, 1, 10).tolist(),
        "timepoints": 10,
        "exported_time": 1,
        "precision": "float32",
        "momenta_sha256": hashlib.sha256(field.tobytes()).hexdigest(),
    }
    _verify_grid(grid, 10, field)
    with pytest.raises(ReferencePCADeformationError):
        _verify_grid({**grid, "exported_time": 0.9}, 10, field)
    with pytest.raises(ReferencePCADeformationError):
        _verify_grid({**grid, "times": np.linspace(0, 1, 11).tolist()}, 10, field)
    with pytest.raises(ReferencePCADeformationError):
        _verify_grid(grid, 10, field + 1)


def test_iteration_budget_uses_selected_observation_not_control_count_or_failed_options():
    observations = [
        {"candidate_id": "chosen", "final_iteration": 198, "maximum_iterations": 200},
        {"candidate_id": "other", "final_iteration": 20_000, "maximum_iterations": 20_000},
    ]
    budget = recommend_iteration_budget(200, observations, ["chosen"])
    assert budget["suggested_max_iterations"] == 500
    assert budget["pilot_near_iteration_cap"]
    assert (
        recommend_iteration_budget(250_000, observations, ["chosen"])["suggested_max_iterations"]
        == 250_000
    )
    assert (
        recommend_iteration_budget(700, observations, ["chosen"])["suggested_max_iterations"] == 700
    )
    assert (
        recommend_iteration_budget(200, observations, ["missing"])["suggested_max_iterations"]
        == 200
    )


def test_fresh_pilot_guided_action_and_scrolling_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_reference_calibration_study import _project

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.reference_calibration_study import create_reference_calibration_study

    app = QApplication.instance() or QApplication([])
    snapshot = create_reference_calibration_study(_project(tmp_path), tmp_path / "pilot")
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    wait_pilot_view(dialog)
    dialog.resize(850, 650)
    dialog.show()
    app.processEvents()
    try:
        assert not dialog.advanced_mode.isChecked()
        assert dialog.start_button.text() == "Find fit"
        assert dialog.scroll.height() >= 200
        assert not dialog.find_fit_button.isVisible()  # Collapsed tools must own their widgets.
        assert not dialog.adaptive_fit_search.isVisible()
        assert dialog.start_button.isVisible()
        assert dialog.start_button.mapTo(dialog, dialog.start_button.rect().bottomRight()).y() < 650
        starts = []
        monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: starts.append(kwargs))
        dialog._start()
        assert starts == [{"adaptive": False, "specimen_fit": True}]
        dialog.pilot_tools.toggle_button.click()
        app.processEvents()
        assert dialog.find_fit_button.isVisible()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("close_before_dispatch", [False, True])
def test_automatic_axis_media_wait_for_release_and_dispatch_once(
    tmp_path, monkeypatch, close_before_dispatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    app = QApplication.instance() or QApplication([])
    window = DiffeoForgeWindow()
    window.show()
    released = [False]
    started = []

    def missing(_key):
        raise KeyError("No shapes")

    review = SimpleNamespace(
        engine_route="deformetrica_reference",
        run_directory=tmp_path,
        bundle_manifest_sha256="a" * 64,
        artifact=missing,
    )
    window._result_review = review
    monkeypatch.setattr(window, "_registration_results_released", lambda: released[0])
    monkeypatch.setattr(window, "_start_reference_pca_deformations", lambda: started.append(review))
    try:
        window._sync_reference_pca_deformation_action(review)
        app.processEvents()
        assert not started
        released[0] = True
        window._sync_reference_pca_deformation_action(review)
        window._sync_reference_pca_deformation_action(review)
        if close_before_dispatch:
            window.hide()
        app.processEvents()
        assert len(started) == (0 if close_before_dispatch else 1)
    finally:
        window._result_review = None
        window.close()
        app.processEvents()


def test_cancel_before_visualization_worker_starts_launches_no_native_work(tmp_path, monkeypatch):
    from diffeoforge.desktop import widgets

    monkeypatch.setattr(
        widgets,
        "verify_reference_pca_bundle",
        lambda *_args, **_kwargs: pytest.fail("Cancelled worker read source"),
    )
    worker = widgets._ReferencePCADeformationWorker(tmp_path)
    errors = []
    worker.signals.failed.connect(errors.append)
    worker.request_cancel()
    worker.run()
    assert errors and "cancelled before native work" in errors[0]

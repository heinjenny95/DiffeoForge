from __future__ import annotations

from pathlib import Path

import pytest

from diffeoforge.input_preflight import (
    HEAVY_COHORT_FACE_COUNT,
    assess_mesh_input_metadata,
)
from diffeoforge.mesh import write_vtk_polydata
from diffeoforge.surface_io import SurfaceMeshMetadata

ROOT = Path(__file__).parents[1]


def _metadata(path: Path, *, diagonal: float, triangles: int = 4) -> SurfaceMeshMetadata:
    return SurfaceMeshMetadata(
        path=str(path.resolve()),
        bytes=path.stat().st_size,
        sha256=(path.name.encode("utf-8").hex() + "0" * 64)[:64],
        source_format="legacy_vtk",
        encoding="ASCII",
        points=max(4, triangles // 2),
        triangles=triangles,
        bounds=(0.0, diagonal, 0.0, 0.0, 0.0, 0.0),
        bounding_box_extents=(diagonal, 0.0, 0.0),
        bounding_box_diagonal=diagonal,
        topology_note="test",
    )


def _ready_window(tmp_path: Path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["input-preflight-test"])
    window = DiffeoForgeWindow()
    directory = ROOT / "examples" / "synthetic" / "meshes"
    window.mesh_edit.setText(str(directory))
    window.template_edit.setText(str(directory / "template.vtk"))
    window.pattern_edit.setText("subject-*.vtk")
    window.project_edit.setText(str(tmp_path / "project"))
    window.units_combo.setCurrentIndex(window.units_combo.findData("millimeter"))
    paths, _landmarks, signature = window._input_preflight_request()
    return application, window, paths, signature


class _QueuedPool:
    def __init__(self):
        self.workers = []

    def start(self, worker):
        self.workers.append(worker)


def test_path_editing_enter_and_alignment_changes_never_dispatch(tmp_path, monkeypatch):
    application, window, _paths, _signature = _ready_window(tmp_path, monkeypatch)
    pool = _QueuedPool()
    window._thread_pool = pool
    for field in (window.mesh_edit, window.template_edit, window.pattern_edit,
                  window.landmarks_edit):
        field.editingFinished.emit()
    window.procrustes_scaling_combo.setCurrentIndex(2)
    window.procrustes_apply_check.setChecked(False)
    application.processEvents()
    assert pool.workers == []
    assert not window.continue_parameter_button.isEnabled()
    window.validate_meshes_button.click()
    window.validate_meshes_button.click()
    assert len(pool.workers) == 1
    assert not window.validate_meshes_button.isEnabled()
    window._input_preflight_worker = None
    window.close()


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_changed_inputs_discard_result_without_queued_restart(tmp_path, monkeypatch, outcome):
    application, window, paths, signature = _ready_window(tmp_path, monkeypatch)
    pool = _QueuedPool()
    window._thread_pool = pool
    window.validate_meshes_button.click()
    window.procrustes_scaling_combo.setCurrentIndex(2)
    assert window._current_input_preflight_signature() != signature
    if outcome == "success":
        report = assess_mesh_input_metadata(tuple(_metadata(p, diagonal=1) for p in paths))
        pool.workers[0].signals.succeeded.emit(report)
    else:
        pool.workers[0].signals.failed.emit("old selection failed")
    application.processEvents()
    assert len(pool.workers) == 1
    assert window._input_preflight is None
    assert window._input_preflight_worker is None
    assert not window.continue_parameter_button.isEnabled()
    assert window.validate_meshes_button.isEnabled()
    assert "Click Run deep mesh validation" in window.input_preflight_status_label.text()
    window.validate_meshes_button.click()
    assert len(pool.workers) == 2
    window._input_preflight_worker = None
    window.close()


def test_failure_focus_loss_does_not_retry_but_explicit_button_does(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    application, window, _paths, signature = _ready_window(tmp_path, monkeypatch)
    pool = _QueuedPool()
    window._thread_pool = pool
    # Emulate the editingFinished signal emitted as the failure dialog takes focus.
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *_: window.template_edit.editingFinished.emit()
    )
    window.validate_meshes_button.click()
    pool.workers[0].signals.failed.emit("mismatched landmarks")
    application.processEvents()
    assert len(pool.workers) == 1
    assert window._input_preflight_failed_signature == signature
    assert not window._data_inputs_ready()
    window.validate_meshes_button.click()
    assert len(pool.workers) == 2
    window._input_preflight_worker = None
    window.close()


def test_success_allows_progress_without_rechecking_unchanged_inputs(tmp_path, monkeypatch):
    application, window, paths, _signature = _ready_window(tmp_path, monkeypatch)
    pool = _QueuedPool()
    window._thread_pool = pool
    assert not window._data_inputs_ready()
    window.validate_meshes_button.click()
    report = assess_mesh_input_metadata(tuple(_metadata(p, diagonal=1) for p in paths))
    pool.workers[0].signals.succeeded.emit(report)
    application.processEvents()
    assert window._data_inputs_ready()
    assert window.continue_parameter_button.isEnabled()
    assert not window.validate_meshes_button.isEnabled()
    window.mesh_edit.editingFinished.emit()
    window._start_input_preflight()
    assert len(pool.workers) == 1
    window.close()


def test_missing_landmark_path_is_not_silently_ignored(tmp_path, monkeypatch):
    application, window, _paths, _signature = _ready_window(tmp_path, monkeypatch)
    pool = _QueuedPool()
    window._thread_pool = pool
    window.landmarks_edit.setText(str(tmp_path / "missing.csv"))
    window.validate_meshes_button.click()
    assert pool.workers == []
    assert "Landmark CSV does not exist" in window.input_preflight_status_label.text()
    assert not window._data_inputs_ready()
    window.close()


def test_mesh_size_group_warning_allows_setup_progress(tmp_path: Path, monkeypatch) -> None:
    application, window, paths, signature = _ready_window(tmp_path, monkeypatch)
    metadata = tuple(
        _metadata(path, diagonal=(1.0 if index < 3 else 1_000.0))
        for index, path in enumerate(paths)
    )
    window._input_preflight = assess_mesh_input_metadata(metadata)
    window._input_preflight_signature = signature
    window._sync_ready_state()

    assert window._data_inputs_ready() is True
    assert window.continue_parameter_button.isEnabled() is True
    assert "advisory workload or size-policy findings" in window.data_status_label.text()

    window.close()
    application.processEvents()


def test_large_mesh_warning_allows_reviewed_progress(tmp_path: Path, monkeypatch) -> None:
    application, window, paths, signature = _ready_window(tmp_path, monkeypatch)
    faces_per_mesh = (HEAVY_COHORT_FACE_COUNT + len(paths) - 1) // len(paths)
    metadata = tuple(
        _metadata(
            path,
            diagonal=1.0,
            triangles=faces_per_mesh,
        )
        for path in paths
    )
    window._input_preflight = assess_mesh_input_metadata(metadata)
    window._input_preflight_signature = signature
    window._sync_ready_state()

    assert window._data_inputs_ready() is True
    assert window.continue_parameter_button.isEnabled() is True
    assert "advisory workload or size-policy findings" in window.data_status_label.text()

    window.close()
    application.processEvents()


def test_alignment_scale_policy_is_part_of_preflight_signature(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application, window, _paths, initial_signature = _ready_window(tmp_path, monkeypatch)

    window.procrustes_scaling_combo.blockSignals(True)
    window.procrustes_scaling_combo.setCurrentIndex(
        window.procrustes_scaling_combo.findData("preserve_size")
    )
    window.procrustes_scaling_combo.blockSignals(False)
    _paths, _landmarks, changed_signature = window._input_preflight_request()

    assert changed_signature != initial_signature

    window.close()
    application.processEvents()


def test_mesh_folder_selection_waits_for_explicit_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    class ImmediateThreadPool:
        @staticmethod
        def start(worker) -> None:
            worker.run()

    application = QApplication.instance() or QApplication(["automatic-preflight-test"])
    window = DiffeoForgeWindow()
    window._thread_pool = ImmediateThreadPool()
    directory = ROOT / "examples" / "synthetic" / "meshes"
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(directory),
    )

    window._choose_mesh_directory()

    assert window._input_preflight is None
    assert window._input_preflight_worker is None
    assert window.validate_meshes_button.isEnabled()
    window.validate_meshes_button.click()

    assert window._input_preflight is not None
    assert window._input_preflight.ready
    assert window._input_preflight_worker is None
    assert "No exceptional combined workload" in window.input_preflight_status_label.text()
    assert window.project_edit.text() == str(directory.parent / "diffeoforge-project")

    window.close()
    application.processEvents()


def test_mesh_folder_selection_blocks_nonmanifold_source_before_parameter_step(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    class ImmediateThreadPool:
        @staticmethod
        def start(worker) -> None:
            worker.run()

    vertices = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, -1.0, 0.0),
    )
    valid_faces = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3))
    nonmanifold_faces = ((0, 1, 2), (1, 0, 3), (0, 1, 4))
    mesh_directory = tmp_path / "meshes"
    mesh_directory.mkdir()
    write_vtk_polydata(mesh_directory / "template.vtk", vertices[:4], valid_faces)
    write_vtk_polydata(mesh_directory / "subject-valid.vtk", vertices[:4], valid_faces)
    write_vtk_polydata(mesh_directory / "aberrans_s.vtk", vertices, nonmanifold_faces)

    warnings: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(mesh_directory),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    application = QApplication.instance() or QApplication(["topology-preflight-test"])
    window = DiffeoForgeWindow()
    window._thread_pool = ImmediateThreadPool()
    window.units_combo.setCurrentIndex(window.units_combo.findData("millimeter"))

    window._choose_mesh_directory()
    window.validate_meshes_button.click()

    assert window._input_preflight is not None
    assert not window._input_preflight.ready
    assert "non-manifold edges" in window.input_preflight_status_label.text()
    assert "aberrans_s.vtk" in window.input_preflight_status_label.text()
    assert warnings and "aberrans_s.vtk" in warnings[0]
    assert window.continue_parameter_button.isEnabled() is False
    assert "blocking mesh-quality" in window.data_status_label.text()

    window.close()
    application.processEvents()

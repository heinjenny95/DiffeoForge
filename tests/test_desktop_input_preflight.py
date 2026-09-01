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

    window.procrustes_scale_check.blockSignals(True)
    window.procrustes_scale_check.setChecked(False)
    window.procrustes_scale_check.blockSignals(False)
    _paths, _landmarks, changed_signature = window._input_preflight_request()

    assert changed_signature != initial_signature

    window.close()
    application.processEvents()


def test_mesh_folder_selection_runs_read_only_preflight_automatically(
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

    assert window._input_preflight is not None
    assert not window._input_preflight.ready
    assert "non-manifold edges" in window.input_preflight_status_label.text()
    assert "aberrans_s.vtk" in window.input_preflight_status_label.text()
    assert warnings and "aberrans_s.vtk" in warnings[0]
    assert window.continue_parameter_button.isEnabled() is False
    assert "blocking mesh-quality" in window.data_status_label.text()

    window.close()
    application.processEvents()

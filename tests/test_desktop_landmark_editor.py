from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
MESHES = ROOT / "examples" / "synthetic" / "meshes"


def _triangle_centroids(path: Path) -> tuple[tuple[float, float, float], ...]:
    from diffeoforge.desktop.mesh_preview import load_mesh_preview

    model = load_mesh_preview(path)
    vertices = np.asarray(model.vertices, dtype=np.float64)
    return tuple(
        tuple(float(value) for value in np.mean(vertices[list(triangle)], axis=0))
        for triangle in model.triangles[:3]
    )


def test_landmark_editor_places_complete_surface_cohort_and_writes_csv(
    monkeypatch, tmp_path: Path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from diffeoforge.analysis.landmarks import read_landmark_csv
    from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog

    application = QApplication.instance() or QApplication(["landmark-editor-test"])
    paths = (MESHES / "template.vtk", MESHES / "subject-01.vtk")
    output = tmp_path / "landmarks.csv"
    dialog = LandmarkEditorDialog(paths, output)
    expected = np.asarray(
        [_triangle_centroids(paths[0]), _triangle_centroids(paths[1])],
        dtype=np.float64,
    )

    for point in expected.reshape((-1, 3)):
        dialog._place_surface_point(tuple(point))
    save = dialog.buttons.button(QDialogButtonBox.StandardButton.Save)
    assert save.isEnabled() is True
    dialog._save_and_accept()

    labels, values = read_landmark_csv(output, tuple(path.name for path in paths))
    assert labels == ("LM1", "LM2", "LM3")
    assert values == pytest.approx(expected)
    dialog.close()
    application.processEvents()


def test_surface_picker_interpolates_frontmost_triangle() -> None:
    pytest.importorskip("PySide6")
    from diffeoforge.desktop.landmark_3d_widget import pick_surface_point, project_surface

    vertices = np.asarray(
        [
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (0.0, 1.0, 0.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (0.0, 1.0, 1.0),
        ],
        dtype=np.float64,
    )
    surface = project_surface(
        vertices,
        np.asarray(((0, 1, 2), (3, 4, 5)), dtype=np.int64),
        center=np.asarray((0.0, 0.0, 0.0), dtype=np.float64),
        scale=2.0,
        yaw=0.0,
        pitch=0.0,
        zoom=1.0,
        pan=(0.0, 0.0),
        width=400,
        height=400,
    )

    assert pick_surface_point(surface, (200.0, 200.0)) == pytest.approx((0.0, 0.0, 1.0))
    assert pick_surface_point(surface, (5.0, 5.0)) is None


def test_3d_canvas_click_emits_an_arbitrary_surface_point(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
    from diffeoforge.desktop.mesh_preview import MeshPreviewModel

    application = QApplication.instance() or QApplication(["landmark-canvas-test"])
    canvas = InteractiveMeshCanvas3D()
    canvas.resize(400, 400)
    canvas.set_model(
        MeshPreviewModel(
            path=tmp_path / "surface.vtk",
            sha256="0" * 64,
            vertices=((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 1.0, 0.0)),
            triangles=((0, 1, 2),),
            edges=((0, 1), (1, 2), (0, 2)),
            bounds=(-1.0, 1.0, -1.0, 1.0, 0.0, 0.0),
        )
    )
    canvas.set_view_preset("front")
    observed: list[tuple[float, float, float]] = []
    canvas.surfacePointPicked.connect(observed.append)
    canvas.show()
    application.processEvents()

    center = QPoint(canvas.width() // 2, canvas.height() // 2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center)

    assert observed[0] == pytest.approx((0.0, 0.0, 0.0))
    assert observed[0] not in canvas._model.vertices
    canvas.close()
    application.processEvents()


def test_3d_canvas_release_requests_full_surface_repaint_after_rotation(
    monkeypatch,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
    from diffeoforge.desktop.mesh_preview import load_mesh_preview

    class UpdateTrackingCanvas(InteractiveMeshCanvas3D):
        def __init__(self) -> None:
            self.update_requests = 0
            super().__init__()

        def update(self, *args) -> None:
            self.update_requests += 1
            super().update(*args)

    application = QApplication.instance() or QApplication(
        ["landmark-canvas-release-test"]
    )
    canvas = UpdateTrackingCanvas()
    canvas.resize(400, 400)
    source = MESHES / "template.vtk"
    canvas.set_model(load_mesh_preview(source))
    canvas.set_markers({"LM1": _triangle_centroids(source)[0]})
    canvas.show()
    application.processEvents()

    QTest.mousePress(
        canvas,
        Qt.MouseButton.LeftButton,
        pos=QPoint(160, 180),
    )
    QTest.mouseMove(canvas, QPoint(230, 180))
    assert canvas._interacting is True
    before_release = canvas.update_requests

    QTest.mouseRelease(
        canvas,
        Qt.MouseButton.LeftButton,
        pos=QPoint(230, 180),
    )

    assert canvas._interacting is False
    assert canvas.update_requests == before_release + 1
    canvas.close()
    application.processEvents()


def test_landmark_editor_undo_restores_replaced_surface_point(
    monkeypatch, tmp_path: Path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog

    application = QApplication.instance() or QApplication(["landmark-editor-undo-test"])
    paths = (MESHES / "template.vtk", MESHES / "subject-01.vtk")
    dialog = LandmarkEditorDialog(paths, tmp_path / "landmarks.csv")
    first = (0.1, 0.2, 0.3)
    replacement = (0.4, 0.5, 0.6)
    dialog._place_surface_point(first)
    dialog.label_combo.setCurrentIndex(0)
    dialog._place_surface_point(replacement)

    dialog._undo_last_placement()

    assert dialog.placements[paths[0].name]["LM1"] == first
    assert dialog.mesh_combo.currentIndex() == 0
    assert dialog.label_combo.currentText() == "LM1"
    dialog.close()
    application.processEvents()


def test_landmark_editor_uses_requested_count_and_optional_mesh_advance(
    monkeypatch, tmp_path: Path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog

    application = QApplication.instance() or QApplication(
        ["landmark-editor-count-test"]
    )
    paths = (MESHES / "template.vtk", MESHES / "subject-01.vtk")
    automatic = LandmarkEditorDialog(
        paths,
        tmp_path / "automatic.csv",
        initial_landmark_count=5,
        auto_advance_mesh=True,
    )

    assert automatic.labels == ["LM1", "LM2", "LM3", "LM4", "LM5"]
    assert automatic.auto_advance_mesh_check.isChecked() is True
    automatic.label_combo.setCurrentIndex(4)
    automatic._place_surface_point((4.0, 0.0, 0.0))
    assert automatic.mesh_combo.currentIndex() == 0
    automatic._clear_current()
    automatic.label_combo.setCurrentIndex(0)
    for index in range(5):
        automatic._place_surface_point((float(index), 0.0, 0.0))
    assert automatic.mesh_combo.currentIndex() == 1
    assert automatic.label_combo.currentIndex() == 0
    automatic.close()

    manual = LandmarkEditorDialog(
        paths,
        tmp_path / "manual.csv",
        initial_landmark_count=5,
        auto_advance_mesh=False,
    )
    for index in range(5):
        manual._place_surface_point((float(index), 0.0, 0.0))
    assert manual.mesh_combo.currentIndex() == 0
    assert manual.label_combo.currentIndex() == 4
    manual.close()
    application.processEvents()


def test_landmark_editor_autosaves_and_hash_validates_resumable_draft(
    monkeypatch, tmp_path: Path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog

    application = QApplication.instance() or QApplication(["landmark-editor-draft-test"])
    paths = (MESHES / "template.vtk", MESHES / "subject-01.vtk")
    output = tmp_path / "landmarks.csv"
    first = LandmarkEditorDialog(
        paths,
        output,
        initial_landmark_count=5,
        auto_advance_mesh=False,
    )
    point = _triangle_centroids(paths[0])[0]
    first._place_surface_point(point)
    assert first.draft_path.is_file()
    first.close()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    resumed = LandmarkEditorDialog(paths, output)

    assert resumed.labels == ["LM1", "LM2", "LM3", "LM4", "LM5"]
    assert resumed.auto_advance_mesh_check.isChecked() is False
    assert resumed.placements[paths[0].name]["LM1"] == pytest.approx(point)
    assert "resumed" in resumed.draft_status_label.text().lower()
    resumed.close()
    application.processEvents()


def test_landmark_editor_module_does_not_change_qt_platform_environment() -> None:
    pytest.importorskip("PySide6")
    before = os.environ.get("QT_QPA_PLATFORM")
    __import__("diffeoforge.desktop.landmark_editor")
    assert os.environ.get("QT_QPA_PLATFORM") == before

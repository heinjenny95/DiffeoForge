from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
MESHES = ROOT / "examples" / "synthetic" / "meshes"


def test_landmark_editor_places_complete_vertex_cohort_and_writes_csv(
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

    for vertex in (0, 40, 80, 0, 40, 80):
        dialog._place_vertex(vertex)
    save = dialog.buttons.button(QDialogButtonBox.StandardButton.Save)
    assert save.isEnabled() is True
    dialog._save_and_accept()

    labels, values = read_landmark_csv(output, tuple(path.name for path in paths))
    assert labels == ("LM1", "LM2", "LM3")
    assert values.shape == (2, 3, 3)
    dialog.close()
    application.processEvents()


def test_landmark_editor_module_does_not_change_qt_platform_environment() -> None:
    pytest.importorskip("PySide6")
    before = os.environ.get("QT_QPA_PLATFORM")
    __import__("diffeoforge.desktop.landmark_editor")
    assert os.environ.get("QT_QPA_PLATFORM") == before

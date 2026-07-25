from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_feature_scale_ruler_records_resets_and_clears(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.feature_scale_dialog import FeatureScaleRulerDialog
    from diffeoforge.desktop.mesh_preview import load_mesh_preview

    application = QApplication.instance() or QApplication(
        ["diffeoforge-feature-ruler-test"]
    )
    model = load_mesh_preview(ROOT / "examples" / "synthetic" / "meshes" / "template.vtk")
    dialog = FeatureScaleRulerDialog(
        model,
        coordinate_unit="millimeter",
    )

    assert dialog.measured_distance is None
    assert dialog.use_button.isEnabled() is False
    dialog.record_point((0.0, 0.0, 0.0))
    dialog.record_point((3.0, 4.0, 0.0))
    assert dialog.measured_distance == pytest.approx(5.0)
    assert dialog.use_button.isEnabled() is True
    assert "5 millimeter" in dialog.status_label.text()

    dialog.record_point((1.0, 1.0, 1.0))
    assert dialog.measured_distance is None
    assert dialog.use_button.isEnabled() is False
    assert "second endpoint" in dialog.status_label.text()

    dialog.clear_measurement()
    assert dialog.measured_distance is None
    assert dialog.use_button.isEnabled() is False
    assert dialog.status_label.text() == "Click the first endpoint."
    dialog.close()
    application.processEvents()


def test_feature_scale_ruler_rejects_zero_length_measurement(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.feature_scale_dialog import FeatureScaleRulerDialog
    from diffeoforge.desktop.mesh_preview import load_mesh_preview

    application = QApplication.instance() or QApplication(
        ["diffeoforge-feature-ruler-zero-test"]
    )
    model = load_mesh_preview(ROOT / "examples" / "synthetic" / "meshes" / "template.vtk")
    dialog = FeatureScaleRulerDialog(model, coordinate_unit="unitless")

    dialog.record_point((1.0, 2.0, 3.0))
    dialog.record_point((1.0, 2.0, 3.0))

    assert dialog.measured_distance is None
    assert dialog.use_button.isEnabled() is False
    assert "coincide" in dialog.status_label.text()
    dialog.close()
    application.processEvents()

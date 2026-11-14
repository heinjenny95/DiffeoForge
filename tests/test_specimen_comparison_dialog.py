import numpy as np
from test_desktop_registration_release import _wait_for_qt
from test_desktop_registration_release import visual_review as _visual_review

visual_review = _visual_review


def test_verified_specimen_renders_both_surfaces_with_one_camera(
    visual_review, monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton

    from diffeoforge.desktop import result_mesh_loader
    from diffeoforge.desktop.display_proxy import DEFAULT_DISPLAY_FACES
    from diffeoforge.desktop.specimen_comparison_dialog import SpecimenComparisonDialog
    from diffeoforge.mesh import sha256_file

    app = QApplication.instance() or QApplication([])
    review = visual_review
    before = {path: sha256_file(path) for path in review.run_directory.iterdir()}
    requested_budgets = []
    load = result_mesh_loader.load_mesh_preview

    def observe_load(path, **options):
        requested_budgets.append(options.get("triangle_budget"))
        return load(path, **options)

    monkeypatch.setattr(result_mesh_loader, "load_mesh_preview", observe_load)
    # This includes a roll and therefore cannot be represented by yaw/pitch alone.
    dialog = SpecimenComparisonDialog(
        review, "subject-2", pca_view=("Saved", (0, 0, 1), (1, 0, 0))
    )
    dialog.show()
    try:
        left, right = dialog.original_canvas, dialog.reconstruction_canvas
        _wait_for_qt(lambda: left._presented_key is not None and right._presented_key is not None)
        assert requested_budgets == [DEFAULT_DISPLAY_FACES, DEFAULT_DISPLAY_FACES]
        assert left.original_model.path.name == "original-2.vtk"
        assert right.reconstruction_model.path.name == "reconstruction-2.vtk"
        assert left._show_original and not left._show_reconstruction
        assert right._show_reconstruction and not right._show_original
        assert np.array_equal(left._center, right._center)
        assert left._scale == right._scale
        assert dialog.preset.currentText() == "PCA view"
        expected_rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
        np.testing.assert_array_equal(left._view_rotation(), expected_rotation)
        np.testing.assert_array_equal(right._view_rotation(), expected_rotation)
        event = QWheelEvent(
            QPointF(100, 130), QPointF(100, 130), QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate, False,
        )
        app.sendEvent(right, event)
        assert left.camera_state()[:4] == right.camera_state()[:4]
        assert left.camera_state()[2] > 1
        QTest.mousePress(left, Qt.MouseButton.LeftButton, pos=QPoint(100, 130))
        QTest.mouseMove(left, QPoint(120, 145))
        QTest.mouseRelease(left, Qt.MouseButton.LeftButton, pos=QPoint(120, 145))
        assert left.camera_state()[:4] == right.camera_state()[:4]
        assert left.camera_state()[:2] != (0.0, 0.0)
        dialog.preset.setCurrentIndex(dialog.preset.findData("back"))
        assert left.camera_state()[:4] == right.camera_state()[:4]
        dialog.reset_button.click()
        np.testing.assert_array_equal(right._view_rotation(), expected_rotation)
        assert left.camera_state()[2] == right.camera_state()[2] == 1.0
        _wait_for_qt(lambda: all(canvas._presented_key == canvas._frame_key()
                                for canvas in (left, right)))
        assert {button.text() for button in dialog.findChildren(QPushButton)} == {
            "Reset view", "Close"
        }
    finally:
        dialog.close()
        app.processEvents()
    assert {path: sha256_file(path) for path in review.run_directory.iterdir()} == before


def test_specimen_comparison_never_renders_a_changed_result(visual_review, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.specimen_comparison_dialog import SpecimenComparisonDialog

    app = QApplication.instance() or QApplication([])
    item = visual_review.registration_qc_item("subject-1")
    artifact = visual_review.artifact(item.reconstruction_artifact_key)
    artifact.path.write_text("changed", encoding="utf-8")
    dialog = SpecimenComparisonDialog(visual_review, "subject-1")
    dialog.show()
    try:
        _wait_for_qt(lambda: "could not be loaded" in dialog.status.text())
        assert dialog.original_canvas.original_model is None
        assert dialog.reconstruction_canvas.reconstruction_model is None
        assert not dialog.reset_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()

import time

import numpy as np
from test_reference_calibration_dialog import _model


def wait(app, predicate):
    deadline = time.monotonic() + 12
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def setup_dialog(tmp_path, monkeypatch, *, best=True):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.fit_preference_dialog import FitPreferenceDialog
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

    app = QApplication.instance() or QApplication([])
    queued = []
    monkeypatch.setattr(
        PreviewMeshLoader, "request_operation", lambda self, key, op: queued.append((key, op))
    )
    dialog = FitPreferenceDialog(tmp_path)
    def record(name):
        return dict(study=name, candidate_id="fit-specimen")
    saved, previous, current = (
        record("specimen-01-01"),
        record("specimen-01-02"),
        record("specimen-01-03"),
    )
    descriptor = dict(
        root=str(tmp_path), current=current, choices=[previous, saved], best=saved if best else None
    )
    dialog._loaded("choices", descriptor)
    original, current_model, saved_model = [
        _model(tmp_path / name) for name in ["target.vtk", "current.vtk", "saved.vtk"]
    ]
    comparison = dict(
        current=current, reference=saved if best else previous, best=descriptor["best"]
    )
    dialog.show()
    dialog._loaded("surfaces", ([original, current_model, saved_model], comparison))
    return app, dialog, comparison, queued


def test_direct_comparison_has_shared_scale_camera_and_frame_gated_feedback(tmp_path, monkeypatch):
    app, dialog, comparison, _ = setup_dialog(tmp_path, monkeypatch)
    assert not dialog.feedback_buttons["better"].isEnabled()
    wait(app, lambda: dialog.feedback_buttons["better"].isEnabled())
    assert dialog.reference_combo.currentText().startswith("Best so far")
    assert np.array_equal(dialog.reference_canvas._center, dialog.current_canvas._center)
    assert dialog.reference_canvas._scale == dialog.current_canvas._scale
    dialog.current_canvas.set_view_preset("back")
    assert dialog.current_canvas.camera_state()[:4] == dialog.reference_canvas.camera_state()[:4]
    # Decisions are unavailable while either comparison is navigating.
    dialog.current_canvas._interacting = True
    dialog.current_canvas._emit_camera()
    dialog._update_actions()
    assert not dialog.feedback_buttons["better"].isEnabled()
    dialog.current_canvas._interacting = False
    dialog.current_canvas._emit_camera()
    dialog.current_canvas.update()
    wait(app, lambda: dialog.feedback_buttons["better"].isEnabled())
    dialog.feedback_buttons["worse"].click()
    assert dialog.decision == ("worse", "fit-specimen", comparison)
    assert dialog._closed
    app.processEvents()


def test_other_history_can_be_viewed_but_cannot_silently_replace_best(tmp_path, monkeypatch):
    app, dialog, comparison, queued = setup_dialog(tmp_path, monkeypatch)
    wait(app, lambda: dialog.feedback_buttons["better"].isEnabled())
    dialog.reference_combo.setCurrentIndex(1)
    assert not dialog.feedback_buttons["better"].isEnabled()
    assert dialog.current_canvas.original_model is None
    original = _model(tmp_path / "target.vtk")
    comparison = dict(comparison, reference=dialog.reference_combo.currentData())
    dialog._loaded(
        "surfaces",
        (
            [original, _model(tmp_path / "current.vtk"), _model(tmp_path / "previous.vtk")],
            comparison,
        ),
    )
    wait(
        app,
        lambda: dialog.current_canvas.comparison_ready and dialog.reference_canvas.comparison_ready,
    )
    assert not any(b.isEnabled() for b in dialog.feedback_buttons.values())
    assert "Best so far" in dialog.status.text()
    assert queued[-1][0] == "surfaces"
    dialog.reject()
    assert dialog.decision is None
    # A late worker delivery cannot revive a closed dialog or apply a decision.
    dialog._loaded("surfaces", ([], {}))
    assert dialog._closed and dialog.decision is None
    app.processEvents()


def test_legacy_unranked_sequence_can_select_an_older_better_attempt(tmp_path, monkeypatch):
    app, dialog, comparison, _ = setup_dialog(tmp_path, monkeypatch, best=False)
    wait(app, lambda: dialog.feedback_buttons["worse"].isEnabled())
    assert dialog.reference_combo.currentText().startswith("Previous attempt")
    dialog.feedback_buttons["same"].click()
    assert dialog.decision[0] == "same"
    assert dialog.decision[2]["best"] is None
    app.processEvents()

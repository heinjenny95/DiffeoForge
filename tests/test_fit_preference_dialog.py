import time
from dataclasses import replace

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

    from diffeoforge.desktop.fit_preference_dialog import FitPreferencePanel
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

    app = QApplication.instance() or QApplication([])
    queued = []
    monkeypatch.setattr(
        PreviewMeshLoader, "request_operation", lambda self, key, op: queued.append((key, op))
    )
    dialog = FitPreferencePanel(tmp_path)
    dialog.resize(1120, 760)
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
    dialog.show_comparison.setChecked(True)  # This suite exercises the optional comparison.
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
    assert not dialog._closed  # Rating alone never closes inspection or starts a fit.
    dialog.close()
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
    dialog.close()
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
    dialog.close()
    app.processEvents()


def test_attempt_labels_and_late_reference_delivery_cannot_mirror_current(tmp_path, monkeypatch):
    app, dialog, comparison, _ = setup_dialog(tmp_path, monkeypatch)
    wait(app, lambda: dialog.feedback_buttons["better"].isEnabled())
    assert dialog.current_label.text() == "Current fit · specimen-01-03"
    assert "specimen-01-01" in dialog.reference_label.text()
    dialog.reference_combo.setCurrentIndex(1)
    # The old saved-fit delivery arrives after the user selects the previous attempt.
    dialog._loaded("surfaces", (
        [_model(tmp_path / name) for name in ("target.vtk", "current.vtk", "saved.vtk")],
        comparison,
    ))
    assert dialog.reference_canvas.reconstruction_model is None
    assert not dialog.selection_ready and not dialog._ready
    selected = dict(comparison, reference=dialog.reference_combo.currentData())
    models = [_model(tmp_path / name) for name in ("target.vtk", "current.vtk", "previous.vtk")]
    dialog._loaded("surfaces", (models, selected))
    wait(app, lambda: dialog.reference_canvas.comparison_ready)
    assert dialog.reference_canvas.reconstruction_model is models[2]
    assert dialog.current_canvas.reconstruction_model is models[1]
    assert "specimen-01-02" in dialog.reference_label.text()
    dialog.close()
    app.processEvents()


def test_distinct_attempts_cannot_display_the_current_file_on_both_sides(tmp_path, monkeypatch):
    app, dialog, comparison, _ = setup_dialog(tmp_path, monkeypatch)
    wait(app, lambda: dialog.feedback_buttons["better"].isEnabled())
    models = [_model(tmp_path / name) for name in ("target.vtk", "current.vtk", "current.vtk")]
    dialog._loaded("surfaces", (models, comparison))
    assert "different attempts and files" in dialog.status.text()
    assert dialog.reference_canvas.reconstruction_model is None
    assert not any(b.isEnabled() for b in dialog.feedback_buttons.values())
    dialog.close()
    app.processEvents()


def test_identical_exports_from_separate_attempts_are_explicit_and_still_reviewable(
    tmp_path, monkeypatch
):
    app, dialog, comparison, _ = setup_dialog(tmp_path, monkeypatch)
    wait(app, lambda: dialog.feedback_buttons["same"].isEnabled())
    assert "separate runs exported identical surfaces" in dialog.status.text()
    assert dialog.reference_canvas.reconstruction_model.path != (
        dialog.current_canvas.reconstruction_model.path
    )
    dialog.feedback_buttons["same"].click()
    assert dialog.decision == ("same", "fit-specimen", comparison)
    dialog.close()
    app.processEvents()


def test_rendered_previous_and_current_surfaces_retain_their_own_geometry(tmp_path, monkeypatch):
    app, dialog, comparison, _ = setup_dialog(tmp_path, monkeypatch, best=False)
    original = _model(tmp_path / "target.vtk")
    previous = replace(_model(tmp_path / "previous.vtk"), sha256="1" * 64)
    current = replace(
        _model(tmp_path / "current.vtk"), sha256="2" * 64,
        vertices=((-1., -1., 0.), (1., -1., 0.), (0., 1., 0.), (.9, .4, 1.8)),
    )
    dialog._loaded("surfaces", ([original, current, previous], comparison))
    wait(app, lambda: dialog.feedback_buttons["better"].isEnabled())
    left, right = dialog.reference_canvas, dialog.current_canvas
    assert left.reconstruction_model is previous and right.reconstruction_model is current
    assert np.array_equal(left._reconstruction_vertices, previous.vertices)
    assert np.array_equal(right._reconstruction_vertices, current.vertices)
    assert left._frames._image != right._frames._image
    dialog.feedback_buttons["worse"].click()
    assert dialog.decision[2]["reference"]["study"] == "specimen-01-02"
    dialog.close()
    app.processEvents()

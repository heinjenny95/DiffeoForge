"""A Better fit with warnings needs an explicit inspected source, never a fallback."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_guided_suitable_dialog import panel as _panel

panel = _panel


def _choice(tmp_path):
    latest = dict(directory=str(tmp_path / "latest"), candidate_id="guided-varifold",
                  method="varifold", target="specimen.vtk")
    earlier = dict(directory=str(tmp_path / "earlier"), candidate_id="guided-current",
                   method="current", target="specimen.vtk")
    pending = dict(identifier="guided-varifold", latest=latest, current=latest,
                   comparison=earlier, reasons=("new surface intersection flags",
                                               "original-source spatial resolution"),
                   choice_required=True)
    return dict(starting_fit_choice=pending, selected=None, choices=[
        dict(reference=latest, label="Test 5 · Varifold", trial_index=5,
             current=True, approved=False),
        dict(reference=earlier, label="Test 3 · Current", trial_index=3,
             current=False, approved=False),
    ])


@pytest.mark.parametrize("bounded_complete", [False, True])
def test_pending_choice_is_only_primary_and_explains_specific_checks(panel, bounded_complete):
    from PySide6.QtWidgets import QLabel, QPushButton

    data = _choice(panel.snapshot.study_directory)
    data.update(panel.guidance["feedback"][panel.candidate.candidate_id])
    data["selected"] = None
    panel.guidance["feedback"][panel.candidate.candidate_id] = data
    if bounded_complete:
        from test_adaptive_desktop_flow import bounded

        panel.guidance["bounded_adaptive"] = bounded(
            closed=True, recommendation=data["starting_fit_choice"]["comparison"])
    # Even a stale repair/density suggestion cannot outrank the unresolved source.
    panel.guidance["fit_direction"] = dict(mode="trial", identifier=panel.candidate.candidate_id,
        request=dict(goal="regional"), reason="Do not prepare this stale trial")
    panel.guidance["density_comparisons"] = {panel.candidate.candidate_id: dict(
        reference=data["starting_fit_choice"]["comparison"], initial_control_count=20,
        denser_control_count=30)}
    opened = []
    panel.window._open_guided_working_fit = lambda *a, **k: opened.append((a, k))
    panel.render()
    active = [b for b in panel.window.findChildren(QPushButton)
              if b.isVisible() and b.isEnabled() and b.objectName() == "primary"]
    assert active == [panel.window.next_step_button]
    assert active[0].text() == "Choose starting fit…"
    assert panel.window._guided_footer_action[1] == "fit_direction_choose_start"
    assert panel.window._guided_footer_goal is None
    assert "not selected" in panel.window.status.text()
    warnings = panel.window.findChildren(QLabel, "startingFitChoiceWarning")
    assert len(warnings) == 1
    assert all(reason in warnings[0].text()
               for reason in data["starting_fit_choice"]["reasons"])
    buttons = [b for b in panel.window.findChildren(QPushButton)
               if b.property("startingFitRole")]
    assert len(buttons) == 2
    assert buttons[0].text() == "Inspect latest fit · Varifold · Test 5…"
    assert buttons[1].text() == "Inspect earlier comparison · Current · Test 3…"
    assert {b.objectName() for b in buttons} == {"secondary"}
    assert not any(b.isDefault() for b in buttons)
    assert not panel.invoked and not opened
    assert any("Deleting a red mark does not protect" in label.text()
               for label in panel.window.findChildren(QLabel))
    buttons[0].click()
    pending = data["starting_fit_choice"]
    assert opened == [((pending["identifier"], pending["latest"]),
                       dict(restore_partial=True, expected_starting_choice=pending))]
    assert not panel.invoked


@pytest.mark.parametrize("role", ["latest", "comparison", "cancel"])
def test_chooser_only_opens_explicit_inspection_and_cancel_is_inert(tmp_path, monkeypatch, role):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget

    from diffeoforge.desktop import guided_feedback as ui

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    called = []
    window._open_guided_working_fit = lambda *a, **k: called.append((a, k))
    window._start_pilot = lambda *_a, **_k: pytest.fail("Source chooser dispatched a trial")
    data = _choice(tmp_path)
    original = deepcopy(data)

    def inspect(dialog):
        assert dialog.chosen_reference is None
        assert all(b.objectName() == "secondary" and not b.isDefault()
                   and not b.autoDefault() for b in dialog.choice_buttons)
        if role == "cancel":
            dialog.reject()
        else:
            next(b for b in dialog.choice_buttons
                 if b.property("startingFitRole") == role).click()
        return dialog.result()

    monkeypatch.setattr(ui.StartingFitChoiceDialog, "exec", inspect)
    ui.choose_starting_fit(window, data)
    if role == "cancel":
        assert called == []
    else:
        assert called == [(("guided-varifold", data["starting_fit_choice"][role]),
                           {"restore_partial": role == "latest",
                            "expected_starting_choice": data["starting_fit_choice"]})]
    assert data == original
    assert not list(tmp_path.iterdir())
    window.close()
    app.processEvents()


@pytest.mark.parametrize("save_marks", [False, True])
@pytest.mark.parametrize("overlap", [False, True])
def test_green_suggestions_are_visible_drafts_until_explicit_settled_save(
    tmp_path, monkeypatch, save_marks, overlap,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from test_full_review_geometry import model, wait

    from diffeoforge.desktop.guided_working_fit import viewer
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.desktop.reference_calibration_dialog import CalibrationQcPair

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PreviewMeshLoader, "request_paths", lambda *_a, **_k: None)
    source = tmp_path / "saved"
    source.mkdir()
    journal = source / "events.jsonl"
    journal.write_text("unchanged evidence\n")
    original, reconstruction = source / "original.vtk", source / "fit.vtk"
    reference = dict(directory=str(source), candidate_id="guided-varifold",
                     method="varifold", target=original.name)
    remaining = dict(version="surface-region-v2", source_sha256="0" * 64,
                     space="original_mesh_coordinates", center=[0, 0, 0], radius=.1,
                     purpose="problem", symptom="detail")
    draft = ([remaining] if overlap else
             [remaining, dict(remaining, center=[.5, 0, 0], purpose="fixed"),
              dict(remaining, center=[-.5, 0, 0], purpose="fixed")])
    context = dict(reference=reference, target=original.name, label="Varifold · Test 5",
                   problem_regions={original.name: draft}, cleared_region_subjects=[],
                   partial_draft=dict(remaining=1, suggested=0 if overlap else 2, marks=draft,
                                      skipped_overlap=2 if overlap else 0),
                   expected_starting_choice=dict(identifier="guided-varifold", latest=reference,
                                                 feedback_sequence=5, choice_required=True))
    before = deepcopy(context)
    candidate = SimpleNamespace(candidate_id="guided-varifold", run_directory=source,
                                status="completed", metrics=dict(invalid_face_count=0))
    pair = CalibrationQcPair("pair", "saved", original, reconstruction, True,
                             "0" * 64, "0" * 64)
    dialog = viewer(None, tmp_path, SimpleNamespace(study_directory=source), candidate,
                    (pair,), {}, context)
    dialog.show()
    try:
        save = next(b for b in dialog.findChildren(QPushButton)
                    if b.text().startswith("Use this fit and save"))
        assert not save.isEnabled()
        if overlap:
            assert "suggested Retain" not in dialog._comparison_intro.text()
            assert "2 removed area(s) overlap" in dialog._comparison_intro.text()
            assert "were not converted to green" in dialog._comparison_intro.text()
            assert not any(mark["purpose"] == "fixed" for mark in
                           dialog.problem_regions[original.name])
        else:
            assert "2 suggested Retain" in dialog._comparison_intro.text()
            assert "overlap" not in dialog._comparison_intro.text()
        assert "suggestions only" in dialog._comparison_intro.text()
        assert dialog.findChild(QLabel, "redGreenRetentionHint")
        assert dialog.working_decision is None and not dialog.review_recorded
        assert dialog.problem_regions[original.name] == draft
        if save_marks:
            dialog._pair_loaded(0, (model(original, True), model(reconstruction, True)))
            wait(app, lambda: dialog.canvas.comparison_ready and save.isEnabled())
            save.click()
            assert dialog.working_decision["reference"] == reference
            assert dialog.working_decision["problem_regions"][original.name] == draft
            expected = context["expected_starting_choice"]
            assert dialog.working_decision["expected_starting_choice"] == expected
            assert dialog.working_decision["expected_starting_choice"] is not expected
        else:
            dialog.reject()
            assert dialog.working_decision is None
        assert context == before and not dialog.review_recorded
        assert journal.read_text() == "unchanged evidence\n"
        assert list(source.iterdir()) == [journal]
    finally:
        dialog.close()
        app.processEvents()


def test_controller_footer_opens_source_choice_without_dispatching_scientific_work(
    panel, monkeypatch,
):
    from diffeoforge.desktop import guided_feedback as ui
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    data = _choice(panel.snapshot.study_directory)
    data.update(panel.guidance["feedback"][panel.candidate.candidate_id])
    data["selected"] = None
    panel.guidance["feedback"][panel.candidate.candidate_id] = data
    opened = []
    panel.window._open_guided_working_fit = lambda *_a, **_k: pytest.fail(
        "The footer chose a saved fit without a user choice")
    panel.window._start_pilot = lambda *_a, **_k: pytest.fail(
        "The pending-choice footer dispatched a scientific/preparation action")
    monkeypatch.setattr(ui, "choose_starting_fit", lambda *a: opened.append(a))
    panel.render()
    panel.window.next_step_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._perform_final_next_step(panel.window))
    panel.window.next_step_button.click()
    assert opened == [(panel.window, dict(starting_fit_choice=data["starting_fit_choice"],
                                         choices=data["choices"]))]
    assert not panel.invoked
    panel.window._worker = object()
    panel.window.next_step_button.click()
    assert len(opened) == 1  # Existing active-worker guard still applies.


def test_working_view_preparation_rechecks_captured_choice_before_loading_geometry(
    tmp_path, monkeypatch,
):
    from diffeoforge import guided_feedback
    from diffeoforge.desktop import reference_calibration_dialog as controller

    data = _choice(tmp_path)
    pending = data["starting_fit_choice"]
    requested = []
    parent = SimpleNamespace(candidates=[SimpleNamespace(candidate_id="guided-varifold")])
    window = SimpleNamespace(_view_loading=False, _view_closed=False, _review_saving=False,
        _worker=None, study_directory=tmp_path,
        _viewer_preparation=SimpleNamespace(request_operation=lambda *a: requested.append(a)))
    monkeypatch.setattr(guided_feedback, "verify_reference", lambda _: parent)
    monkeypatch.setattr(controller, "load_reference_calibration_study", lambda _: object())
    monkeypatch.setattr(guided_feedback, "starting_fit_choice",
                        lambda *_: dict(pending, feedback_sequence="newer review"))
    monkeypatch.setattr(controller, "collect_calibration_qc_pairs",
                        lambda *_: pytest.fail("Stale choice loaded geometry"))
    controller.ReferenceCalibrationDialog._open_guided_saved_fit(
        window, pending["latest"], working_for="guided-varifold", restore_partial=True,
        expected_starting_choice=pending)
    assert len(requested) == 1
    with pytest.raises(ValueError, match="starting-fit decision changed"):
        requested[0][1]()

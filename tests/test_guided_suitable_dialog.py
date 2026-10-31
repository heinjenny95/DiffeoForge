"""Actual Qt transitions; synthetic evidence only, no fit or private owner data."""

from collections import defaultdict
from types import SimpleNamespace

import pytest


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QLabel,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from diffeoforge import reference_calibration_study as study
    from diffeoforge.desktop import guided_diagnosis, guided_feedback
    from diffeoforge.desktop import guided_pilot as ui
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    app = QApplication.instance() or QApplication([])
    window = QDialog()
    window.setLayout(QVBoxLayout())
    window.content = QWidget()
    window.content_layout = QVBoxLayout(window.content)
    window.layout().addWidget(window.content)
    window._worker = None
    window._restoring_search = False
    window.progress = QProgressBar()
    window.status = QLabel()
    window.layout().addWidget(window.progress)
    window.layout().addWidget(window.status)
    for name in (
        "find_fit_button",
        "saved_searches_button",
        "adaptive_fit_search",
        "advanced_mode",
        "afk_mode",
        "outward_mode",
        "collect_evidence_button",
        "keep_previous_button",
        "selection_combo",
        "advance_button",
        "compare_options_button",
        "use_provisional_button",
        "review_next_button",
        "denser_model_button",
        "start_button",
        "cancel_button",
        "next_step_button",
    ):
        setattr(window, name, QPushButton(name, window))
    window.close_button = QPushButton("Close", window)
    window.study_directory = tmp_path
    window._view_loading = False
    window._review_saving = False
    window.layout().addWidget(window.review_next_button)
    window.layout().addWidget(window.next_step_button)
    _set_action_emphasis(window.close_button, False)
    window.close_button.clicked.connect(window.close)
    window.layout().addWidget(window.close_button)
    invoked, inspected = [], []
    window._start_pilot = lambda *a, **kw: invoked.append((a, kw))
    window._open_candidate = inspected.append
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *_a, **_kw: pytest.fail("UI rendering dispatched a fit"),
    )
    monkeypatch.setattr(guided_feedback, "render_feedback", lambda *_a: None)
    monkeypatch.setattr(guided_feedback, "render_starting_fits", lambda *_a: None)
    monkeypatch.setattr(guided_diagnosis, "render", lambda *_a: None)
    info = dict(
        phase="refine",
        goal="optimize",
        target="specimen.vtk",
        screen_trials_spent=5,
        pilot_order=["specimen.vtk"],
        approved=[],
    )
    monkeypatch.setattr(ui, "record", lambda _s: info)
    quality = dict(
        transition_preserved=True,
        outside_preserved=True,
        shape_preserved=True,
        no_new_intersection_flags=False,
        temporal_grid_stable=True,
        spatial_resolution_sufficient=False,
        numerical_selection_suitable=False,
    )
    candidate = SimpleNamespace(
        candidate_id="guided-varifold",
        label="Varifold",
        status="completed",
        metrics=dict(
            completed=True,
            converged=False,
            invalid_face_count=0,
            optimizer_stop_signal="maximum_iterations",
            maximum_iterations=3,
            final_iteration=4,
            runtime_seconds=1,
            attachment_comparison=dict(subjects={"specimen.vtk": dict(regional_quality=quality)}),
        ),
    )
    snapshot = SimpleNamespace(
        study_directory=tmp_path,
        candidates=(candidate,),
        visual_reviews={candidate.candidate_id: False},
        attachment_comparison=dict(
            methods={candidate.candidate_id: "varifold"},
            regional_objective={"version": "bound-local-objective"},
        ),
        plan=SimpleNamespace(pilot_subject_count=1),
    )
    proposal = dict(
        available=True,
        reason="Same objective, new finite iterations.",
        title="Optimize longer with the same regional settings",
        initialization="learned",
        numerical_extension=True,
        optimization_iterations=6,
        goal="optimize",
        remaining_checks=0,
    )
    context = dict(
        total=1,
        checked=0,
        preferred="varifold",
        allowed={candidate.candidate_id: True},
        feedback={
            candidate.candidate_id: dict(
                current_inspected=True,
                selected=True,
                feedback=dict(outcome="better", symptom="detail"),
                problem_regions={},
                needs_direction=False,
            )
        },
        proposals={candidate.candidate_id: defaultdict(lambda: proposal)},
    )
    prepared = SimpleNamespace(snapshot=snapshot, guidance=context)

    def render():
        while window.content_layout.count():
            item = window.content_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        app.processEvents()
        ui.render(window, prepared)
        window.show()
        app.processEvents()

    yield SimpleNamespace(
        app=app,
        window=window,
        snapshot=snapshot,
        guidance=context,
        candidate=candidate,
        invoked=invoked,
        inspected=inspected,
        render=render,
    )
    window.close()
    app.processEvents()


def test_numerical_failure_explains_stop_and_disables_same_retry(panel, monkeypatch):
    import os

    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop import guided_failed_parent

    monkeypatch.setattr(guided_failed_parent, "render", lambda *_: None)
    panel.candidate.status = "failed"
    panel.candidate.metrics = None
    panel.candidate.error = "Deformetrica finished with return code 1 and status 'failed'"
    panel.snapshot.visual_reviews.clear()
    panel.guidance["guard_failures"] = {panel.candidate.candidate_id: dict(
        reason="inconsistent_FG_for_identical_parameters",
        message="Numerical consistency check stopped this trial: identical parameters "
        "produced different objective or gradient values. Inspect the retained earlier fit.",
    )}
    panel.window.layout().addWidget(panel.window.start_button)
    panel.render()
    assert not panel.window.start_button.isEnabled()
    assert "cannot be rerun" in panel.window.start_button.text()
    assert "cannot be rerun" in panel.window.start_button.toolTip()
    assert "retry" not in panel.window.status.text()
    assert any("identical parameters" in label.text() and label.isVisible()
               for label in panel.window.content.findChildren(QLabel))
    assert not any("Optimize longer" in label.text() and label.isVisible()
                   for label in panel.window.content.findChildren(QLabel))
    panel.window.start_button.click()
    assert not panel.invoked
    capture = os.environ.get("DF_GUARD_UI_CAPTURE")
    if capture:
        from PySide6.QtGui import QFont, QFontDatabase

        from diffeoforge.desktop.appearance import Appearance, themed_style
        from diffeoforge.desktop.widgets import _STYLE

        panel.window.setWindowTitle("Synthetic failure-view test — no owner fit started")
        font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        assert font_id >= 0
        panel.app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
        panel.window.setStyleSheet(themed_style(_STYLE, Appearance()))
        panel.window.resize(1050, 730)
        panel.app.processEvents()
        assert panel.window.grab().save(capture)


def test_suitable_capped_warning_fit_stops_default_refinement_but_keeps_inspection(panel):
    from PySide6.QtWidgets import QLabel, QPushButton

    from diffeoforge.desktop.info_disclosure import InfoDisclosure

    panel.render()
    buttons = panel.window.content.findChildren(QPushButton)
    assert any("prepare 1 trial" in b.text() and b.isVisible() and b.isEnabled() for b in buttons)
    assert any(
        "has not passed" in label.text() and label.isVisible()
        for label in panel.window.content.findChildren(QLabel)
    )
    assert not panel.invoked

    # The persisted human decision changes only the presentation, not numerical QC.
    panel.snapshot.visual_reviews[panel.candidate.candidate_id] = True
    panel.render()
    labels = panel.window.content.findChildren(QLabel)
    assert any(label.text() == "Suitable fit saved" and label.isVisible() for label in labels)
    assert any(
        "Your suitable-fit decision is saved. Surface checks still report" in label.text()
        and label.isVisible()
        for label in labels
    )
    assert not any(
        ("has not passed" in label.text() or "This attempt fails:" in label.text())
        and label.isVisible()
        for label in labels
    )
    buttons = panel.window.content.findChildren(QPushButton)
    assert not any("prepare 1 trial" in b.text() and b.isVisible() for b in buttons)
    assert not any("check remaining forms" in b.text() and b.isVisible() for b in buttons)
    inspect = next(b for b in buttons if b.text() == "Inspect Varifold fit" and b.isVisible())
    assert inspect.isEnabled() and inspect.objectName() == "secondary"
    inspect.click()
    assert panel.inspected == [panel.candidate] and not panel.invoked
    optional = next(
        d
        for d in panel.window.content.findChildren(InfoDisclosure)
        if d.title == "Optional further refinement"
    )
    assert not optional.toggle_button.isChecked() and optional.panel.isHidden()
    assert optional.toggle_button.objectName() == "secondary"
    optional.toggle_button.click()
    panel.app.processEvents()
    assert optional.panel.isVisible()
    assert not panel.invoked
    optional.toggle_button.click()
    panel.app.processEvents()
    assert optional.panel.isHidden() and not panel.invoked
    assert panel.candidate.metrics["converged"] is False
    assert (
        panel.candidate.metrics["attachment_comparison"]["subjects"]["specimen.vtk"][
            "regional_quality"
        ]["numerical_selection_suitable"]
        is False
    )
    assert panel.window.close_button.isEnabled() and panel.window.close_button.isVisible()
    panel.window.close_button.click()
    assert not panel.window.isVisible() and not panel.invoked


def test_needs_improvement_keeps_visible_guided_recovery(panel):
    from PySide6.QtWidgets import QLabel, QPushButton

    panel.render()
    assert any(
        "has not passed" in label.text() and label.isVisible()
        for label in panel.window.content.findChildren(QLabel)
    )
    assert (
        sum(
            "prepare 1 trial on 1 specimen" in b.text() and b.isVisible()
            for b in panel.window.content.findChildren(QPushButton)
        )
        == 1
    )
    assert not panel.invoked


@pytest.mark.parametrize("invalid_faces", [0, 1])
def test_actual_compact_viewer_keeps_visual_and_numerical_gates_distinct(
    panel, tmp_path, monkeypatch, invalid_faces
):
    from test_fit_preference_dialog import wait
    from test_reference_calibration_dialog import _model

    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.desktop.reference_calibration_dialog import (
        CalibrationCandidateViewerDialog,
        CalibrationQcPair,
    )

    candidate = panel.candidate
    candidate.run_directory = tmp_path
    candidate.metrics["invalid_face_count"] = invalid_faces
    monkeypatch.setattr(PreviewMeshLoader, "request_paths", lambda *_a, **_kw: None)
    original, fitted = tmp_path / "specimen.vtk", tmp_path / "fitted.vtk"
    pair = CalibrationQcPair(
        pair_id="current",
        label="specimen.vtk",
        original_path=original,
        reconstruction_path=fitted,
        required=True,
        original_sha256="0" * 64,
        reconstruction_sha256="0" * 64,
    )
    viewer = CalibrationCandidateViewerDialog(
        tmp_path, candidate, pairs=(pair,), compact_review=True
    )
    viewer.show()
    assert not viewer.complete_button.isEnabled()
    viewer._pair_loaded(0, (_model(original), _model(fitted)))
    wait(panel.app, lambda: viewer.canvas.comparison_ready)
    viewer._update_review_progress()
    assert viewer.complete_button.text() == "Suitable fit"
    assert viewer.complete_button.isEnabled() is (invalid_faces == 0)
    if not invalid_faces:
        viewer.complete_button.click()
        assert viewer.review_complete and viewer.review_passed
        assert viewer.subject_decisions == {"specimen.vtk": "pass"}
    else:
        assert not viewer.review_recorded
        assert "Technically invalid fit" in viewer.review_gate.text()
    assert candidate.metrics["converged"] is False
    assert (
        candidate.metrics["attachment_comparison"]["subjects"]["specimen.vtk"]["regional_quality"][
            "numerical_selection_suitable"
        ]
        is False
    )
    assert not panel.invoked
    viewer.close()
    panel.app.processEvents()


def test_selected_starting_fit_has_own_working_card_and_preparation_action(panel):
    import os

    from PySide6.QtWidgets import QFrame, QLabel, QPushButton

    proposal = dict(available=True, reason='Start from the selected saved deformation.',
        title='Improve marked areas and protect the rest', initialization='residual',
        numerical_extension=False, goal='regional', remaining_checks=5)
    panel.guidance['working_proposals'] = {
        panel.candidate.candidate_id: defaultdict(lambda: proposal, detail=proposal)}
    panel.render()
    cards = [w for w in panel.window.findChildren(QFrame) if w.property('workingFit')]
    assert len(cards) == 1
    assert any(w.text().startswith('Latest attempt · saved for comparison:')
               for w in panel.window.findChildren(QLabel))
    buttons = [b for b in cards[0].findChildren(QPushButton)
               if b.isVisible() and 'prepare 1 trial on 1 specimen' in b.text()]
    assert len(buttons) == 1 and buttons[0].isEnabled()
    buttons[0].click()
    assert panel.invoked[-1][1]['guided_action'][0] == 'adaptive_recover_start'
    capture = os.environ.get('DF_WORKING_UI_CAPTURE')
    if capture:
        from diffeoforge.desktop.appearance import Appearance, themed_style
        from diffeoforge.desktop.widgets import _STYLE

        panel.window.setStyleSheet(themed_style(_STYLE, Appearance()))
        panel.window.resize(1050, 780)
        panel.app.processEvents()
        assert panel.window.grab().save(capture)

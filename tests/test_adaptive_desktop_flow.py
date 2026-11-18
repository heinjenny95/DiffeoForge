"""Actual offscreen Qt journeys; no native worker, mesh replay or owner study."""

from copy import deepcopy

import pytest
from pilot_view_helpers import wait_pilot_view
from test_guided_suitable_dialog import panel as panel


def bounded(*, closed=False, recommendation=None):
    # Explicit boundary: the worker's verified ledger presentation is supplied
    # here. Durable cap/receipt integrity is tested separately with the real policy.
    return dict(
        spent=220 if closed else 0,
        held=0,
        total=600,
        stage_iterations=100,
        purpose="warm",
        wall_seconds=7200,
        closed=closed,
        reason="The declared allowance ended; keep the earlier feasible field." if closed else "",
        recommendation=recommendation,
        requires_review=bool(recommendation),
    )


def retained_reference(root):
    return dict(
        directory=str(root / "earlier-accepted-field"),
        candidate_id="guided-varifold",
        target="specimen.vtk",
        method="varifold",
        manifest_sha256="1" * 64,
        binding=dict(metrics_sha256="2" * 64),
        values=dict(deformation_kernel_width=0.4),
    )


def test_prepared_adaptive_run_names_shared_cap_and_separate_native_stage(panel):
    from PySide6.QtWidgets import QLabel

    panel.candidate.status = "pending"
    panel.candidate.metrics = None
    panel.snapshot.visual_reviews.clear()
    panel.guidance.update(bounded_adaptive=bounded(), feedback={}, proposals={})
    panel.window.layout().addWidget(panel.window.start_button)
    panel.render()
    assert panel.window.start_button.isVisible() and panel.window.start_button.isEnabled()
    assert panel.window.start_button.text() == "Run adaptive correction · ≤600 total iterations"
    note = panel.window.findChild(QLabel, "adaptiveEffort")
    assert note is not None and note.isVisible()
    assert "0 / 600 iterations used across all attempts" in note.text()
    assert "100 maximum in this stage" in note.text()
    assert "2 h deadline includes preparation and checks" in note.text()
    assert not panel.invoked


@pytest.mark.parametrize("failed_status", ["failed", "interrupted"])
def test_closed_failed_child_disables_run_and_reviews_exact_retained_field(panel, failed_status):
    from PySide6.QtWidgets import QLabel, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    reference = retained_reference(panel.snapshot.study_directory)
    source_reference = deepcopy(reference)
    panel.candidate.status = failed_status
    panel.candidate.metrics = None
    panel.candidate.error = "Synthetic incomplete child; earlier field remains saved"
    panel.snapshot.visual_reviews.clear()
    panel.guidance.update(
        bounded_adaptive=bounded(closed=True, recommendation=reference), feedback={}, proposals={}
    )
    opened = []
    panel.window._open_guided_working_fit = lambda *a, **k: opened.append((a, k))
    panel.window.layout().addWidget(panel.window.start_button)
    panel.window.next_step_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._perform_final_next_step(panel.window)
    )
    panel.render()
    assert panel.window.start_button.isHidden() and not panel.window.start_button.isEnabled()
    assert panel.window.review_next_button.isHidden()
    assert (
        panel.window.next_step_button.text() == "Review retained adaptive fit · mark / edit areas…"
    )
    assert panel.window.next_step_button.isVisible() and panel.window.next_step_button.isEnabled()
    assert panel.window._guided_footer_action == (
        panel.snapshot.study_directory,
        "bounded_retained",
        (panel.candidate.candidate_id, reference),
    )
    primaries = [
        button
        for button in panel.window.findChildren(QPushButton)
        if button.isVisible() and button.isEnabled() and button.objectName() == "primary"
    ]
    assert primaries == [panel.window.next_step_button]
    assert "220 / 600" in panel.window.findChild(QLabel, "adaptiveEffort").text()
    assert (
        "Anatomical review is still required"
        in panel.window.findChild(QLabel, "adaptiveResult").text()
    )
    panel.window.start_button.click()
    assert not panel.invoked
    panel.window.next_step_button.click()
    assert opened == [((panel.candidate.candidate_id, source_reference), {})]
    assert reference == source_reference and not panel.invoked
    assert panel.snapshot.visual_reviews == {}
    # A visible retained-result action still respects the actual active-worker gate.
    panel.window._worker = object()
    panel.window.next_step_button.click()
    assert len(opened) == 1 and not panel.invoked
    panel.window._worker = None


def test_adaptive_extension_is_the_primary_preparation_and_review_remains_available(panel):
    from PySide6.QtWidgets import QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    reference = retained_reference(panel.snapshot.study_directory)
    offer = dict(
        iterations=300,
        remaining_regions=[
            dict(label="A", improvement_percent=14.3),
            dict(label="C", improvement_percent=5.5),
        ],
    )
    panel.snapshot.visual_reviews.clear()
    result = bounded(closed=True, recommendation=reference)
    result.update(spent=600, extension=offer)
    panel.guidance.update(bounded_adaptive=result, feedback={}, proposals={})
    panel.window.layout().addWidget(panel.window.start_button)
    panel.window.next_step_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._perform_final_next_step(panel.window)
    )
    panel.window.review_next_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._open_next_review(panel.window)
    )
    opened = []
    panel.window._snapshot = panel.snapshot
    panel.window._open_guided_working_fit = lambda *args: opened.append(args)
    panel.render()

    assert panel.window.start_button.isHidden()
    assert panel.window.next_step_button.text() == "Prepare +300 iterations"
    primaries = [
        button for button in panel.window.findChildren(QPushButton)
        if button.isVisible() and button.isEnabled() and button.objectName() == "primary"
    ]
    assert primaries == [panel.window.next_step_button]
    assert "Area A (14.3%), Area C (5.5%)" in panel.window.status.text()
    assert "Protection checks passed" in panel.window.status.text()
    assert not panel.invoked
    panel.window.review_next_button.click()
    assert opened == [(panel.candidate.candidate_id, reference)]
    assert not panel.invoked

    panel.window.next_step_button.click()
    assert panel.invoked == [((), dict(adaptive=False, guided_action=(
        "adaptive_extend_bounded", panel.candidate.candidate_id, offer,
    )))]
    assert panel.snapshot.visual_reviews == {}


def test_prepared_extension_requires_a_separate_run(panel):
    from PySide6.QtWidgets import QLabel

    panel.candidate.status = "pending"
    panel.candidate.metrics = None
    panel.snapshot.visual_reviews.clear()
    result = bounded()
    result.update(total=300, stage_iterations=300, purpose="continue", extension_from=600)
    panel.guidance.update(bounded_adaptive=result, feedback={}, proposals={})
    panel.window.layout().addWidget(panel.window.start_button)
    panel.render()
    assert panel.window.start_button.isVisible() and panel.window.start_button.isEnabled()
    assert panel.window.start_button.text() == "Run +300 continuation"
    assert "Continuation after 600 iterations · 0 / 300" in (
        panel.window.findChild(QLabel, "adaptiveEffort").text()
    )
    assert "Prepare +300" not in panel.window.next_step_button.text()
    assert not panel.invoked


def test_open_expired_action_without_recommendation_cannot_restart_it(panel):
    panel.candidate.status = "pending"
    panel.candidate.metrics = None
    panel.snapshot.visual_reviews.clear()
    panel.guidance.update(bounded_adaptive=bounded(closed=True), feedback={}, proposals={})
    panel.render()
    assert not panel.window.start_button.isEnabled()
    assert panel.window.start_button.isHidden()
    panel.window.start_button.click()
    assert not panel.invoked


def test_ordinary_view_clears_adaptive_progress_before_new_native_events(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_guided_pilot import origin

    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    snapshot = guided.prepare(origin(tmp_path).study_directory)
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *_a, **_k: pytest.fail("A presentation journey launched an optimizer"),
    )
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        ordinary = dialog._prepared_view
        dialog._event(
            dict(event="bounded_adaptive_progress", spent=180, total=600, purpose="cp_probe")
        )
        identifier = snapshot.candidates[0].candidate_id

        def progress(iteration, maximum):
            dialog._event(
                dict(
                    event="candidate_worker_event",
                    candidate_id=identifier,
                    worker_event=dict(
                        kind="progress",
                        payload=dict(iteration=iteration, maximum_iterations=maximum),
                    ),
                )
            )

        progress(7, 40)
        assert "Adaptive correction: 187 / 600 total iterations" in dialog.status.text()
        assert "cp probe (7 / 40)" in dialog.status.text()
        assert dialog._bounded_adaptive_progress is not None
        # Use the real controller render and actual prepared ordinary snapshot,
        # so reset is exercised at the same boundary as project/study navigation.
        dialog._render(prepared=ordinary)
        assert dialog._bounded_adaptive_progress is None
        progress(3, 120)
        assert "Deformetrica iteration 3 of 120 total" in dialog.status.text()
        assert "Adaptive correction" not in dialog.status.text()
        assert "600" not in dialog.status.text()
        assert dialog._worker is None
        assert snapshot.visual_reviews == {}
    finally:
        dialog.close()
        app.processEvents()
def test_uninspected_numerical_history_opens_review_before_returning(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

    from diffeoforge.desktop.guided_feedback import render_starting_fits

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    panel = QWidget()
    layout = QVBoxLayout(panel)
    reference = dict(directory=str(tmp_path / "numerical"), method="varifold")
    opened = []
    panel._open_guided_saved_fit = lambda *a: None
    panel._open_guided_working_fit = lambda *a: opened.append(a)
    panel._start_pilot = lambda **kw: pytest.fail("History navigation dispatched fitting")
    snapshot = SimpleNamespace(attachment_comparison={"methods": {"test": "varifold"}})
    data = dict(selected=None, choices=[dict(reference=reference, label="Numerical stage",
                approved=False, inspected=False, current=False, trial_index=1)])
    try:
        render_starting_fits(panel, snapshot, "test", layout, data)
        labels = [row.text() for row in panel.findChildren(QLabel)]
        assert any("anatomical review needed" in text for text in labels)
        assert not any("inspected, not approved" in text for text in labels)
        button = next(row for row in panel.findChildren(QPushButton)
                      if row.text().startswith("Inspect first fit before"))
        button.click()
        assert opened == [("test", reference)]
    finally:
        panel.close()
        app.processEvents()

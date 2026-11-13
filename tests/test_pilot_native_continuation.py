"""Cumulative pilot dispatch with synthetic controllers and real study journals."""

import copy
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_pilot_completion import _checked

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_continuation as continuation
from diffeoforge import reference_pilot_qualification as qualification
from diffeoforge.config import load_config
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.mesh import sha256_file


def _fixture(tmp_path, monkeypatch):
    runner, snapshot, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    root = snapshot.study_directory
    # The ordinary fixture prohibits new runs after its fixed-state check. Only
    # synthetic controllers are re-enabled here; no native optimizer is used.
    monkeypatch.setattr(runner, "run_current_stage",
                        study.ReferenceCalibrationStudyRunner.run_current_stage.__get__(runner))
    calls = []

    def checkpoint(source):
        config = copy.deepcopy(load_config(source.config_path))
        maximum = source.metrics["maximum_iterations"]
        config["optimization"]["max_iterations"] = maximum
        run = study.calibration_candidate_run_directory(source)
        return SimpleNamespace(manifest=dict(effective_config=config)), dict(
            version=continuation.VERSION, source_run=str(run),
            source_manifest_sha256=sha256_file(run / "manifest.json"),
            checkpoint_sha256="a" * 64, initial_iteration=maximum,
            additional_iterations=300, maximum_iterations=maximum + 300,
            history="Synthetic checkpoint dispatch fixture",
        )

    def request(source, *, request_id, run_id, additional_iterations):
        source = Path(source)
        calls.append((source, additional_iterations))
        event = next(e for e in reversed(study._load_events(root))
                     if e["event"] == "pilot_qualification_declared")
        path = root / event["config"]
        return DesktopReferenceLaunchRequest(
            request_id, path, source.parent / run_id, run_id, sha256_file(path),
            None, None, launcher_type="native", resume_source=source,
            additional_iterations=additional_iterations, launcher_executable="deformetrica",
        )

    collect = study.collect_reference_calibration_run_metrics

    def metrics(run):
        result = collect(run)
        event = next(e for e in reversed(study._load_events(root))
                     if e["event"] == "pilot_qualification_declared")
        maximum = event["checkpoint_continuation"]["maximum_iterations"]
        return replace(result, final_iteration=maximum, maximum_iterations=maximum)

    zero = dict(rms=0.0, p95=0.0, maximum=0.0)
    names = [s.filename for s in snapshot.plan.selected_pilot_subjects]
    monkeypatch.setattr(continuation, "_checkpoint", checkpoint)
    monkeypatch.setattr("diffeoforge.desktop.reference_prelaunch.build_reference_resume_launch_request",
                        request)
    monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", metrics)
    monkeypatch.setattr(qualification, "optimizer_check", lambda *a: dict(
        template=zero, subjects={n: zero for n in names},
        velocity_relative={n: 0.0 for n in names},
    ))
    from diffeoforge import reference_adaptive_calibration, reference_pilot_completion

    monkeypatch.setattr(qualification, "shoot", reference_pilot_completion.shoot)
    monkeypatch.setattr(qualification, "bind_learned_seed",
                        reference_adaptive_calibration.bind_learned_seed)
    return runner, snapshot, identifier, calls


def test_two_additional_budgets_chain_latest_checkpoint_and_preserve_source(tmp_path, monkeypatch):
    runner, before, identifier, calls = _fixture(tmp_path, monkeypatch)
    root = before.study_directory
    original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    source = next(c for c in before.candidates if c.candidate_id == identifier)
    initial = load_config(source.config_path)
    first = continuation.run(runner, identifier)
    one = first.candidates[-1]
    second = continuation.run(runner, identifier)  # Same old card must select its latest child.
    two = second.candidates[-1]
    assert one.metrics["final_iteration"] == 350
    assert two.metrics["final_iteration"] == 650
    assert calls == [(study.calibration_candidate_run_directory(source), 300),
                     (one.run_directory, 300)]
    assert two.metrics["pilot_continuation"]["source_candidate_id"] == one.candidate_id
    assert continuation.latest(second, identifier) == two
    for candidate in (one, two):
        config = load_config(candidate.config_path)
        assert config["optimization"]["convergence_tolerance"] == initial["optimization"][
            "convergence_tolerance"]
        assert config["runtime"]["precision"] == initial["runtime"]["precision"]
        assert config["optimization"]["freeze_template"] == initial["optimization"][
            "freeze_template"]
        assert candidate.candidate_id not in second.visual_reviews
    assert all(p.read_bytes() == data for p, data in original.items()
               if p.name != study.STUDY_EVENTS)
    assert (root / study.STUDY_EVENTS).read_bytes().startswith(original[root / study.STUDY_EVENTS])
    assert study.load_reference_calibration_study(root).candidates == second.candidates


def test_changed_continuation_checkpoint_is_rejected_before_dispatch(tmp_path, monkeypatch):
    _, snapshot, identifier, calls = _fixture(tmp_path, monkeypatch)
    prepared, _ = continuation.prepare(snapshot, identifier)
    events = study._load_events(snapshot.study_directory)
    event = copy.deepcopy(qualification.declarations(events)[-1])
    event["checkpoint_continuation"]["checkpoint_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="settings or checkpoint changed"):
        continuation.verify(prepared.study_directory, event, events)
    assert not calls


@pytest.mark.parametrize("reopen", [False, True], ids=["direct", "resume-declared"])
def test_dialog_selects_new_continuation_result_for_fresh_review(tmp_path, monkeypatch, reopen):
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication
    from test_pilot_completion import _approve_preview

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    runner, original, identifier, calls = _fixture(tmp_path, monkeypatch)
    _approve_preview(original, identifier)
    before = study.load_reference_calibration_study(original.study_directory)
    if reopen:
        before, _ = continuation.prepare(before, identifier)
    expected = qualification.declarations(study._load_events(before.study_directory))
    assert len(expected) == int(reopen)

    application = QApplication.instance() or QApplication([])
    dialog = ReferenceCalibrationDialog(before.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(identifier))
        assert dialog.selection_combo.currentData() == identifier
        assert dialog.next_step_button.isEnabled()
        if reopen:
            assert dialog.next_step_button.text() == "Resume saved check"
            assert not dialog.final_finish_button.isVisible()
        else:
            assert dialog.next_step_button.text().startswith("Continue saved fit: +300 iterations")
            assert dialog.final_finish_button.isVisible()
        workers = []
        monkeypatch.setattr(dialog._thread_pool, "start", workers.append)
        dialog.next_step_button.click()
        assert len(workers) == 1
        worker = workers[0]
        assert worker.qualification is reopen
        assert worker.continuation == (None if reopen else (identifier, 300))
        worker.runner = runner  # Keep the synthetic controller for the full route.
        worker.run()
        wait_pilot_view(dialog)
        declarations = qualification.declarations(study._load_events(before.study_directory))
        assert len(declarations) == 1
        if reopen:
            assert declarations == expected
        declaration = declarations[0]
        assert calls == [(Path(declaration["checkpoint_continuation"]["source_run"]), 300)]
        continuation_id = declaration["candidate"]["candidate_id"]
        assert dialog.selection_combo.currentData() == continuation_id
        assert dialog.next_step_button.text() == "Review saved fit…"
        assert dialog.snapshot.visual_reviews[identifier] is True
        assert continuation_id not in dialog.snapshot.visual_reviews

        if not reopen:
            dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(identifier))
            dialog._start_pilot(adaptive=False, qualification=True)
            assert len(workers) == 2
            workers[-1].runner = runner
            workers[-1].run()
            wait_pilot_view(dialog)
            assert dialog.selection_combo.currentData() == identifier
            assert len(calls) == 1  # Reusing the time check starts no fitting.
    finally:
        dialog.close()
        application.processEvents()


def test_dialog_compares_continuation_with_immediate_checkpoint_source(tmp_path, monkeypatch):
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication
    from test_pilot_completion import _approve_preview

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    runner, before, identifier, calls = _fixture(tmp_path, monkeypatch)
    collect = study.collect_reference_calibration_run_metrics
    names = tuple(s.filename for s in before.plan.selected_pilot_subjects)
    worse_subject = names[-1]

    def collect_measured_continuation(run):
        metrics = collect(run)
        if metrics.final_iteration == 350:
            return replace(
                metrics,
                residual_p95=0.10,
                subject_residual_p95=tuple((name, 0.10) for name in names),
            )
        assert metrics.final_iteration == 650
        return replace(
            metrics,
            residual_p95=0.09,
            attachment_objective_magnitude=0.4,
            subject_residual_p95=tuple(
                (name, 0.13 if name == worse_subject else 0.08) for name in names
            ),
        )

    monkeypatch.setattr(
        study, "collect_reference_calibration_run_metrics", collect_measured_continuation
    )
    first = continuation.run(runner, identifier)
    prior = first.candidates[-1]
    second = continuation.run(runner, identifier)
    latest = second.candidates[-1]
    _approve_preview(second, latest.candidate_id)

    application = QApplication.instance() or QApplication([])
    dialog = ReferenceCalibrationDialog(second.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        dialog.selection_combo.setCurrentIndex(
            dialog.selection_combo.findData(latest.candidate_id)
        )
        assert dialog.selection_combo.currentData() == latest.candidate_id
        assert dialog.final_check_summary.isVisible()
        assert not dialog.scroll.isAncestorOf(dialog.final_check_summary)
        summary = dialog.final_check_summary.text()
        assert "350 → 650" in summary
        assert worse_subject in summary
        assert "Surface P95" in summary
        assert "2 closer, 1 farther" in summary
        assert re.search(r"\+30(?:\.0+)?\s*%", summary)
        assert "cost" in summary.lower()
        assert re.search(r"-11\.1\d*\s*%", summary)
        assert dialog.next_step_button.isEnabled()
        assert "recommended" not in dialog.next_step_button.text().lower()
        assert dialog.final_finish_button.isVisible()

        dialog.selection_combo.setCurrentIndex(
            dialog.selection_combo.findData(prior.candidate_id)
        )
        assert dialog.selection_combo.currentData() == prior.candidate_id
        summary = dialog.final_check_summary.text()
        assert "50 → 350" in summary
        assert "350 → 650" not in summary
        dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(identifier))
        assert "Last continuation" not in dialog.final_check_summary.text()
        assert len(calls) == 2
    finally:
        dialog.close()
        application.processEvents()


@pytest.mark.parametrize("mismatch", [False, True], ids=["missing-subject", "metric-family"])
def test_continuation_keeps_objective_when_surfaces_are_incomparable(mismatch):
    from diffeoforge.desktop.reference_calibration_presentation import continuation_progress

    source = SimpleNamespace(
        candidate_id="first",
        status="completed",
        metrics={
            "final_iteration": 300,
            "metric_version": "0.2",
            "attachment_objective_magnitude": 0.0,
            "deformation_energy": 0.0,
        },
    )
    latest = SimpleNamespace(
        candidate_id="continued",
        status="completed",
        metrics={
            **source.metrics,
            "final_iteration": 600,
            "metric_version": "0.1" if mismatch else "0.2",
            "pilot_continuation": {
                "version": continuation.VERSION,
                "source_candidate_id": source.candidate_id,
                "initial_iteration": 300,
            },
        },
    )
    snapshot = SimpleNamespace(
        candidates=(source, latest),
        plan=SimpleNamespace(
            selected_pilot_subjects=(SimpleNamespace(filename="subject.vtk"),)
        ),
    )
    fits = {
        "first": {"subject.vtk": 0.2},
        "continued": {"subject.vtk": 0.1} if mismatch else {},
    }

    summary = continuation_progress(snapshot, latest, fits)

    assert "300 → 600" in summary
    assert "cost" in summary.lower()
    assert "0 → 0 (unchanged)" in summary
    assert "Surface P95 · comparable measurements unavailable" in summary
    assert "closer" not in summary
    assert continuation_progress(snapshot, source, fits) == ""


def test_failed_continuation_can_retry_or_finish_the_reviewed_source(tmp_path, monkeypatch):
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QMessageBox
    from test_pilot_completion import _approve_preview
    from test_reference_calibration_study import _FailedController

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    runner, original, identifier, calls = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_controller_factory", _FailedController)
    failed = continuation.run(runner, identifier)
    failed_id = failed.candidates[-1].candidate_id
    assert failed.candidates[-1].status == "failed"
    root = failed.study_directory
    declarations = qualification.declarations(study._load_events(root))

    application = QApplication.instance() or QApplication([])
    dialog = ReferenceCalibrationDialog(root)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(identifier))
        assert dialog.next_step_button.text() == "Resume saved check"
        assert not dialog.final_retry_button.isVisible()
        _approve_preview(original, identifier)
        dialog._render()
        wait_pilot_view(dialog)
        assert dialog.selection_combo.currentData() == identifier
        assert dialog.next_step_button.text() == "Finish pilot provisionally → atlas setup"
        assert dialog.next_step_button.isVisible() and dialog.next_step_button.isEnabled()
        assert dialog.final_retry_button.text() == "Retry failed continuation"
        assert dialog.final_retry_button.isVisible() and dialog.final_retry_button.isEnabled()
        assert dialog.final_retry_button.objectName() == "secondary"
        assert not dialog.scroll.isAncestorOf(dialog.final_retry_button)
        assert not dialog.final_finish_button.isVisible()

        workers = []
        monkeypatch.setattr(dialog._thread_pool, "start", workers.append)
        dialog.final_retry_button.click()
        assert len(workers) == 1 and workers[0].qualification
        assert not dialog.next_step_button.isEnabled()
        assert not dialog.final_retry_button.isEnabled()
        workers[0].runner = runner
        workers[0].run()
        wait_pilot_view(dialog)
        assert qualification.declarations(study._load_events(root)) == declarations
        retry = next(c for c in dialog.snapshot.candidates if c.candidate_id == failed_id)
        assert retry.status == "failed" and retry.attempts == 2
        assert calls == [(Path(declarations[0]["checkpoint_continuation"]["source_run"]), 300)] * 2
        assert dialog.snapshot.visual_reviews[identifier] is True

        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
        dialog.next_step_button.click()
        assert len(workers) == 1
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
        dialog.next_step_button.click()
        assert len(workers) == 2 and workers[1].finish_candidate_id == identifier
        workers[1].run()
        assert dialog.snapshot.status == "completed"
        assert dialog.snapshot.selected_candidate_ids["timepoints"] == identifier
        assert len(calls) == 2
        failures = [event for event in study._load_events(root)
                    if event["event"] == "candidate_failed" and event["candidate_id"] == failed_id]
        assert len(failures) == 2
    finally:
        dialog.close()
        application.processEvents()

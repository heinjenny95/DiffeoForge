import shutil
from dataclasses import dataclass, replace

import pytest
from test_reference_calibration_study import _approve_for_test
from test_reference_integration_check import _fourth

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_completion as completion
from diffeoforge.config import load_config


def _checked(tmp_path, monkeypatch, *, capped=False, bad=False):
    runner, fourth = _fourth(tmp_path, monkeypatch)
    if capped:
        collect = study.collect_reference_calibration_run_metrics
        monkeypatch.setattr(
            study,
            "collect_reference_calibration_run_metrics",
            lambda run: replace(
                collect(run),
                converged=False,
                optimizer_stop_signal="maximum_iterations",
                final_iteration=50,
                maximum_iterations=50,
            ),
        )
    done = runner.run_current_stage()
    template = next((done.study_directory / "inputs/template").glob("*.vtk"))
    names = [s.filename for s in done.plan.selected_pilot_subjects]
    monkeypatch.setattr(
        completion.legacy, "_reconstructions", lambda *a: (None, {n: template for n in names})
    )
    calls = []

    def shoot(config, folder, seed, destination, count, **kwargs):
        calls.append(count)
        destination.mkdir(parents=True)
        paths = {}
        for name in names:
            paths[name] = destination / name
            shutil.copyfile(template, paths[name])
        return paths, {}

    monkeypatch.setattr(completion, "shoot", shoot)
    if bad:
        real = completion.movement
        monkeypatch.setattr(
            completion,
            "movement",
            lambda a, b, scale: (
                dict(rms=0.1, p95=0.1, maximum=0.1) if names[-1] in str(b) else real(a, b, scale)
            ),
        )
    monkeypatch.setattr(
        runner, "run_current_stage", lambda **k: pytest.fail("No optimization allowed")
    )
    result = completion.run(runner, candidate_id=done.candidates[0].candidate_id)
    return runner, result, calls, done.candidates[0].candidate_id


def _approve_preview(done, identifier):
    names = tuple(s.filename for s in done.plan.selected_pilot_subjects)
    return study.record_reference_calibration_candidate_review(
        done.study_directory,
        candidate_id=identifier,
        approved=True,
        reviewed_subjects=names,
        subject_decisions={name: "pass" for name in names},
        display_scopes={name: "preview" for name in names},
    )


@pytest.mark.parametrize("capped", [False, True])
def test_preview_qc_finishes_reopens_and_repeated_finish_keeps_all_bytes(
    tmp_path, monkeypatch, capped
):
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=capped)
    reviewed = _approve_preview(done, identifier)
    assert reviewed.visual_reviews[identifier] is True
    assert not any(
        e["event"] == "candidate_visual_review" and e.get("candidate_id") == identifier
        for e in study._load_events(done.study_directory)
    )
    final, _ = completion.finish(done.study_directory, identifier)
    assert final.status == "completed"
    saved = {p: p.read_bytes() for p in final.study_directory.rglob("*") if p.is_file()}
    assert study.load_reference_calibration_study(final.study_directory).status == "completed"
    again, _ = completion.finish(final.study_directory, identifier)
    assert again == final
    with pytest.raises(ValueError, match="different saved fit"):
        completion.finish(final.study_directory, "different")
    assert all(p.read_bytes() == value for p, value in saved.items())
    # The selection's approval summary is not a replacement for the human QC journal.
    series, _ = study._search_extension_series(final.study_directory)
    review_path = series / "visual-reviews.json"
    data = review_path.read_bytes()
    review_path.unlink()
    with pytest.raises(ValueError, match="Review"):
        study.load_reference_calibration_study(final.study_directory)
    review_path.write_bytes(data)
    assert study.load_reference_calibration_study(final.study_directory).status == "completed"


def test_legacy_receipt_finishes_with_desktop_preview_review_and_rejects_changed_binding(
    tmp_path, monkeypatch
):
    import json

    from test_pilot_qualification import _complete_check

    _, done, _, _ = _complete_check(tmp_path, monkeypatch, legacy=True)
    identifier = done.candidates[-1].candidate_id
    _approve_preview(done, identifier)
    final, _ = completion.finish(done.study_directory, identifier)
    assert final.status == "completed"
    series, _ = study._search_extension_series(final.study_directory)
    path = series / "visual-reviews.json"
    journal = json.loads(path.read_text())
    record = journal["records"][-1]
    record["source"]["result_sha256"] = "0" * 64
    record["event_hash"] = study._canonical_hash(
        {k: v for k, v in record.items() if k != "event_hash"}
    )
    path.write_text(json.dumps(journal), encoding="utf-8")
    with pytest.raises(ValueError, match="source evidence changed"):
        study.load_reference_calibration_study(final.study_directory)


def test_fixed_check_never_optimizes_reuses_evidence_and_keeps_fresh_review(tmp_path, monkeypatch):
    runner, done, counts, identifier = _checked(tmp_path, monkeypatch)
    assert len(counts) == 3
    n = int(load_config(done.candidates[0].config_path)["model"]["deformation"]["timepoints"])
    assert counts == [n, 2 * n - 1, 4 * n - 3]
    assert not done.visual_reviews
    assert not study.assess_reference_calibration_snapshot(
        done, completion_preview=True
    ).balanced_candidate_id
    old = {p: p.read_bytes() for p in done.study_directory.rglob("*") if p.is_file()}
    completion.run(runner, candidate_id=identifier)
    assert len(counts) == 3
    assert all(p.read_bytes() == data for p, data in old.items())
    with pytest.raises(ValueError, match="Review"):
        completion.finish(done.study_directory, identifier)
    _approve_for_test(done.study_directory, identifier)
    reviewed = study.load_reference_calibration_study(done.study_directory)
    assert (
        study.assess_reference_calibration_snapshot(
            reviewed, completion_preview=True
        ).balanced_candidate_id
        == identifier
    )
    final, _ = completion.finish(done.study_directory, identifier)
    assert final.status == "completed"
    assert not study.load_reference_calibration_report(final.study_directory)[
        "final_pilot_completion"
    ]["provisional"]


def test_capped_fit_finishes_only_explicitly_with_warnings_and_original_tolerance(
    tmp_path, monkeypatch
):
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    assert completion.provisional_available(done, identifier)
    with pytest.raises(ValueError, match="Review"):
        completion.finish(done.study_directory, identifier)
    _approve_for_test(done.study_directory, identifier)
    reviewed = study.load_reference_calibration_study(done.study_directory)
    assert not study.assess_reference_calibration_snapshot(
        reviewed, completion_preview=True
    ).balanced_candidate_id
    with pytest.raises(ValueError):
        study.record_reference_calibration_stage_review(
            done.study_directory, selected_candidate_id=identifier, visual_approvals={}
        )
    from diffeoforge import reference_adaptive_calibration as adaptive

    bind = adaptive.bind_learned_seed

    def tighter(*a, **kw):
        seed = bind(*a, **kw)
        seed["optimization"]["convergence_tolerance"] = 1e-6
        return seed

    monkeypatch.setattr("diffeoforge.reference_adaptive_calibration.bind_learned_seed", tighter)
    final, _ = completion.finish(done.study_directory, identifier)
    report = study.load_reference_calibration_report(final.study_directory)
    assert report["final_pilot_completion"]["provisional"]
    assert report["final_pilot_completion"]["converged"] is False
    assert "PROVISIONAL" in final.report_html_path.read_text(encoding="utf-8")
    config = load_config(final.final_config_path)
    manifest = study._verify_manifest(final.study_directory)
    original = load_config(final.study_directory / manifest["source_config"]["copy"])
    assert (
        config["optimization"]["convergence_tolerance"]
        == original["optimization"]["convergence_tolerance"]
    )
    assert config["model"]["deformation"].get("initial_momenta")
    assert config["project"]["parameter_provenance"]["recommendation"]["calibration_result"][
        "full_cohort_initialization"
    ]["method"] == "preserved_pilot_momenta_fixed_basis_initialization"
    assert study.load_reference_calibration_study(final.study_directory).status == "completed"


def test_one_bad_specimen_or_rejected_anatomy_blocks_provisional_finish(tmp_path, monkeypatch):
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=True, bad=True)
    _approve_for_test(done.study_directory, identifier)
    reviewed = study.load_reference_calibration_study(done.study_directory)
    assert not completion.provisional_available(reviewed, identifier)
    with pytest.raises(ValueError, match="integration evidence"):
        completion.finish(done.study_directory, identifier)


def test_changed_integration_artifact_blocks_reopening_and_finish(tmp_path, monkeypatch):
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    receipt = completion.evidence(done)[identifier]["receipt"]
    path = done.study_directory / next(iter(receipt["artifacts"]))
    path.write_bytes(path.read_bytes() + b"\n ")
    with pytest.raises(ValueError, match="artifact changed"):
        study.load_reference_calibration_study(done.study_directory)


def test_legacy_failed_receipt_keeps_meaning_but_state_drift_is_diagnostic(tmp_path, monkeypatch):
    from test_pilot_qualification import _complete_check

    from diffeoforge import reference_pilot_qualification as legacy

    # A native-converged state may fail an old whole-continuation drift budget.
    original_run = legacy.run

    def with_drift(*args, **kwargs):
        base = legacy.optimizer_check

        def moving(*a):
            value = base(*a)
            for name in value["velocity_relative"]:
                value["velocity_relative"][name] = 0.2
            return value

        monkeypatch.setattr(legacy, "optimizer_check", moving)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(legacy, "run", with_drift)
    _, done, _, approve = _complete_check(tmp_path, monkeypatch)
    identifier = done.candidates[-1].candidate_id
    receipt = legacy.verified_receipts(done)[identifier]
    assert not receipt["numerical_pass"]
    before = (
        done.study_directory / completion.evidence(done)[identifier]["receipt_path"]
    ).read_bytes()
    approve(done.study_directory, identifier)
    final, _ = completion.finish(done.study_directory, identifier)
    report = study.load_reference_calibration_report(final.study_directory)
    assert report["final_pilot_completion"]["legacy_numerical_pass"] is False
    assert "did NOT pass" in final.report_html_path.read_text(encoding="utf-8")
    assert (
        done.study_directory / report["final_pilot_completion"]["receipt"]
    ).read_bytes() == before


def test_nonfinite_integration_evidence_rejected():
    row = dict(rms=float("nan"), p95=0.0, maximum=0.0)
    with pytest.raises(ValueError, match="finite"):
        completion.integration_failures(
            dict(
                valid_geometry=True,
                criteria=completion.CRITERIA,
                roundtrip={"a": row},
                integration={"10->19": {"a": row}},
            )
        )


def test_rejected_anatomy_cannot_finish_even_with_good_integration(tmp_path, monkeypatch):
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    reviewed = replace(done, visual_reviews={identifier: False})
    assert not completion.provisional_available(reviewed, identifier)
    with pytest.raises(ValueError, match="Review"):
        completion.decision(reviewed, identifier)


def test_capped_dialog_requires_recorded_qc_and_explicit_provisional_finish(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    dialog = ReferenceCalibrationDialog(done.study_directory)
    assert dialog.selection_combo.currentData() == done.candidates[-1].candidate_id
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(identifier))
    assert not dialog.advance_button.isEnabled()
    assert "no optimization" in dialog.qualification_button.text()
    _approve_preview(done, identifier)
    dialog._render()
    assert dialog.advance_button.isEnabled()
    assert "provisionally" in dialog.advance_button.text()
    assert not dialog._assessment.balanced_candidate_id
    dialog.continuation_iterations.setValue(400)
    assert all("Optional strict check" in b.text() for b in dialog._continuation_buttons.values())
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    dialog._advance()
    assert study.load_reference_calibration_study(done.study_directory).status == "awaiting_review"
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    workers = []
    monkeypatch.setattr(dialog._thread_pool, "start", workers.append)
    finished = []
    dialog.finished.connect(finished.append)
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *a, **k: pytest.fail("Finishing must not fit or shoot"),
    )
    dialog.show()
    dialog._advance()
    assert len(workers) == 1 and dialog._worker is workers[0]
    assert "Verifying saved pilot" in dialog.status.text()
    assert not dialog.advance_button.isEnabled()
    assert not dialog.cancel_button.isEnabled()
    dialog._advance()
    assert len(workers) == 1  # Double-click cannot dispatch another completion.
    workers[0].run()
    assert dialog.snapshot.status == "completed"
    assert dialog._worker is None
    assert finished == [dialog.DialogCode.Accepted]
    assert not dialog.isVisible()
    import json

    audit = completion.legacy.export_audit(done.study_directory, tmp_path / "audit.json")
    exported = json.loads(audit.read_text())
    assert exported["final_pilot_completion"]["provisional"]
    assert exported["saved_model_integration_checks"]
    dialog.close()
    app.processEvents()


def test_completed_dialog_has_explicit_return_to_atlas_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    app = QApplication.instance() or QApplication([])
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    _approve_preview(done, identifier)
    final, _ = completion.finish(done.study_directory, identifier)

    @dataclass
    class Result:
        config_path: object
        report_path: object = None

    window = DiffeoForgeWindow()
    window._result = Result(done.candidates[0].config_path)
    def refresh_after_application():
        assert window._reference_calibrated_config_path == final.final_config_path

    monkeypatch.setattr(
        window, "_refresh_reference_calibration_execution_card", refresh_after_application
    )
    reviewed = []
    monkeypatch.setattr(
        window, "_review_project", lambda: reviewed.append(window._result.config_path)
    )
    dialog = ReferenceCalibrationDialog(final.study_directory)
    window._reference_calibration_dialog = dialog
    window.centralWidget().setEnabled(False)
    dialog.finished.connect(window._reference_calibration_closed)
    dialog.show()
    assert "non-converged" in dialog.status.text()
    assert dialog.advance_button.text() == "Return to full atlas setup"
    assert dialog.advance_button.isEnabled()
    finished = []
    dialog.finished.connect(finished.append)
    dialog.advance_button.click()
    assert finished == [dialog.DialogCode.Accepted]
    assert window._reference_calibration_dialog is None
    assert window.centralWidget().isEnabled()
    assert window._result.config_path == final.final_config_path
    assert reviewed == [final.final_config_path]
    assert window.reference_parameter_profile_combo.currentText() == (
        "Pilot-calibrated selection (read-only)"
    )
    window.close()
    app.processEvents()


@pytest.mark.parametrize("strict", [False, True])
def test_worker_keeps_no_optimization_default_and_explicit_strict_route(monkeypatch, strict):
    from diffeoforge.desktop.reference_calibration_dialog import _CalibrationStageWorker

    calls = []
    monkeypatch.setattr(completion, "run", lambda *a, **k: calls.append("fixed") or "result")
    monkeypatch.setattr(
        completion.legacy, "run", lambda *a, **k: calls.append("strict") or "result"
    )
    worker = _CalibrationStageWorker(object(), qualification=True, strict_optimizer=strict)
    worker.run()
    assert worker.is_finished and worker.error_message is None
    assert calls == (["strict"] if strict else ["fixed"])

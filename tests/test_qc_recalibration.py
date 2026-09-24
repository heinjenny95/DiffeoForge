import json
import shutil
from dataclasses import replace

import pytest
from test_reference_calibration_study import _CompletedController, _metrics, _project

from diffeoforge.config import load_config
from diffeoforge.desktop.project_setup import load_existing_reference_project
from diffeoforge.desktop.qc_recalibration import prepare_qc_recalibration
from diffeoforge.desktop.registration_release import inspection_binding
from diffeoforge.desktop.result_review import (
    ModernResultArtifact,
    ModernResultReview,
    RegistrationQCItem,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration_study import (
    ReferenceCalibrationStudyRunner,
    create_reference_calibration_search_extension_study,
    load_reference_calibration_study,
    record_reference_calibration_stage_review,
)


@pytest.fixture
def source(tmp_path):
    config_path = _project(tmp_path)
    config = load_config(config_path)
    run = tmp_path / "completed-run"
    (run / "input/subjects").mkdir(parents=True)
    (run / "input/template").mkdir()
    from diffeoforge.config import validate_input_paths

    inputs = validate_input_paths(config, config_path)
    records, artifacts, items = [], [], []
    for role, originals in (("template", (inputs.template,)), ("subject", inputs.subjects)):
        for index, original in enumerate(originals):
            target = (
                run / "input" / ("template" if role == "template" else "subjects") / original.name
            )
            shutil.copyfile(original, target)
            digest = sha256_file(target)
            records.append(
                dict(
                    role=role,
                    staged_path=target.relative_to(run).as_posix(),
                    geometry={"sha256": digest},
                )
            )
            if role == "subject":
                key = f"original-{index}"
                artifacts.append(
                    ModernResultArtifact(
                        key, original.name, target, "vtk", target.stat().st_size, digest, "fixture"
                    )
                )
                items.append(RegistrationQCItem(index + 1, target.name, 0.01 * index, key, key))
    manifest = run / "manifest.json"
    manifest.write_text(json.dumps(dict(effective_config=config, inputs=records)))
    analysis = run / "analysis.json"
    analysis.write_text("{}")
    review = ModernResultReview(
        run,
        run,
        "test",
        "now",
        manifest,
        sha256_file(manifest),
        analysis,
        sha256_file(analysis),
        True,
        "converged",
        20,
        150,
        (),
        (),
        (),
        (),
        tuple(artifacts),
        (),
        engine_route="deformetrica_reference",
        registration_qc=tuple(items),
    )
    previous = {
        item["filename"]
        for item in config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"][
            "selected_pilot_subjects"
        ]
    }
    missed = next(item.subject_name for item in items if item.subject_name not in previous)
    control = next(item.subject_name for item in items if item.subject_name != missed)
    decisions = {missed: "fail", control: "pass"}
    inspections = {name: inspection_binding(review, name) for name in decisions}
    return review, decisions, inspections


def prepare(source, tmp_path):
    return prepare_qc_recalibration(
        *source, tmp_path / "successor", reason="extra protrusion", technical_checks_confirmed=True
    )


def test_successor_is_bounded_preserves_sources_and_full_cohort(source, tmp_path):
    review, decisions, _ = source
    before = {p: sha256_file(p) for p in review.run_directory.rglob("*") if p.is_file()}
    path = prepare(source, tmp_path)
    assert load_existing_reference_project(path).subject_count == len(review.registration_qc)
    config = load_config(path)
    plan = config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"]
    assert sum(len(s["candidates"]) for s in plan["stages"]) == 11
    assert set(decisions) <= {i["filename"] for i in plan["selected_pilot_subjects"]}
    assert "calibration_result" not in config["project"]["parameter_provenance"]["recommendation"]
    assert "preprocessing" not in config
    assert before == {p: sha256_file(p) for p in review.run_directory.rglob("*") if p.is_file()}
    study = next((path.parent / "calibration").iterdir())
    snapshot = load_reference_calibration_study(study)
    from diffeoforge.reference_calibration_report import render_reference_calibration_plan_html

    assert "11" in snapshot.plan.summary_text()
    assert "adaptive QC follow-up" in render_reference_calibration_plan_html(snapshot.plan)
    assert snapshot.status == "ready"
    assert all(c.status == "pending" for c in snapshot.candidates)
    with pytest.raises(ValueError, match="visual stage review"):
        ReferenceCalibrationStudyRunner(study).run_complete_automatic_pilot(afk=True)
    with pytest.raises(ValueError, match="bounded grid"):
        create_reference_calibration_search_extension_study(
            study, tmp_path / "extension", safety_limits={}
        )
    with pytest.raises(ValueError, match="new successor folder"):
        prepare(source, tmp_path)
    request_copy = study / "source/qc-request.json"
    request_copy.write_text("{}")
    with pytest.raises(ValueError, match="binding differs"):
        load_reference_calibration_study(study)


def test_review_required_and_new_configuration_keeps_whole_cohort(source, tmp_path, monkeypatch):
    import diffeoforge.reference_calibration_study as module

    path = prepare(source, tmp_path)
    study = next((path.parent / "calibration").iterdir())

    def collect(run):
        atlas = run / "atlas.vtk"
        atlas.write_text("fixture")
        return _metrics(atlas)

    monkeypatch.setattr(module, "collect_reference_calibration_run_metrics", collect)
    monkeypatch.setattr(module, "atlas_rms_distance", lambda *_args: 0.001)
    runner = ReferenceCalibrationStudyRunner(study, controller_factory=_CompletedController)
    for _ in range(4):
        snapshot = runner.run_current_stage()
        selected = snapshot.candidates[0].candidate_id
        with pytest.raises(ValueError, match="explicit visual approval"):
            record_reference_calibration_stage_review(
                study, visual_approvals={}, selected_candidate_id=selected
            )
        snapshot, _ = record_reference_calibration_stage_review(
            study, visual_approvals={selected: True}, selected_candidate_id=selected
        )
    assert snapshot.status == "completed"
    result = load_config(snapshot.final_config_path)
    assert result["input"] == load_config(path)["input"]
    assert result["project"]["parameter_provenance"]["recommendation"]["calibration_result"][
        "full_cohort_confirmation_required"
    ]
    assert not list((study / "selected").glob("runs/*"))


@pytest.mark.parametrize(
    "change", ["no_concern", "no_inspection", "changed_mesh", "modern", "inside_run"]
)
def test_fail_closed(source, tmp_path, change):
    review, decisions, inspections = source
    destination = tmp_path / "successor"
    if change == "no_concern":
        decisions = {}
    if change == "no_inspection":
        inspections = {}
    if change == "changed_mesh":
        review.artifacts[0].path.write_text("changed")
    if change == "modern":
        review = replace(review, engine_route="modern")
    if change == "inside_run":
        destination = review.run_directory / "new"
    with pytest.raises((ValueError, RuntimeError)):
        prepare_qc_recalibration(
            review,
            decisions,
            inspections,
            destination,
            reason="bad fit",
            technical_checks_confirmed=True,
        )
    assert not destination.exists()


def test_desktop_qc_button_worker_and_handoff(source, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from test_desktop_calibration import _prepared_window

    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import (
        _InputPreflightWorker,
        _QcRecalibrationWorker,
        _ReviewWorker,
    )

    app, window, queued = _prepared_window(monkeypatch, tmp_path)
    review, decisions, inspections = source
    window._result_review = review
    window._registration_qc_decisions = {}
    window._update_registration_qc_summary()
    assert window.result_qc_recalibrate_button.isHidden()
    window._registration_qc_decisions = decisions
    window._registration_visual_inspections = inspections
    window._update_registration_qc_summary()
    assert not window.result_qc_recalibrate_button.isHidden()
    assert window.result_qc_recalibrate_button.isEnabled()
    worker = _QcRecalibrationWorker(
        review, decisions, inspections, tmp_path / "successor", "bad fit"
    )
    window._worker = worker
    window._update_registration_qc_summary()
    assert not window.result_qc_recalibrate_button.isEnabled()
    successes, failures = [], []
    worker.signals.succeeded.connect(successes.append)
    worker.signals.failed.connect(failures.append)
    worker.run()
    assert not failures and len(successes) == 1
    window._worker = None
    window.engine_combo.setCurrentIndex(window.engine_combo.findData(DesktopEngine.MODERN_CPU))
    window._run_result = object()
    window._qc_recalibration_prepared(successes[0])
    app.processEvents()
    assert window._run_result is None and window._result_review is None
    assert window.engine_combo.currentData() == DesktopEngine.DEFORMETRICA_REFERENCE
    assert window.reference_parameter_profile_combo.currentData() == "data_assisted"
    assert window.project_edit.text() == str(tmp_path / "successor")
    assert window.already_gpa_check.isChecked() and not window.landmarks_edit.text()
    assert window._result.config_path == successes[0].config_path
    assert sum(isinstance(item, _ReviewWorker) for item in queued) == 1
    assert all(isinstance(item, (_ReviewWorker, _InputPreflightWorker)) for item in queued)
    # No numerical worker starts. Restored stored evidence also works after
    # a new app session, without a fresh recommendation or lost concern set.
    window._worker = None
    window._review = SimpleNamespace(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        config_path=successes[0].config_path,
        config_sha256=sha256_file(successes[0].config_path),
    )
    assert window._reference_recommendation is None
    assert window._reference_calibration_plan_matches_current_inputs()
    window.template_edit.blockSignals(True)
    window.template_edit.setText(str(tmp_path / "different.vtk"))
    window.template_edit.blockSignals(False)
    assert not window._reference_calibration_plan_matches_current_inputs()
    window.close()
    app.processEvents()


def test_qc_dialog_requires_visual_selection_and_no_afk(source, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import diffeoforge.reference_calibration_study as module
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication(["qc-followup-test"])
    path = prepare(source, tmp_path)
    study = next((path.parent / "calibration").iterdir())
    dialog = ReferenceCalibrationDialog(study)
    assert dialog.advanced_mode.isChecked() and dialog.afk_mode.isHidden()
    assert dialog.outward_mode.isHidden() and dialog.start_button.isEnabled()
    dialog.close()

    def collect(run):
        atlas = run / "atlas.vtk"
        atlas.write_text("fixture")
        return _metrics(atlas)

    monkeypatch.setattr(module, "collect_reference_calibration_run_metrics", collect)
    monkeypatch.setattr(module, "atlas_rms_distance", lambda *_args: 0.001)
    snapshot = ReferenceCalibrationStudyRunner(
        study, controller_factory=_CompletedController
    ).run_current_stage()
    dialog = ReferenceCalibrationDialog(study)
    selected = snapshot.candidates[0].candidate_id
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(selected))
    dialog._update_stage_review_action()
    assert not dialog.advance_button.isEnabled()
    dialog._visually_reviewed_candidates.add(selected)
    dialog._visually_approved_candidates.add(selected)
    dialog._update_stage_review_action()
    assert dialog.advance_button.isEnabled()
    assert dialog.collect_evidence_button.isHidden()
    dialog.close()
    app.processEvents()

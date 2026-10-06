import pytest
from test_reference_integration_check import _fourth

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_qualification as qualification
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_fixed_shooting import movement


def _evidence():
    zero = dict(rms=0.0, p95=0.0, maximum=0.0)
    optimizer = dict(
        template=zero, subjects={"a": zero, "b": zero}, velocity_relative={"a": 0.0, "b": 0.0}
    )
    return (
        optimizer,
        {"10->19": {"a": dict(zero), "b": dict(zero)}},
        {"a": dict(zero), "b": dict(zero)},
    )


@pytest.mark.parametrize(
    "gate", ["optimizer", "geometry", "velocity", "integration", "roundtrip", "invalid"]
)
def test_each_gate_blocks_independently_including_one_bad_specimen(gate):
    optimizer, integration, roundtrip = _evidence()
    if gate == "geometry":
        optimizer["subjects"]["b"] = dict(rms=0.006)
    if gate == "velocity":
        optimizer["velocity_relative"]["b"] = 0.011
    if gate == "integration":
        integration["10->19"]["b"]["maximum"] = 0.021
    if gate == "roundtrip":
        roundtrip["b"]["maximum"] = 0.001
    failures = qualification.failed_gates(
        optimizer,
        integration,
        roundtrip,
        converged=gate != "optimizer",
        objective_relative=0,
        valid_geometry=gate != "invalid",
    )
    assert failures


def test_converged_geometry_does_not_hide_objective_drift():
    a, b, c = _evidence()
    assert qualification.failed_gates(a, b, c, converged=True, objective_relative=0.011)
    assert not qualification.failed_gates(a, b, c, converged=True, objective_relative=0.001)


def _stub(monkeypatch):
    from test_reference_adaptive_calibration import seed_stub

    def bind(snapshot, identifier, destination):
        seed = seed_stub(snapshot, identifier, destination)
        c = next(c for c in snapshot.candidates if c.candidate_id == identifier)
        run = study.calibration_candidate_run_directory(c)
        seed.update(
            source_manifest_sha256=sha256_file(run / "manifest.json"), source_run_directory=str(run)
        )
        return seed

    monkeypatch.setattr(qualification, "bind_learned_seed", bind)


def test_prospective_checkpoint_preserves_source_and_does_not_run_old_grid(tmp_path, monkeypatch):
    runner, fourth = _fourth(tmp_path, monkeypatch)
    _stub(monkeypatch)
    prepared, identifier = qualification.prepare(fourth)
    assert prepared.current_stage.order == 4
    assert not prepared.integration_tolerances
    events = study._load_events(prepared.study_directory)
    assert qualification.declarations(events)[-1]["criteria"] == qualification.CRITERIA
    done = runner.run_current_stage(candidate_ids={identifier})
    new = next(c for c in done.candidates if c.candidate_id == identifier)
    assert new.status == "completed"
    assert new.candidate_id not in done.visual_reviews  # Previous anatomy approval never transfers.
    assert all(
        c.attempts == 0 for c in done.candidates if c.candidate_id.startswith("timepoints-0")
    )
    assert all(
        c.metrics == prepared.candidates[i].metrics for i, c in enumerate(done.candidates[:-1])
    )
    assert (
        study.load_reference_calibration_study(done.study_directory).candidates == done.candidates
    )
    with pytest.raises(ValueError):
        new.config_path.write_text(
            new.config_path.read_text().replace("convergence_tolerance:", "wrong_tolerance:")
        )
        study.load_reference_calibration_study(done.study_directory)


def test_fixed_vertex_comparison_rejects_changed_topology_and_measures_tail(tmp_path):
    from pathlib import Path

    source = Path(__file__).parents[1] / "examples/synthetic/meshes/template.vtk"
    assert movement(source, source, 1) == dict(rms=0, p95=0, maximum=0)
    changed = tmp_path / "changed.vtk"
    from diffeoforge.mesh import read_vtk_polydata, write_vtk_polydata

    mesh = read_vtk_polydata(source)
    triangles = list(mesh.triangles)
    a, b, c = triangles[0]
    triangles[0] = (a, c, b)
    write_vtk_polydata(changed, mesh.vertices, triangles)
    with pytest.raises(ValueError, match="topology"):
        movement(source, changed, 1)


def test_one_checkpoint_needs_human_review_and_cannot_select_legacy_refits(tmp_path, monkeypatch):
    runner, fourth = _fourth(tmp_path, monkeypatch)
    _stub(monkeypatch)
    prepared, identifier = qualification.prepare(fourth)
    done = runner.run_current_stage(candidate_ids={identifier})
    study._append_event(done.study_directory, "stage_awaiting_review", dict(stage_id="timepoints"))
    done = study.load_reference_calibration_study(done.study_directory)
    assessment = study.assess_reference_calibration_snapshot(done)
    assert assessment.version == qualification.VERSION
    assert assessment.balanced_candidate_id is None
    assert all(not c.eligible for c in assessment.candidates)
    assert (
        study.load_reference_calibration_study(done.study_directory).visual_reviews.get(identifier)
        is None
    )


def _complete_check(tmp_path, monkeypatch):
    import shutil

    from test_reference_calibration_study import _approve_for_test

    runner, fourth = _fourth(tmp_path, monkeypatch)
    _stub(monkeypatch)
    template = next((fourth.study_directory / "inputs/template").glob("*.vtk"))
    names = [s.filename for s in fourth.plan.selected_pilot_subjects]
    row = dict(rms=0.0, p95=0.0, maximum=0.0)
    optimizer = dict(
        template=row, subjects={n: row for n in names}, velocity_relative={n: 0.0 for n in names}
    )
    monkeypatch.setattr(qualification, "optimizer_check", lambda *a: optimizer)
    monkeypatch.setattr(
        qualification, "_reconstructions", lambda r: (None, {n: template for n in names})
    )
    counts = []

    def shoot(config, seed_root, seed, destination, count, **kwargs):
        counts.append(count)
        destination.mkdir(parents=True)
        paths = {}
        for n in names:
            p = destination / n
            shutil.copyfile(template, p)
            paths[n] = p
        return paths, {}

    monkeypatch.setattr(qualification, "shoot", shoot)
    done = qualification.run(runner)
    return runner, done, counts, _approve_for_test


def test_complete_check_requires_fresh_qc_and_exports_exact_receipt(tmp_path, monkeypatch):
    runner, done, counts, approve = _complete_check(tmp_path, monkeypatch)
    new = done.candidates[-1]
    n = int(done.current_stage.candidates[-1].values["timepoints"])
    assert counts == [n, 2 * n - 1, 4 * n - 3]
    assert not study.assess_reference_calibration_snapshot(done).balanced_candidate_id
    approve(done.study_directory, new.candidate_id)
    done = study.load_reference_calibration_study(done.study_directory)
    assessed = study.assess_reference_calibration_snapshot(done)
    assert assessed.balanced_candidate_id == new.candidate_id
    assert not assessed.automatic_selection_allowed
    audit = qualification.export_audit(done.study_directory, tmp_path / "audit.json")
    assert audit.is_file()
    result, assessment = study.record_reference_calibration_stage_review(
        done.study_directory, selected_candidate_id=new.candidate_id, visual_approvals={}
    )
    assert result.status == "completed"
    report = study.load_reference_calibration_report(result.study_directory)
    assert report["numerical_qualification"][0]["numerical_pass"]
    assert report["full_cohort_confirmation_required"]
    assert study.load_reference_calibration_study(result.study_directory).status == "completed"
    import json

    completed_audit = qualification.export_audit(
        result.study_directory, tmp_path / "completed-audit.json"
    )
    assert json.loads(completed_audit.read_text())["qualification"][new.candidate_id][
        "numerical_pass"
    ]
    assert "Independent numerical qualification" in result.report_html_path.read_text(
        encoding="utf-8"
    )
    receipt = qualification.verified_receipts(done)[new.candidate_id]
    path = done.study_directory / next(iter(receipt["artifacts"]))
    path.write_bytes(path.read_bytes() + b"\n ")
    with pytest.raises(ValueError, match="changed"):
        study.load_reference_calibration_study(result.study_directory)


def test_artifact_tampering_blocks_qualified_selection(tmp_path, monkeypatch):
    _, done, _, approve = _complete_check(tmp_path, monkeypatch)
    approve(done.study_directory, done.candidates[-1].candidate_id)
    done = study.load_reference_calibration_study(done.study_directory)
    receipt = qualification.verified_receipts(done)[done.candidates[-1].candidate_id]
    path = done.study_directory / next(iter(receipt["artifacts"]))
    path.write_bytes(path.read_bytes() + b"\n ")
    with pytest.raises(ValueError, match="changed"):
        study.assess_reference_calibration_snapshot(done)


def test_notification_deduplicates_without_forcing_focus_and_keeps_iteration(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    runner, fourth = _fourth(tmp_path, monkeypatch)
    done = runner.run_current_stage()
    monkeypatch.setattr(
        study,
        "atlas_rms_distance",
        lambda *a: (_ for _ in ()).throw(
            AssertionError("UI must not refit-compare legacy atlases")
        ),
    )
    dialog = ReferenceCalibrationDialog(done.study_directory)
    calls = []
    monkeypatch.setattr(QApplication, "alert", lambda *a: calls.append(a))
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    dialog.showMinimized()
    dialog._notify_review_ready()
    dialog._notify_review_ready()
    assert len(calls) == 1
    assert dialog.isMinimized()
    from dataclasses import replace

    dialog._snapshot = replace(
        done,
        status="ready",
        early_screening=dict(current_status="completed", complete=False, current_child="probe"),
    )
    dialog._notify_review_ready()
    dialog._notify_review_ready()
    assert len(calls) == 2
    identifier = done.candidates[0].candidate_id
    dialog._event(dict(event="candidate_started", candidate_id=identifier))
    dialog._event(
        dict(
            event="candidate_worker_event",
            candidate_id=identifier,
            worker_event=dict(kind="progress", payload=dict(iteration=12, maximum_iterations=300)),
        )
    )
    dialog._event(
        dict(
            event="candidate_worker_event",
            candidate_id=identifier,
            worker_event=dict(kind="activity", payload=dict(elapsed_seconds=120)),
        )
    )
    assert "12 / 300" in dialog.status.text() and "2.0 min" in dialog.status.text()
    dialog.close()
    app.processEvents()


def test_finer_refit_preserves_source_but_does_not_claim_qualification(tmp_path, monkeypatch):
    runner, fourth = _fourth(tmp_path, monkeypatch)
    _stub(monkeypatch)
    done = qualification.run(runner, finer_model=True)
    declarations = qualification.declarations(study._load_events(done.study_directory))
    assert len(declarations) == 1
    declaration = declarations[0]
    assert declaration["refinement_timepoints"] == (
        2 * declaration["continuation_seed"]["model"]["deformation"]["timepoints"] - 1
    )
    assert not qualification.verified_receipts(done)
    assert not study.assess_reference_calibration_snapshot(done).balanced_candidate_id
    assert done.candidates[-1].status == "completed"
    assert done.visual_reviews.get(done.candidates[-1].candidate_id) is None
    assert study.load_reference_calibration_study(done.study_directory).status == "awaiting_review"


def test_nonfinite_measurement_fails_closed():
    optimizer, integration, roundtrip = _evidence()
    integration["10->19"]["b"]["maximum"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        qualification.failed_gates(
            optimizer, integration, roundtrip, converged=True, objective_relative=0
        )


def test_audit_contains_individual_trials_approval_and_plan_b(tmp_path, monkeypatch):
    import json

    from test_reference_calibration_study import _approve_for_test, _review_ready_stage
    from test_reference_sequential_fit import _measured

    from diffeoforge import reference_fit_search as search
    from diffeoforge import reference_sequential_fit as sequence

    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    cid = first.candidates[0].candidate_id
    _approve_for_test(first.study_directory, cid)
    second = sequence.run_specimen_sequence(runner, action=("advance", cid, 0))
    later = sequence.run_specimen_sequence(runner, action=("maybe", cid, 0))
    path = qualification.export_audit(later.study_directory, tmp_path / "sequence-audit.json")
    audit = json.loads(path.read_text(encoding="utf-8"))
    state = audit["specimen_sequence"]
    assert len(state["approved"]) == 1
    assert state["fallbacks"]["1"]["study"] == second.study_directory.name
    assert len(audit["individual_trials"]) == len(state["trials"]) >= 3
    assert audit["specimen_sequence_source"]["events"]
    assert any(
        e["event"] == "candidate_visual_review"
        for trial in audit["individual_trials"]
        for e in trial["events"] + trial["reviews"]
    )


def test_optimizer_compares_physical_fields_on_common_probes(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    import numpy as np

    template = Path(__file__).parents[1] / "examples/synthetic/meshes/template.vtk"
    names = ("a", "b")
    controls = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    momenta = np.array(
        [[[0.01, 0.02, 0.0], [0.03, 0.01, 0.0]], [[0.01, 0.0, 0.01], [0.0, 0.01, 0.02]]]
    )
    report = SimpleNamespace(
        manifest=dict(effective_config=dict(model=dict(deformation=dict(kernel_width=1.0))))
    )
    before = SimpleNamespace(
        subject_labels=names, control_points=controls, momenta=momenta, run_report=report
    )
    after = SimpleNamespace(
        subject_labels=names,
        control_points=controls[::-1],
        momenta=momenta[:, ::-1],
        run_report=report,
    )
    monkeypatch.setattr(
        qualification,
        "_reconstructions",
        lambda r: (before if r == "before" else after, {n: template for n in names}),
    )
    monkeypatch.setattr(
        "diffeoforge.reference_holdout_study._trained_model_artifacts", lambda r: (template,)
    )
    result = qualification.optimizer_check("before", "after", dict(a=1.0, b=1.0), 1.0)
    assert max(result["velocity_relative"].values()) < 1e-12
    after.momenta = after.momenta * 2
    changed = qualification.optimizer_check("before", "after", dict(a=1.0, b=1.0), 1.0)
    assert all(abs(v - 1.0) < 1e-12 for v in changed["velocity_relative"].values())

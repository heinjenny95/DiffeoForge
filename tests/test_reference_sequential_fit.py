from pathlib import Path

import numpy as np
import pytest
from test_reference_calibration_study import _approve_for_test, _review_ready_stage

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_fit_search as search
from diffeoforge import reference_sequential_fit as sequence
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import ReferencePCAError, read_deformetrica_momenta


def _measured(root, manifest, candidate, run):
    return dict(
        original_surface_fit={
            r["filename"]: dict(p95=0.1, p99=0.2, mean=0.05, diagonal=1)
            for r in manifest["inputs"]["subjects"]
        },
        fit_scope="full_targets"
        if candidate.candidate_id in manifest["fit_search"]["confirmation_ids"]
        else "screening",
    )


def _reject(snapshot):
    candidate = snapshot.candidates[0]
    names = tuple(s.filename for s in snapshot.plan.selected_pilot_subjects)
    study.record_reference_calibration_candidate_review(
        snapshot.study_directory,
        candidate_id=candidate.candidate_id,
        approved=False,
        reviewed_subjects=names,
        subject_decisions={n: "fail" for n in names},
        display_scopes={n: "preview" for n in names},
    )
    return candidate.candidate_id


def test_rejection_runs_one_new_setting_for_same_animal_preserving_common_basis(
    tmp_path, monkeypatch
):
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    candidate_id = _reject(first)
    root = Path(sequence.sequence_info(first.study_directory)["root"])
    budget = root / "fit-search-budget.json"
    study._write_json(budget, dict(limit_seconds=900, spent_seconds=900), overwrite=False)
    before = budget.read_bytes()
    alternative = sequence.run_specimen_sequence(runner, action=("reject", candidate_id, 0))
    assert len(alternative.candidates) == 1 and alternative.candidates[0].attempts == 1
    assert sequence.sequence_info(alternative.study_directory)["index"] == 0
    assert sequence._values(alternative, candidate_id) != sequence._values(first, candidate_id)
    assert (
        study.load_reference_calibration_study(first.study_directory).visual_reviews[candidate_id]
        is False
    )
    assert budget.read_bytes() == before
    with pytest.raises(ValueError, match="no longer current"):
        sequence.run_specimen_sequence(
            study.ReferenceCalibrationStudyRunner(first.study_directory),
            action=("reject", candidate_id, 0),
        )
    _approve_for_test(alternative.study_directory, candidate_id)
    second = sequence.run_specimen_sequence(runner, action=("advance", candidate_id, 0))
    cid = _reject(second)
    retry = sequence.run_specimen_sequence(runner, action=("reject", cid, 0))
    assert sequence.sequence_info(retry.study_directory)["index"] == 1
    assert sequence._values(retry, cid) != sequence._values(second, cid)
    assert sequence._basis(sequence._values(retry, cid)) == sequence._basis(
        sequence._values(alternative, candidate_id)
    )
    assert len(sequence._read(root)["approved"]) == 1
    _approve_for_test(retry.study_directory, cid)
    # A second approval with different matching weights remains a valid initializer.
    state = sequence._read(root)
    state["approved"].append(
        dict(
            study=retry.study_directory.relative_to(root).as_posix(),
            candidate_id=cid,
            run_sha256=sha256_file(
                study.calibration_candidate_run_directory(retry.candidates[0]) / "manifest.json"
            ),
        )
    )
    sequence._save(root, state)
    assert len(sequence._read(root)["approved"]) == 2


def test_rejection_inherits_exact_working_targets_without_native_repreparation(
    tmp_path, monkeypatch
):
    from diffeoforge import mesh_filter_worker

    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    root = Path(sequence.sequence_info(first.study_directory)["root"])
    parent = study._verify_manifest(root)
    cid = _reject(first)
    monkeypatch.setattr(mesh_filter_worker, "run_mesh_filter",
                        lambda *a, **k: pytest.fail("Repeated native reduction"))
    second = sequence.run_specimen_sequence(runner, action=("reject", cid, 0))
    manifest = study._verify_manifest(second.study_directory)
    assert manifest["fit_search"]["controls"] == parent["fit_search"]["controls"]
    expected = {r["filename"]: r for r in parent["fit_search"]["working_targets"]}
    for row in manifest["fit_search"]["working_targets"]:
        assert row == expected[row["filename"]]
        assert sha256_file(second.study_directory / row["copy"]) == row["sha256"]


def test_qc_dispatches_next_parameters_or_next_animal_and_ignores_stale_viewers(
    tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    dialog = ReferenceCalibrationDialog(first.study_directory)
    calls = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kw: calls.append(kw))
    cid = first.candidates[0].candidate_id
    dialog._continue_specimen_review(first.study_directory, cid, False)
    assert calls[-1]["specimen_action"] == ("reject", cid, 0)
    dialog._continue_specimen_review(first.study_directory, cid, True)
    assert calls[-1]["specimen_action"] == ("advance", cid, 0)
    dialog._continue_specimen_review(first.study_directory.parent, cid, False)
    assert len(calls) == 2
    dialog._worker = object()
    dialog._continue_specimen_review(first.study_directory, cid, False)
    assert len(calls) == 2
    dialog._succeeded(first)
    assert len(calls) == 3 and dialog._pending_specimen_review is None
    dialog.close()
    app.processEvents()


def test_early_pause_approval_guard_next_only_and_resume(tmp_path, monkeypatch):
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    info = sequence.sequence_info(first.study_directory)
    assert info["index"] == 0 and info["total"] == original.plan.pilot_subject_count
    assert len(first.candidates) == 1 and first.candidates[0].attempts == 1
    for candidate in first.candidates:
        config = load_config(candidate.config_path)
        assert len(validate_input_paths(config, candidate.config_path).subjects) == 1
        assert config["optimization"]["freeze_template"]
        assert config["optimization"]["freeze_control_points"]
    current = first.candidates[0].candidate_id
    with pytest.raises(ValueError, match="Approve this specimen"):
        sequence.run_specimen_sequence(runner, action=("advance", current, 0))
    assert not sequence._read(Path(info["root"]))["approved"]
    reopened = sequence.run_specimen_sequence(runner)
    assert [c.attempts for c in reopened.candidates] == [c.attempts for c in first.candidates]
    assert (
        study.latest_reference_calibration_search_extension_directory(original.study_directory)
        == first.study_directory
    )
    _approve_for_test(first.study_directory, current)
    second = sequence.run_specimen_sequence(runner, action=("advance", current, 0))
    assert sequence.sequence_info(second.study_directory)["index"] == 1
    assert len(second.candidates) == 1 and not second.visual_reviews
    assert sequence._values(second, second.candidates[0].candidate_id) == sequence._values(
        first, current
    )
    assert sequence.resume_directory(first.study_directory) == second.study_directory
    assert first.study_directory.exists()


def test_legacy_sequence_resumes_approved_fits_with_exhausted_budget(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    create = study.create_reference_calibration_study

    def legacy_create(*args, **kwargs):
        settings = kwargs["fit_search"]
        settings["minutes"] = 15
        if settings.get("sequence"):
            settings["sequence"]["minutes"] = 15
        return create(*args, **kwargs)

    monkeypatch.setattr(study, "create_reference_calibration_study", legacy_create)
    first = sequence.run_specimen_sequence(runner)
    cid = first.candidates[0].candidate_id
    _approve_for_test(first.study_directory, cid)
    second = sequence.run_specimen_sequence(runner, action=("advance", cid, 0))
    _approve_for_test(second.study_directory, cid)
    root = Path(sequence.sequence_info(second.study_directory)["root"])
    study._write_json(root / "fit-search-budget.json",
                      dict(limit_seconds=900, spent_seconds=900), overwrite=False)
    before = {p: sha256_file(p) for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(study, "create_reference_calibration_study", create)
    assert sequence.resume_directory(original.study_directory) == second.study_directory
    reopened = sequence.run_specimen_sequence(runner)
    assert reopened.visual_reviews[cid] is True
    assert reopened.candidates[0].attempts == second.candidates[0].attempts
    assert len(sequence._read(root)["approved"]) == 1
    assert {p: sha256_file(p) for p in root.rglob("*") if p.is_file()} == before
    dialog = ReferenceCalibrationDialog(reopened.study_directory)
    assert not hasattr(dialog, "fit_minutes")
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(cid))
    assert dialog.advance_button.isEnabled()
    starts = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **k: starts.append(k))
    dialog.advance_button.click()
    assert starts[0]["specimen_action"] == ("advance", cid, 0)
    dialog.close()
    app.processEvents()


def test_rejection_and_longer_fit_stay_on_same_specimen(tmp_path, monkeypatch):
    from test_reference_progressive_fit import mock_singleton

    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    candidate = first.candidates[0]
    mock_singleton(monkeypatch, first)
    study.record_reference_calibration_candidate_review(
        first.study_directory,
        candidate_id=candidate.candidate_id,
        approved=False,
        subject_decisions={s.filename: "fail" for s in first.plan.selected_pilot_subjects},
        reviewed_subjects=tuple(s.filename for s in first.plan.selected_pilot_subjects),
        display_scopes={s.filename: "preview" for s in first.plan.selected_pilot_subjects},
    )
    with pytest.raises(ValueError, match="Approve this specimen"):
        sequence.run_specimen_sequence(runner, action=("advance", candidate.candidate_id, 0))
    retry = sequence.run_specimen_sequence(runner, action=("retry", candidate.candidate_id, 80))
    config = load_config(retry.candidates[0].config_path)
    assert config["optimization"]["max_iterations"] == 80
    assert config["model"]["deformation"].get("initial_momenta")
    assert sequence.sequence_info(retry.study_directory)["index"] == 0
    assert not retry.visual_reviews


def test_every_approval_precedes_joint_confirmation_and_fresh_qc(tmp_path, monkeypatch):
    from diffeoforge.reference_pca_deformations import _write_momenta

    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)

    def seed(root, state):
        parent = study._verify_manifest(root)
        values = np.zeros((len(state["order"]), parent["fit_search"]["controls"]["count"], 3))
        file = root / "joint-test-seed.txt"
        _write_momenta(file, values)
        return dict(
            path=str(file),
            sha256=sha256_file(file),
            subject_labels=sorted(state["order"], key=Path),
        )

    monkeypatch.setattr(sequence, "_joint_seed", seed)
    snapshot = sequence.run_specimen_sequence(runner)
    for index in range(original.plan.pilot_subject_count):
        assert sequence.sequence_info(snapshot.study_directory)["index"] == index
        candidate_id = snapshot.candidates[0].candidate_id
        _approve_for_test(snapshot.study_directory, candidate_id)
        snapshot = sequence.run_specimen_sequence(runner, action=("advance", candidate_id, 0))
    assert sequence.sequence_info(snapshot.study_directory)["phase"] == "joint"
    assert snapshot.plan.pilot_subject_count == original.plan.pilot_subject_count
    assert not snapshot.visual_reviews and not snapshot.selected_candidate_ids
    config = load_config(snapshot.candidates[0].config_path)
    assert not config["optimization"]["freeze_template"]
    assert not config["optimization"]["freeze_control_points"]
    assert "working-targets" not in config["input"]["directory"]
    assert config["model"]["deformation"]["initial_momenta"]
    assert snapshot.candidates[0].metrics["fit_scope"] == "full_targets"
    root = Path(sequence.sequence_info(snapshot.study_directory)["root"])
    assert not (root / "fit-search-budget.json").exists()
    assert not (snapshot.study_directory / "fit-search-budget.json").exists()
    # Joint continuation must retain newly learned fields, not restore individual starts.
    from test_reference_adaptive_calibration import seed_stub

    from diffeoforge import reference_adaptive_calibration as adaptive

    monkeypatch.setattr(adaptive, "bind_learned_seed", seed_stub)
    successor = adaptive.create_selected_continuation(
        snapshot.study_directory,
        study.next_reference_calibration_search_extension_destination(snapshot.study_directory),
        candidate_id=snapshot.candidates[0].candidate_id,
        iterations=300,
    )
    config = load_config(successor.candidates[-1].config_path)
    assert "working-targets" not in config["input"]["directory"]
    assert "adaptive-seed" in config["model"]["deformation"]["initial_momenta"]
    assert "adaptive-seed" in config["model"]["deformation"]["initial_control_points"]
    assert config["optimization"]["max_iterations"] == 300


def test_singleton_field_import_does_not_enable_singleton_pca(tmp_path):
    file = tmp_path / "momenta.txt"
    file.write_text("1 2 3\n\n1 2 3\n4 5 6\n")
    with pytest.raises(ReferencePCAError, match="at least two"):
        read_deformetrica_momenta(file)
    values = read_deformetrica_momenta(file, allow_singleton=True)
    assert values.shape == (1, 2, 3)
    np.testing.assert_array_equal(values[0, 1], [4, 5, 6])


def test_explicit_new_search_preserves_old_budget_and_restarts_complete_cohort(
    tmp_path, monkeypatch
):
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    candidate_id = first.candidates[0].candidate_id
    _approve_for_test(first.study_directory, candidate_id)
    second = sequence.run_specimen_sequence(runner, action=("advance", candidate_id, 0))
    previous_root = Path(sequence.sequence_info(second.study_directory)["root"])
    budget = previous_root / "fit-search-budget.json"
    study._write_json(budget, dict(limit_seconds=900, spent_seconds=900), overwrite=False)
    before = budget.read_bytes()
    restart = sequence.run_specimen_sequence(runner, action=("restart", "", 0))
    info = sequence.sequence_info(restart.study_directory)
    assert info["index"] == 0 and info["total"] == original.plan.pilot_subject_count
    assert "minutes" not in info
    assert Path(info["root"]) != previous_root
    assert budget.read_bytes() == before
    assert second.study_directory.exists() and not restart.visual_reviews
    assert sequence.resume_directory(original.study_directory) == restart.study_directory


def test_individual_qc_advances_even_if_iteration_cap_is_reached(tmp_path, monkeypatch):
    from dataclasses import replace

    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    collect = study.collect_reference_calibration_run_metrics
    monkeypatch.setattr(
        study,
        "collect_reference_calibration_run_metrics",
        lambda p: replace(collect(p), converged=False, optimizer_stop_signal="maximum_iterations"),
    )
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    candidate_id = first.candidates[0].candidate_id
    dialog = ReferenceCalibrationDialog(first.study_directory)
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(candidate_id))
    assert not dialog.advance_button.isEnabled()
    _approve_for_test(first.study_directory, candidate_id)
    dialog._render()
    dialog.selection_combo.setCurrentIndex(dialog.selection_combo.findData(candidate_id))
    assert dialog.advance_button.text() == "Fit next specimen →"
    assert dialog.advance_button.isEnabled()
    called = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kwargs: called.append(kwargs))
    dialog.advance_button.click()
    assert called[0]["specimen_action"] == ("advance", candidate_id, 0)
    dialog.close()
    app.processEvents()


def test_singleton_input_requires_explicit_fixed_probe_scope(tmp_path, monkeypatch):
    from diffeoforge.config import ConfigurationError

    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    candidate = first.candidates[0]
    config = load_config(candidate.config_path)
    config["optimization"]["freeze_template"] = False
    with pytest.raises(ConfigurationError, match="at least two"):
        validate_input_paths(config, candidate.config_path)


def test_joint_seed_orders_fields_and_refuses_another_control_basis(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from diffeoforge import reference_pca
    from diffeoforge.reference_pca_deformations import _write_momenta

    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    actual_seed = sequence._joint_seed

    def fixture_seed(root, state):
        file = root / "joint-fixture.txt"
        count = study._verify_manifest(root)["fit_search"]["controls"]["count"]
        _write_momenta(file, np.zeros((len(state["order"]), count, 3)))
        return dict(
            path=str(file),
            sha256=sha256_file(file),
            subject_labels=sorted(state["order"], key=Path),
        )

    monkeypatch.setattr(sequence, "_joint_seed", fixture_seed)
    snapshot = sequence.run_specimen_sequence(runner)
    for _ in range(original.plan.pilot_subject_count):
        candidate_id = snapshot.candidates[0].candidate_id
        _approve_for_test(snapshot.study_directory, candidate_id)
        snapshot = sequence.run_specimen_sequence(runner, action=("advance", candidate_id, 0))
    root = Path(sequence.sequence_info(snapshot.study_directory)["root"])
    state = sequence._read(root)
    controls = np.loadtxt(root / study._verify_manifest(root)["fit_search"]["controls"]["copy"])
    lookup = {}
    for i, record in enumerate(state["approved"], 1):
        child = study.load_reference_calibration_study(root / record["study"])
        candidate = next(c for c in child.candidates if c.candidate_id == record["candidate_id"])
        run = study.calibration_candidate_run_directory(candidate)
        momenta = run / "fixture-momenta.txt"
        _write_momenta(momenta, np.full((1, len(controls), 3), float(i)))
        lookup[run] = SimpleNamespace(
            subject_labels=(sequence.sequence_info(child.study_directory)["filename"],),
            momenta=np.full((1, len(controls), 3), float(i)),
            control_points=np.round(controls.copy(), 6),
            momenta_path=momenta,
            run_report=SimpleNamespace(
                manifest={"effective_config": load_config(candidate.config_path)}
            ),
        )
    monkeypatch.setattr(reference_pca, "load_reference_momenta", lambda run, **k: lookup[run])
    seed = actual_seed(root, state)
    observed = read_deformetrica_momenta(seed["path"])
    order = {value.subject_labels[0]: value.momenta[0] for value in lookup.values()}
    np.testing.assert_array_equal(observed, np.stack([order[n] for n in seed["subject_labels"]]))
    next(iter(lookup.values())).control_points[0, 0] += 1
    with pytest.raises(ValueError, match="control basis"):
        actual_seed(root, state)

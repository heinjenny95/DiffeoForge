import ast
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import pytest
import yaml
from test_runs import _execute_cap_fixture, write_run_config

from diffeoforge import _atlas_distance_metric
from diffeoforge import reference_morphospace_stopping as stopping
from diffeoforge.analysis.shape_space import lddmm_momenta_squared_distances
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_atlas_stop import (
    MORPHOSPACE_STABILITY,
    OPTIMIZER_CONVERGENCE,
    stop_policy,
)
from diffeoforge.reference_morphospace_native import REPORT_NAME, manifest_subject_labels
from diffeoforge.reference_morphospace_stopping import (
    compare_distances,
    distance_matrix,
    metric_source,
    read_morphospace_stability,
)
from diffeoforge.result_report import collect_run_report
from diffeoforge.runs import _append_event, _inventory_outputs, _read_manifest, prepare_run


def test_one_of_one_hundred_specimens_blocks_automatic_stability():
    labels = tuple(f"specimen-{index}" for index in range(100))
    control_points = np.zeros((1, 3))
    momenta = np.zeros((100, 1, 3))
    momenta[:, 0, 0] = np.linspace(0, 10, 100)
    baseline = distance_matrix(momenta, control_points, 1.0)
    momenta[-1, 0, 0] += 0.03 * np.linalg.norm(baseline[-1]) / np.sqrt(99)
    candidate = distance_matrix(momenta, control_points, 1.0)
    change = compare_distances(baseline, candidate, labels)
    assert change["cohort_percent"] < 1.0
    assert sum(value < 2.0 for value in change["subject_percent"]) == 99
    assert change["max_subject_percent"] == pytest.approx(3.0)
    assert change["worst_subjects"] == ["specimen-99"]
    assert change["stable"] is False


def test_scale_changes_survive_and_require_both_strict_thresholds():
    matrix = np.array([[0, 100], [100, 0]], dtype=np.uint64)
    labels = ("a", "b")
    for percent_evidence, stable in ((0.5, True), (1.0, False), (1.5, False)):
        candidate = np.array([[0, 100 - percent_evidence], [100 - percent_evidence, 0]])
        change = compare_distances(matrix, candidate, labels)
        assert change["stable"] is stable
        assert change["cohort_percent"] == pytest.approx(percent_evidence)
        assert change["max_subject_percent"] == pytest.approx(percent_evidence)
        assert change["worst_subjects"] == list(labels)


@pytest.mark.parametrize("invalid", [
    np.zeros((3, 3)),
    np.array([[0, 0, 0], [0, 0, 1], [0, 1, 0]]),
    np.array([[0, 1, 1], [1, 0, np.inf], [1, np.inf, 0]]),
    np.array([[0, 1, 1], [1, 0, 4], [1, 3, 0]]),
    np.full((3, 3), "garbage"),
])
def test_degenerate_or_invalid_distance_evidence_is_unavailable(invalid):
    usable = np.ones((3, 3)) - np.eye(3)
    for previous, current in ((invalid, usable), (usable, invalid)):
        change = compare_distances(previous, current, ("a", "b", "c"))
        assert change["status"] == "unavailable"
        assert change["stable"] is False
    assert compare_distances(usable, usable, ("a", "a", "c"))["status"] == "unavailable"


def test_native_python38_source_and_analyzer_measure_same_lddmm_distances():
    namespace = {}
    source = ast.parse(metric_source(), feature_version=(3, 8))
    exec(compile(source, "<native atlas metric>", "exec"), namespace)
    momenta = np.zeros((3, 2, 3), dtype=np.float32)
    momenta[0, :, 0] = (1.5, 3.0)
    momenta[1, :, 1] = (4.0, 0.7)
    controls = np.array([[0, 0, 0], [0, 0, 2]], dtype=np.float64)
    archived = namespace["distance_matrix"](momenta, controls, 0.5)
    expected = np.sqrt(lddmm_momenta_squared_distances(
        momenta.astype(np.float64), controls, deformation_kernel_width=0.5,
    ))
    np.testing.assert_array_equal(archived, expected)
    moved_basis = distance_matrix(momenta, controls + 10.0, 0.5)
    np.testing.assert_array_equal(moved_basis, archived)
    updated_basis = distance_matrix(momenta, controls / 10.0, 0.5)
    assert not np.allclose(updated_basis, archived)
    assert namespace["compare_distances"](archived, updated_basis, ("a", "b", "c")) == (
        compare_distances(archived, updated_basis, ("a", "b", "c"))
    )


def test_large_diagnostic_uses_bounded_blocks_without_changing_the_metric(monkeypatch):
    values = np.random.default_rng(57)
    momenta = values.normal(size=(8, 18, 3))
    controls = values.uniform(size=(18, 3))
    width = 0.76
    baseline = distance_matrix(momenta, controls, width)
    monkeypatch.setattr(_atlas_distance_metric, "_MAX_DIAGNOSTIC_KERNEL_ELEMENTS", 18 * 4)

    def unexpected_dense_kernel(*_args):
        pytest.fail("Large in-run observations must use bounded workspace")

    monkeypatch.setattr(
        _atlas_distance_metric, "gaussian_control_point_kernel", unexpected_dense_kernel,
    )
    actual = distance_matrix(momenta, controls, width)
    np.testing.assert_allclose(actual, baseline, rtol=5e-15, atol=1e-15)
    np.testing.assert_array_equal(actual, actual.T)


def _retained_report(
    tmp_path, *, interrupted=False, full_window=None, reason=None, unlimited=False,
):
    configuration_path = write_run_config(tmp_path)
    config = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    mode = OPTIMIZER_CONVERGENCE if full_window is None else MORPHOSPACE_STABILITY
    policy = stop_policy(mode, unlimited_iterations=unlimited)
    config["project"]["atlas_stop"] = policy
    config["output"]["checkpoint_mode"] = "compact_final_export"
    end = 2 if full_window is None else 400
    config["optimization"]["max_iterations"] = 2 if unlimited else end
    configuration_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    run = prepare_run(configuration_path, run_id="native-report")
    assert read_morphospace_stability(run) is None
    output = run / "output"
    (output / "morphospace-checkpoints").mkdir()
    labels = list(manifest_subject_labels(_read_manifest(run)))
    positions = np.array([[0.0, 0, 0]])
    momenta = np.array([[[0.0, 0, 0]], [[1.0, 0, 0]]])
    if full_window is None:
        points = [(0, 1.0), (2, 1.03)]
    else:
        points = [(step, 1.0 if step < 200 else 1.015) for step in range(0, 400, 25)]
        points.append((400, 1.0075 if full_window else 1.015))
    snapshots, observations = {}, []

    def window(requested, iteration, distances):
        previous = min((index for index in snapshots if index >= iteration - requested),
                       default=None)
        basis, old = snapshots.get(previous, (None, None))
        span = 0 if previous is None else iteration - previous
        change = compare_distances(old, distances, labels)
        change["stable"] = change["stable"] and span == requested
        return dict(previous_iteration=previous, previous_checkpoint=basis,
                    window_iterations=span, **change)

    for iteration, scale in points:
        relative = f"morphospace-checkpoints/iteration-{iteration}.npz"
        np.savez(output / relative, momenta=momenta * scale, control_points=positions)
        checkpoint = {"path": relative, "sha256": sha256_file(output / relative)}
        distances = distance_matrix(momenta * scale, positions, 0.1)

        observations.append(dict(iteration=iteration, checkpoint=checkpoint, objective=-19.0,
                                 weighted_fit_error=16.0,
                                 long_window=window(400, iteration, distances),
                                 **window(200, iteration, distances)))
        snapshots[iteration] = checkpoint, distances
    terminal_path = output / "deformetrica-state.p"
    terminal = None
    if not interrupted:
        terminal_path.write_bytes(b"retained state bytes; the reader must never unpickle")
        terminal = {"reason": reason or "native_tolerance", "iteration": end,
                    "checkpoint_sha256": sha256_file(terminal_path), "export": "complete"}
    report = {
        "version": 1, "policy": policy, "subject_labels": labels, "deformation_kernel_width": 0.1,
        "joint_origin_iteration": 0, "observations": observations, "terminal": terminal,
    }
    (output / REPORT_NAME).write_text(json.dumps(report), encoding="utf-8")
    status = "interrupted" if interrupted else "completed"
    result = {"run_id": "native-report", "status": status, "outputs": _inventory_outputs(run),
              "convergence_rows": 0}
    (run / "result.json").write_text(json.dumps(result), encoding="utf-8")
    _append_event(run / "events.jsonl", {"event": status})
    return run, report


def test_reopen_exact_saved_accepted_window_without_unpickling(tmp_path):
    run, report = _retained_report(tmp_path)
    before = {path: sha256_file(path) for path in run.rglob("*") if path.is_file()}
    assert read_morphospace_stability(run) == report
    assert {path: sha256_file(path) for path in run.rglob("*") if path.is_file()} == before


def test_cap_prepares_reviewable_successor_with_exact_joint_origin(tmp_path, monkeypatch):
    from diffeoforge.runs import prepare_resume_run, verify_prepared_run

    example, report = _retained_report(tmp_path, reason="iteration_limit")
    source = prepare_run(tmp_path / "atlas.yaml", run_id="completed")
    output = source / "output"
    files = {
        "output/" + path: (example / "output" / path).read_bytes()
        for path in (row["checkpoint"]["path"] for row in report["observations"])
    }
    exact = -123.76562309265137
    report["observations"][0]["objective"] = exact
    checkpoint = pickle.dumps({"current_iteration": 2})
    report["terminal"]["checkpoint_sha256"] = hashlib.sha256(checkpoint).hexdigest()
    files["output/" + REPORT_NAME] = json.dumps(report).encode()
    _execute_cap_fixture(source, monkeypatch, output_files=files, checkpoint=checkpoint)
    successor = prepare_resume_run(source, additional_iterations=300)
    manifest = verify_prepared_run(successor)
    config = manifest["effective_config"]
    assert config["optimization"]["max_iterations"] == 302
    assert config["output"]["checkpoint_mode"] == "compact_final_export"
    provenance = json.loads((successor / "resume/resume.json").read_text())
    assert provenance["convergence_reference"] == {
        "version": 1, "origin_iteration": 0, "initial_log_likelihood": exact,
        "origin_checkpoint_sha256": report["observations"][0]["checkpoint"]["sha256"],
        "convergence_tolerance": config["optimization"]["convergence_tolerance"],
    }
    assert "objective_baseline" in provenance["semantics"]["restored"]
    staged = prepare_resume_run(source, run_id="new-tolerance", optimizer_tolerance=1e-6,
                                iteration_limit=117)
    staged_receipt = json.loads((staged / "resume/resume.json").read_text())
    assert staged_receipt["convergence_reference"] == dict(
        provenance["convergence_reference"], convergence_tolerance=1e-6)
    assert staged_receipt["tolerance_continuation"]["source_reason"] == "iteration_limit"
    assert verify_prepared_run(staged)["effective_config"]["optimization"]["max_iterations"] == 117
    report["observations"][0]["objective"] += 1
    (output / REPORT_NAME).write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="terminal output inventory"):
        prepare_resume_run(source, run_id="changed-origin", additional_iterations=300)
    assert not (source.parent / "changed-origin").exists()


def test_reopen_reuses_run_review_that_already_verified_every_output(tmp_path, monkeypatch):
    run, saved = _retained_report(tmp_path)
    verified = collect_run_report(run)
    assert all(check.status == "pass" for check in verified.checks)

    def unexpected_rehash(_path):
        pytest.fail("Previously verified checkpoint bytes must not be rehashed")

    monkeypatch.setattr(stopping, "sha256_file", unexpected_rehash)
    assert read_morphospace_stability(run, verified_run_report=verified) == saved


def test_hard_interrupt_can_reopen_last_sealed_observation_without_native_terminal(tmp_path):
    run, report = _retained_report(tmp_path, interrupted=True)
    reopened = read_morphospace_stability(run)
    assert reopened == report and reopened["terminal"] is None
    assert reopened["observations"][-1]["iteration"] == 2


@pytest.mark.parametrize(("relative", "match"), [
    (Path("morphospace-checkpoints/iteration-2.npz"), "checksum mismatch"),
    (Path("deformetrica-state.p"), "checksum mismatch"),
    (Path(REPORT_NAME), "terminal output inventory"),
])
def test_reader_rejects_retained_evidence_changes(tmp_path, relative, match):
    run, _ = _retained_report(tmp_path)
    path = run / "output" / relative
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ConfigurationError, match=match):
        read_morphospace_stability(run)


def test_reader_refuses_short_window_claimed_as_stable(tmp_path):
    run, report = _retained_report(tmp_path)
    report["observations"][-1]["stable"] = True
    (run / "output" / REPORT_NAME).write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="inconsistent stability decision"):
        read_morphospace_stability(run)


def test_reader_verifies_the_independent_long_window_when_eligible(tmp_path):
    run, saved = _retained_report(tmp_path, full_window=True, reason="morphospace_stable")
    reopened = read_morphospace_stability(run)
    assert reopened == saved
    last = reopened["observations"][-1]
    assert last["window_iterations"] == 200 and last["stable"]
    assert last["long_window"]["window_iterations"] == 400 and last["long_window"]["stable"]


def test_reader_rejects_budget_stop_for_an_unbounded_atlas(tmp_path):
    run, _ = _retained_report(
        tmp_path, full_window=False, reason="iteration_limit", unlimited=True,
    )
    with pytest.raises(ConfigurationError, match="iteration limit for an uncapped atlas"):
        read_morphospace_stability(run)


def test_reader_refuses_short_only_automatic_stop_when_long_window_open(tmp_path):
    run, saved = _retained_report(tmp_path, full_window=False, reason="morphospace_stable")
    last = saved["observations"][-1]
    assert last["stable"] and not last["long_window"]["stable"]
    with pytest.raises(ConfigurationError, match="automatic stop over the longer window"):
        read_morphospace_stability(run)

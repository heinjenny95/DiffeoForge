"""Sealed synthetic receipts only; no optimizer, failed field or owner input."""

import json

import pytest
from test_failed_parent_recovery import terminal as terminal

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guard_failure as failure
from diffeoforge.mesh import sha256_file


@pytest.mark.parametrize("reason", ["inconsistent_FG_for_identical_parameters",
                                  "accepted_cost_regression", "unexpected_optimizer_thread"])
def test_bound_guard_stop_blocks_same_attempt_before_any_launch(terminal, reason):
    terminal.rewrite(reason)
    before = {p: sha256_file(p) for p in terminal.run.rglob("*") if p.is_file()}
    diagnostic = failure.read_failure(terminal.run)
    assert diagnostic["reason"] == reason and diagnostic["verified"]
    candidate = terminal.snapshot.candidates[0]
    with pytest.raises(study.ReferenceCalibrationStudyError, match="numerical safety check"):
        study._launch_request(terminal.run.parent, {}, candidate)
    assert before == {p: sha256_file(p) for p in terminal.run.rglob("*") if p.is_file()}


@pytest.mark.parametrize("name", ["violation.json", "events.jsonl"])
def test_changed_stop_evidence_never_qualifies_for_retry(terminal, name):
    (terminal.run / "output/numerical-guard" / name).write_text("changed")
    diagnostic = failure.for_candidate(terminal.snapshot.candidates[0])
    assert diagnostic["reason"] == "unverified_guard_failure"
    assert diagnostic["block_retry"] and not diagnostic["verified"]


def test_failed_field_coefficients_are_not_read(terminal, monkeypatch):
    from diffeoforge import regional_continuation, regional_evaluation

    monkeypatch.setattr(regional_continuation, "bundle", lambda *_: pytest.fail("Checkpoint read"))
    monkeypatch.setattr(regional_evaluation, "field_inputs", lambda *_: pytest.fail("Field read"))
    terminal.rewrite("inconsistent_FG_for_identical_parameters")
    diagnostic = failure.read_failure(terminal.run)
    assert "identical parameters" in diagnostic["message"]
    assert "adding iterations does not resolve" in diagnostic["message"]


@pytest.mark.parametrize("details, expected", [
    ({"native_iteration": 448, "evaluation_reference": 477}, 448),
    ({"attempted_native_iteration": 3}, 3), ({"native_iteration": True}, None), ({}, None),
])
def test_sealed_stop_explains_reason_and_only_verified_iteration(terminal, details, expected):
    terminal.rewrite("nonfinite_or_invalid_objective", details=details)
    diagnostic = failure.read_failure(terminal.run)
    assert "non-finite or invalid objective" in diagnostic["message"]
    assert diagnostic["native_iteration"] == expected
    if expected is None:
        assert "iteration " not in diagnostic["message"]
    else:
        assert f"at iteration {expected}." in diagnostic["message"]


@pytest.mark.parametrize("name", ["violation.json", "events.jsonl"])
def test_missing_sealed_stop_file_does_not_reenable_retry(terminal, name):
    (terminal.run / "output/numerical-guard" / name).unlink()
    diagnostic = failure.for_candidate(terminal.snapshot.candidates[0])
    assert diagnostic["block_retry"] and not diagnostic["verified"]


def test_completed_or_unguarded_runs_keep_their_existing_behavior(terminal):
    result = json.loads((terminal.run / "result.json").read_text())
    result["status"] = "completed"
    terminal.write(terminal.run / "result.json", result)
    assert failure.read_failure(terminal.run) is None
    terminal.manifest["effective_config"]["project"]["parameter_provenance"] = {}
    assert failure.read_failure(terminal.run) is None


def test_conflicting_terminal_event_cannot_authorize_retry(terminal):
    path = terminal.run / "output/numerical-guard/violation.json"
    data = json.loads(path.read_text())
    data["details"] = {"evaluation_reference": 7}
    terminal.write(path, data)
    inventory = json.loads((terminal.run / "output-inventory.json").read_text())
    for row in inventory["files"]:
        if row["path"].endswith("violation.json"):
            row.update(bytes=path.stat().st_size, sha256=sha256_file(path))
    terminal.write(terminal.run / "output-inventory.json", inventory)
    result = json.loads((terminal.run / "result.json").read_text())
    result["outputs"]["inventory_sha256"] = sha256_file(terminal.run / "output-inventory.json")
    terminal.write(terminal.run / "result.json", result)
    assert not failure.for_candidate(terminal.snapshot.candidates[0])["verified"]



def test_ordinary_singleton_receipt_also_blocks_repeating_numerical_stop(terminal):
    from diffeoforge.reference_ordinary_guard import DECLARATION

    terminal.manifest["effective_config"]["project"]["parameter_provenance"] = dict(
        finite_accepted_guard=DECLARATION)
    diagnostic = failure.read_failure(terminal.run)
    assert diagnostic["verified"] and diagnostic["block_retry"]
    assert diagnostic["reason"] == "accepted_cost_regression"

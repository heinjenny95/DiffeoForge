"""Read-only adaptive presentation against the real durable policy ledger.

The imported action fixture supplies synthetic numerical receipts and a normal
runner seam. It never starts a native worker or changes scientific inputs.
"""

from copy import deepcopy

import pytest
from test_pilot_adaptive_run import action as action

from diffeoforge import pilot_adaptive_fit as policy
from diffeoforge import pilot_adaptive_native as native
from diffeoforge import pilot_adaptive_run as adaptive
from diffeoforge import reference_calibration_study as study


def files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def reviews(action):
    return {
        str(path): deepcopy(snapshot.visual_reviews) for path, snapshot in action.states.items()
    }


def test_prepared_action_presents_zero_of600_without_reservation_or_mutation(action):
    first = adaptive.prepare(action.arguments)
    root = action.base.study_directory.parent
    before, decisions = files(root), reviews(action)
    result = adaptive.presentation(first)
    assert result["spent"] == result["held"] == 0
    assert result["total"] == 600 and result["stage_iterations"] == 100
    assert result["purpose"] == "warm" and not result["closed"]
    assert result["recommendation"] is None and result["requires_review"] is False
    assert not action.launches
    assert files(root) == before and reviews(action) == decisions
    state = policy.load_ledger(adaptive.marker(first.attachment_comparison)["ledger"])
    assert state.stages == () and state.remaining == 600


def test_completed_best_is_verified_read_only_and_is_not_a_human_preference(action):
    first = adaptive.prepare(action.arguments)
    final = adaptive.run(action.Runner(first.study_directory))
    root = action.base.study_directory.parent
    before, decisions = files(root), reviews(action)
    mark = adaptive.marker(final.attachment_comparison)
    state = policy.load_ledger(mark["ledger"])
    result = adaptive.presentation(final)
    assert result["closed"] and result["requires_review"]
    assert result["spent"] == 600 and result["held"] == 0
    assert result["recommendation"] == state.best_feasible["reference"]
    assert result["recommendation"] != action.seed
    assert final.visual_reviews == {}
    result["recommendation"]["values"]["noise_std"] = 999.0
    assert adaptive.presentation(final)["recommendation"] == state.best_feasible["reference"]
    assert files(root) == before and reviews(action) == decisions
    forbidden = {
        "guided_starting_fit_selected",
        "guided_method_preference",
        "candidate_visual_review",
        "guided_joint_starting_fit_selected",
    }
    assert not any(
        event["event"] in forbidden
        for snapshot in action.states.values()
        if (snapshot.study_directory / study.STUDY_EVENTS).exists()
        for event in study._load_events(snapshot.study_directory)
    )


def test_failed_child_keeps_full_reservation_and_presents_previous_field(action, monkeypatch):
    first = adaptive.prepare(action.arguments)
    runner = action.Runner(first.study_directory)
    attempts = []

    def stopped(**_kwargs):
        attempts.append(first.study_directory)
        first.candidates[0].status, first.candidates[0].attempts = "failed", 1
        return first

    monkeypatch.setattr(runner, "run_current_stage", stopped)
    final = adaptive.run(runner)
    root = action.base.study_directory.parent
    before, decisions = files(root), reviews(action)
    result = adaptive.presentation(final)
    assert result["closed"] and result["requires_review"]
    assert result["spent"] == 0 and result["held"] == 100 and result["total"] == 600
    assert result["recommendation"] == action.seed
    assert "incomplete" in result["reason"]
    assert attempts == [first.study_directory]
    assert adaptive.presentation(final) == result
    assert files(root) == before and reviews(action) == decisions
    assert not action.launches


def test_expired_prepared_action_opens_retained_field_but_cannot_launch(action, monkeypatch):
    first = adaptive.prepare(action.arguments)
    root = action.base.study_directory.parent
    mark = adaptive.marker(first.attachment_comparison)
    deadline = mark["contract"]["deadline"]
    monkeypatch.setattr(policy.time, "time", lambda: deadline + 1)
    before, decisions = files(root), reviews(action)
    result = adaptive.presentation(first)
    assert result["closed"] and result["requires_review"]
    assert "deadline has expired" in result["reason"]
    assert result["recommendation"] == action.seed
    assert result["spent"] == result["held"] == 0
    manifest = study._verify_manifest(first.study_directory)
    # Expiry permits read-only review of the immutable prepared declaration.
    adaptive.verify_declaration(first.study_directory, manifest, first.attachment_comparison)
    with pytest.raises(ValueError, match="deadline ended"):
        adaptive.authorize_launch(first.study_directory, manifest, first.candidates[0].candidate_id)
    assert not action.launches
    assert policy.load_ledger(mark["ledger"]).stages == ()
    assert files(root) == before and reviews(action) == decisions


def test_historical_stage_exposes_current_best_without_reopening_its_budget(action):
    first = adaptive.prepare(action.arguments)
    final = adaptive.run(action.Runner(first.study_directory))
    root = action.base.study_directory.parent
    before, decisions = files(root), reviews(action)
    result = adaptive.presentation(first)
    assert result["closed"] and "historical" in result["reason"]
    assert result["spent"] == 600
    assert result["recommendation"] == adaptive.finished_reference(final)
    assert result["recommendation"] != adaptive._reference(first, first.candidates[0].candidate_id)
    launches = list(action.launches)
    with pytest.raises(ValueError, match="historical"):
        adaptive.run(action.Runner(first.study_directory))
    assert action.launches == launches
    assert files(root) == before and reviews(action) == decisions


def test_expired_retained_reference_is_reverified_and_does_not_hide_changed_field(
    action, monkeypatch
):
    first = adaptive.prepare(action.arguments)
    mark = adaptive.marker(first.attachment_comparison)
    deadline = mark["contract"]["deadline"]
    monkeypatch.setattr(policy.time, "time", lambda: deadline + 1)
    original = native.inspect_field

    def changed(snapshot, identifier):
        field = deepcopy(original(snapshot, identifier))
        field["field_sha256"] = "f" * 64
        return field

    monkeypatch.setattr(native, "inspect_field", changed)
    root = action.base.study_directory.parent
    before, decisions = files(root), reviews(action)
    with pytest.raises(ValueError, match="original retained field changed"):
        adaptive.presentation(first)
    assert files(root) == before and reviews(action) == decisions
    assert not action.launches


def test_ordinary_snapshot_has_no_adaptive_presentation_or_hidden_files(action):
    before = files(action.base.study_directory)
    assert adaptive.presentation(action.base) is None
    assert files(action.base.study_directory) == before
    assert action.base.visual_reviews == {"guided-varifold": False}
    assert not action.launches

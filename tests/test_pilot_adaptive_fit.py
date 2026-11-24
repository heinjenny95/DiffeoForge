"""Bounded policy/ledger qualification, without meshes, native workers or approval."""

import hashlib
from copy import deepcopy

import pytest

from diffeoforge import pilot_adaptive_fit as adaptive


def h(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def contract(**changes):
    values = dict(
        action_id="synthetic-action",
        seed_sha256=h("seed"),
        objective_sha256=h("physical-objective"),
        marks_sha256=h("red-and-green-marks"),
        evaluation_sha256=h("exact-roi-measurement-protocol"),
        red_tolerances=dict(A=1.0, B=1.0, C=1.0),
        green_limits=dict(G=0.01),
        outside_limit=0.02,
        wall_seconds=1000,
        now=100.0,
    )
    return adaptive.create_contract(**(values | changes))


def baseline(c):
    return dict(
        field_sha256=c["seed_sha256"],
        native_receipt_sha256=h("seed-native"),
        objective_sha256=c["objective_sha256"],
        marks_sha256=c["marks_sha256"],
        evaluation_sha256=c["evaluation_sha256"],
        basis_sha256=h("original-basis"),
        control_count=100,
        movement_width=1.0,
        prefix_sha256=None,
        finite=True,
        accepted=True,
        normal_terminal=True,
        stop="seed",
        iterations=0,
        evaluations=0,
        duration_seconds=0.0,
        red_errors=dict(A=10.0, B=8.0, C=6.0),
        green_errors=dict(G=0.0),
        outside_error=0.0,
    )


def create(tmp_path, **changes):
    c = contract(**changes)
    root = tmp_path / "action"
    return root, adaptive.create_ledger(root, c, baseline=baseline(c), now=100.0)


def binding(state, decision):
    seed, purpose = decision["seed"], decision["purpose"]
    row = dict(
        child_manifest_sha256=h(decision["stage_id"]),
        seed_sha256=seed["field_sha256"],
        objective_sha256=decision["objective_sha256"],
        marks_sha256=decision["marks_sha256"],
        evaluation_sha256=decision["evaluation_sha256"],
        basis_sha256=seed["basis_sha256"],
        parent_basis_sha256=seed["basis_sha256"],
        control_count=seed["control_count"],
        movement_width=seed["movement_width"],
        initialization=decision["initialization"],
        optimizer_history="new",
        basis_relation="unchanged",
        prefix_sha256=(
            seed["field_sha256"] if decision["initialization"] == "zero_residual"
            else seed["prefix_sha256"]
        ),
    )
    if purpose == "cp_probe":
        row.update(basis_sha256=h("nested-basis"), control_count=150, basis_relation="nested")
    elif purpose == "motion_probe":
        previous = next(s["binding"] for s in state.stages if s["plan"]["purpose"] == "cp_probe")
        row.update(
            basis_sha256=previous["basis_sha256"],
            parent_basis_sha256=previous["basis_sha256"],
            control_count=previous["control_count"],
            movement_width=0.5,
        )
    return row


def reserve(root, state):
    plan = adaptive.next_decision(state)
    assert plan["kind"] == "stage"
    stage = adaptive.reserve_stage(
        root,
        plan,
        binding(state, plan),
        request_id="reserve-" + plan["stage_id"],
        expected_head=state.head,
        now=state.now,
    )
    return stage, adaptive.load_ledger(root, now=state.now)


def receipt(
    stage,
    red=None,
    *,
    green=0.0,
    outside=0.0,
    iterations=None,
    finite=True,
    accepted=True,
    quality_warnings=None,
    native_accepted=None,
):
    bound, plan = stage["binding"], stage["plan"]
    count = plan["iterations"] if iterations is None else iterations
    result = dict(
        bound,
        field_sha256=h((stage["stage_id"], red, green, outside)),
        native_receipt_sha256=h("native-" + stage["stage_id"]),
        finite=finite,
        accepted=accepted,
        normal_terminal=True,
        stop="maximum_iterations" if count == plan["iterations"] else "tolerance",
        iterations=count,
        evaluations=count * 2,
        duration_seconds=5.0,
        red_errors=red or deepcopy(plan["seed"]["red_errors"]),
        green_errors=dict(G=green),
        outside_error=outside,
    )
    if quality_warnings is not None:
        result["quality_warnings"] = quality_warnings
    if native_accepted is not None:
        result["native_accepted"] = native_accepted
    return result


def finish(root, state, stage, red=None, **changes):
    return adaptive.complete_stage(
        root,
        stage["stage_id"],
        receipt(stage, red, **changes),
        request_id="complete-" + stage["stage_id"],
        expected_head=state.head,
        now=state.now + 5,
    )


def test_opt_in_contract_rejects_more_than_600_and_requires_wall_allowance():
    with pytest.raises(ValueError):
        contract(total_iterations=601)
    with pytest.raises(ValueError):
        contract(wall_seconds=0)
    with pytest.raises(ValueError):
        contract(minimum_improvement=1)
    c = contract()
    assert c["opt_in"] and not c["anatomical_approval"]
    assert c["deadline"] == 1100


@pytest.mark.parametrize("residual_start", [False, True])
def test_all_completed_and_discarded_arms_share_one_budget_and_one_probe_seed(
    tmp_path, residual_start,
):
    root, state = create(tmp_path, residual_start=residual_start)
    warm, state = reserve(root, state)
    assert warm["plan"]["initialization"] == ("zero_residual" if residual_start else "learned")
    assert warm["plan"]["iterations"] == 100 and state.held == 100 and state.remaining == 500
    state = finish(root, state, warm, dict(A=10.0, B=6.0, C=6.0))
    shared_seed = state.best_feasible["field_sha256"]
    rows = (dict(A=9.0, B=6.0, C=6.0), dict(A=5.0, B=5.0, C=4.0), dict(A=7.0, B=4.0, C=4.0))
    for purpose, red in zip(adaptive._PROBES, rows, strict=True):
        stage, state = reserve(root, state)
        assert stage["plan"]["purpose"] == purpose
        assert stage["plan"]["seed"]["field_sha256"] == shared_seed
        assert stage["plan"]["iterations"] == 40
        assert stage["binding"]["prefix_sha256"] == shared_seed
        state = finish(root, state, stage, red)
    assert state.spent == 220 and state.remaining == 380 and state.held == 0
    # The motion arm improves B but loses A. It must not replace the CP field.
    assert state.best_feasible["stage_id"] == "stage-0003"
    decision = adaptive.next_decision(state)
    assert decision["purpose"] == "continue" and not decision["cp_bottleneck_proven"]
    assert decision["seed"] == state.best_feasible


def test_iterations_of_progressive_stages_never_exceed_600(tmp_path):
    root, state = create(tmp_path)
    while adaptive.next_decision(state)["kind"] == "stage":
        stage, state = reserve(root, state)
        red = {key: value * 0.9 for key, value in stage["plan"]["seed"]["red_errors"].items()}
        state = finish(root, state, stage, red)
    assert state.spent == 600 and state.remaining == state.held == 0
    assert len(state.stages) == 6
    stop = adaptive.next_decision(state)
    assert stop["requires_review"] and not stop["anatomical_approval"]


def test_extra_iterations_require_progress_in_each_unresolved_area(tmp_path):
    root, state = create(tmp_path)
    for _ in range(5):
        stage, state = reserve(root, state)
        red = {key: value * 0.8 for key, value in stage["plan"]["seed"]["red_errors"].items()}
        state = finish(root, state, stage, red, native_accepted=True)
    final, state = reserve(root, state)
    before = final["plan"]["seed"]["red_errors"]
    # A and C improve substantially. B still misses its target and is unchanged.
    state = finish(root, state, final, {"A": before["A"] * 0.7,
        "B": before["B"], "C": before["C"] * 0.8}, native_accepted=True)
    assert state.spent == 600
    assert state.best_feasible["stage_id"] == final["stage_id"]
    assert adaptive.extension_progress(state) is None


@pytest.mark.parametrize(
    "changes", [dict(green=0.02), dict(outside=0.03), dict(finite=False), dict(accepted=False)]
)
def test_failed_protection_or_native_acceptance_rolls_back_to_feasible_seed(tmp_path, changes):
    root, state = create(tmp_path)
    stage, state = reserve(root, state)
    state = finish(root, state, stage, dict(A=0.5, B=0.5, C=0.5), **changes)
    assert state.best_feasible == state.baseline and state.spent == 100
    assert adaptive.next_decision(state)["kind"] == "stop"


def test_green_failure_in_a_probe_is_charged_but_not_selected(tmp_path):
    root, state = create(tmp_path)
    warm, state = reserve(root, state)
    state = finish(root, state, warm)
    base, state = reserve(root, state)
    state = finish(root, state, base)
    cp, state = reserve(root, state)
    state = finish(root, state, cp, dict(A=0.5, B=0.5, C=0.5), green=0.02)
    assert state.best_feasible["field_sha256"] != state.stages[-1]["receipt"]["field_sha256"]
    assert state.spent == 180
    assert adaptive.next_decision(state)["purpose"] == "motion_probe"


def test_qc_warning_warm_field_is_discarded_and_probes_share_earlier_valid_seed(tmp_path):
    root, state = create(tmp_path)
    warm, state = reserve(root, state)
    state = finish(
        root,
        state,
        warm,
        dict(A=0.1, B=0.1, C=0.1),
        accepted=False,
        native_accepted=True,
        quality_warnings=["spatial_resolution_sufficient", "numerical_selection_suitable"],
    )
    assert state.best_feasible == state.baseline and state.spent == 100
    for purpose in adaptive._PROBES:
        arm, state = reserve(root, state)
        assert arm["plan"]["purpose"] == purpose
        assert arm["plan"]["seed"]["field_sha256"] == state.baseline["field_sha256"]
        state = finish(root, state, arm)
    decision = adaptive.next_decision(state)
    assert decision["kind"] == "stop" and state.spent == 220
    assert "spatial_resolution_sufficient" in decision["quality_warnings"]
    assert decision["cp_bottleneck_proven"] is False


def test_only_qualified_contrast_can_replace_baseline_after_warm_qc_warning(tmp_path):
    root, state = create(tmp_path)
    warm, state = reserve(root, state)
    state = finish(
        root,
        state,
        warm,
        accepted=False,
        native_accepted=True,
        quality_warnings=["no_new_intersection_flags"],
    )
    base, state = reserve(root, state)
    state = finish(root, state, base)
    cp, state = reserve(root, state)
    state = finish(root, state, cp, dict(A=4.0, B=3.0, C=2.0))
    motion, state = reserve(root, state)
    state = finish(
        root,
        state,
        motion,
        dict(A=0.1, B=0.1, C=0.1),
        accepted=False,
        native_accepted=True,
        quality_warnings=["temporal_grid_stable"],
    )
    assert state.best_feasible["stage_id"] == cp["stage_id"]
    assert adaptive.next_decision(state)["purpose"] == "continue"
    assert adaptive.next_decision(state)["seed"]["stage_id"] == cp["stage_id"]


@pytest.mark.parametrize(
    "changes",
    [dict(green=0.02), dict(outside=0.03), dict(finite=False), dict(native_accepted=False)],
)
def test_qc_warning_cannot_override_protection_or_native_failure(tmp_path, changes):
    root, state = create(tmp_path)
    warm, state = reserve(root, state)
    state = finish(
        root,
        state,
        warm,
        accepted=False,
        quality_warnings=["spatial_resolution_sufficient"],
        **(dict(native_accepted=True) | changes),
    )
    assert adaptive.next_decision(state)["kind"] == "stop"
    assert state.best_feasible == state.baseline


def test_accepted_child_cannot_hide_qualification_warning(tmp_path):
    root, state = create(tmp_path)
    warm, state = reserve(root, state)
    with pytest.raises(ValueError, match="warning-bearing"):
        finish(root, state, warm, quality_warnings=["spatial_resolution_sufficient"])


def test_not_enough_remaining_budget_for_comparison_stops_without_partial_arms(tmp_path):
    root, state = create(tmp_path, total_iterations=200)
    stage, state = reserve(root, state)
    state = finish(root, state, stage)
    assert state.remaining == 100
    assert adaptive.next_decision(state)["kind"] == "stop"
    assert len(state.stages) == 1


def test_reservation_and_terminal_retries_are_idempotent_despite_old_head(tmp_path):
    root, first = create(tmp_path)
    plan = adaptive.next_decision(first)
    bound = binding(first, plan)
    stage = adaptive.reserve_stage(
        root, plan, bound, request_id="reserve", expected_head=first.head, now=100
    )
    again = adaptive.reserve_stage(
        root, plan, bound, request_id="reserve", expected_head=first.head, now=101
    )
    assert stage == again
    state = adaptive.load_ledger(root, now=101)
    data = receipt(stage, iterations=12)
    done = adaptive.complete_stage(
        root, stage["stage_id"], data, request_id="finish", expected_head=state.head, now=105
    )
    retry = adaptive.complete_stage(
        root, stage["stage_id"], data, request_id="finish", expected_head=state.head, now=106
    )
    assert retry.sequence == done.sequence == 2 and retry.spent == done.spent == 12
    assert retry.remaining == 588
    with pytest.raises(adaptive.StaleLedger):
        adaptive.complete_stage(
            root,
            stage["stage_id"],
            dict(data, iterations=11),
            request_id="finish",
            expected_head=state.head,
            now=107,
        )


def test_crash_after_event_publication_holds_budget_and_retry_finishes_commit(
    tmp_path, monkeypatch
):
    root, state = create(tmp_path)
    plan, marker = adaptive.next_decision(state), adaptive._marker
    monkeypatch.setattr(
        adaptive, "_marker", lambda *_: (_ for _ in ()).throw(OSError("power loss"))
    )
    with pytest.raises(OSError):
        adaptive.reserve_stage(
            root,
            plan,
            binding(state, plan),
            request_id="reserve",
            expected_head=state.head,
            now=100,
        )
    pending = adaptive.load_ledger(root, now=101)
    assert pending.held == 100 and pending.remaining == 500
    assert adaptive.next_decision(pending)["kind"] == "wait"
    monkeypatch.setattr(adaptive, "_marker", marker)
    retried = adaptive.reserve_stage(
        root, plan, binding(state, plan), request_id="reserve", expected_head=state.head, now=102
    )
    assert retried["status"] == "reserved"
    assert len(list((root / "events").glob("*.json"))) == 1
    assert (root / "commits/000001.json").is_file()


def test_stale_or_modified_plans_cannot_reserve_more_work(tmp_path):
    root, state = create(tmp_path)
    plan = adaptive.next_decision(state)
    with pytest.raises(ValueError):
        adaptive.reserve_stage(
            root,
            dict(plan, iterations=600),
            binding(state, plan),
            request_id="forged",
            expected_head=state.head,
            now=100,
        )
    reserve(root, state)
    with pytest.raises(adaptive.StaleLedger):
        adaptive.reserve_stage(
            root, plan, binding(state, plan), request_id="stale", expected_head=state.head, now=101
        )


@pytest.mark.parametrize(
    "change",
    [
        "objective_sha256",
        "marks_sha256",
        "evaluation_sha256",
        "optimizer_history",
        "seed_sha256",
        "movement_width",
    ],
)
def test_child_contract_cannot_silently_change_physics_marks_seed_or_optimizer(tmp_path, change):
    root, state = create(tmp_path)
    plan = adaptive.next_decision(state)
    bound = binding(state, plan)
    bound[change] = (
        0.5
        if change == "movement_width"
        else ("restored" if change == "optimizer_history" else h("changed"))
    )
    with pytest.raises(ValueError):
        adaptive.reserve_stage(
            root, plan, bound, request_id="bad", expected_head=state.head, now=100
        )
    assert adaptive.load_ledger(root, now=100).sequence == 0


def test_roi_loss_unknown_shutdown_and_over_cap_receipts_keep_full_reservation(tmp_path):
    root, state = create(tmp_path)
    stage, state = reserve(root, state)
    good = receipt(stage)
    for bad in (
        dict(good, iterations=101),
        dict(good, normal_terminal=False),
        dict(good, red_errors=dict(A=1.0, B=1.0)),
        dict(good, green_errors={}),
    ):
        with pytest.raises(ValueError):
            adaptive.complete_stage(
                root, stage["stage_id"], bad, request_id="bad", expected_head=state.head, now=101
            )
    current = adaptive.load_ledger(root, now=101)
    assert current.held == 100 and current.spent == 0 and current.sequence == 1


def test_abort_charges_uncertain_cap_and_never_automatically_restarts(tmp_path):
    root, state = create(tmp_path)
    stage, state = reserve(root, state)
    with pytest.raises(ValueError):
        adaptive.abort_stage(
            root,
            stage["stage_id"],
            reason="worker lost",
            shutdown_verified=False,
            request_id="abort",
            expected_head=state.head,
            now=101,
        )
    done = adaptive.abort_stage(
        root,
        stage["stage_id"],
        reason="verified stopped after worker loss",
        shutdown_verified=True,
        request_id="abort",
        expected_head=state.head,
        now=102,
    )
    assert done.spent == 100 and done.held == 0 and done.remaining == 500
    assert adaptive.next_decision(done)["kind"] == "stop"


def test_deadline_and_clock_rollback_cannot_restore_allowance(tmp_path):
    root, state = create(tmp_path, wall_seconds=10)
    stage, state = reserve(root, state)
    expired = adaptive.load_ledger(root, now=111)
    assert adaptive.next_decision(expired)["kind"] == "cancel"
    done = adaptive.complete_stage(
        root,
        stage["stage_id"],
        receipt(stage, iterations=4),
        request_id="finish",
        expected_head=state.head,
        now=112,
    )
    assert adaptive.next_decision(done)["kind"] == "stop" and done.spent == 4
    with pytest.raises(ValueError, match="clock moved backwards"):
        adaptive.load_ledger(root, now=105)


def test_committed_tail_deletion_and_contract_edits_fail_closed(tmp_path):
    root, state = create(tmp_path)
    reserve(root, state)
    (root / "events/000001.json").unlink()
    with pytest.raises(ValueError, match="tail was removed"):
        adaptive.load_ledger(root, now=101)


@pytest.mark.parametrize("arm", ["cp_probe", "motion_probe"])
def test_capacity_and_motion_probes_cannot_confuse_which_variable_changed(tmp_path, arm):
    root, state = create(tmp_path)
    while adaptive.next_decision(state).get("purpose") != arm:
        stage, state = reserve(root, state)
        state = finish(root, state, stage)
    plan = adaptive.next_decision(state)
    correct = binding(state, plan)
    if arm == "cp_probe":
        bad = dict(correct, movement_width=0.5)
    else:
        bad = dict(correct, basis_sha256=h("another-basis"))
    before = state.head
    with pytest.raises(ValueError):
        adaptive.reserve_stage(
            root, plan, bad, request_id="confounded", expected_head=state.head, now=state.now
        )
    assert adaptive.load_ledger(root, now=state.now).head == before
    assert (
        adaptive.reserve_stage(
            root,
            plan,
            correct,
            request_id="qualified-contrast",
            expected_head=state.head,
            now=state.now,
        )["status"]
        == "reserved"
    )


def test_no_gain_in_all_three_contrasts_stops_without_cp_causal_claim(tmp_path):
    root, state = create(tmp_path)
    for _ in range(4):
        stage, state = reserve(root, state)
        assert stage["plan"]["cp_bottleneck_proven"] is False
        state = finish(root, state, stage)
    decision = adaptive.next_decision(state)
    assert decision["kind"] == "stop" and decision["requires_review"]
    assert decision["reference"] == state.baseline
    assert state.spent == 220 and state.remaining == 380


def test_an_existing_action_cannot_be_reinitialized_to_restore_600(tmp_path):
    root, state = create(tmp_path)
    stage, state = reserve(root, state)
    before = {p: p.read_bytes() for p in root.rglob("*.json")}
    with pytest.raises(FileExistsError):
        adaptive.create_ledger(root, contract(), baseline=baseline(contract()), now=100)
    assert before == {p: p.read_bytes() for p in before}
    after = adaptive.load_ledger(root, now=101)
    assert after.held == stage["plan"]["iterations"] == 100 and after.remaining == 500


def test_contract_content_change_is_rejected_without_replaying_a_smaller_budget(tmp_path):
    import json

    root, _ = create(tmp_path)
    path = root / "contract.json"
    old = json.loads(path.read_text())
    old["contract"]["total_iterations"] = 500
    path.write_text(json.dumps(old))
    with pytest.raises(ValueError, match="contract hash changed"):
        adaptive.load_ledger(root, now=101)

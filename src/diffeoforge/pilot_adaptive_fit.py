"""Opt-in bounded native-stage policy and durable effort ledger.

This module neither fits nor verifies native coefficients. Its caller must supply
independently verified accepted-field/ROI receipts and enforce each sealed child
stage's native cap and wall deadline. No receipt creates human inspection,
anatomical approval, a user preference, or a claim of a unique failure cause.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

VERSION = "bounded-adaptive-fit-v1"
MAX_ITERATIONS = 600
_MAX_EVENTS = 256
_LIMIT = 2 * 1024 * 1024
_PROBES = ("baseline_probe", "cp_probe", "motion_probe")
HARD_QUALITY_FLAGS = (
    "transition_preserved",
    "outside_preserved",
    "shape_preserved",
    "no_new_intersection_flags",
    "temporal_grid_stable",
    "spatial_resolution_sufficient",
    "explicit_fixed_preserved",
    "numerical_selection_suitable",
)


class StaleLedger(ValueError):
    """Reload the current action; no additional stage was authorized."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _hash(value, name):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("Invalid adaptive-fit hash: " + name)
    return value


def _number(value, name, *, positive=False):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or positive
        and value <= 0
    ):
        raise ValueError("Invalid adaptive-fit nonnegative scalar: " + name)
    return float(value)


def _integer(value, name, minimum=0, maximum=MAX_ITERATIONS):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid adaptive-fit bounded integer: " + name)
    return value


def _rois(values, name, *, empty=False, positive=False):
    if (
        not isinstance(values, dict)
        or not empty
        and not values
        or len(values) > 64
        or any(
            not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key)
            for key in values
        )
    ):
        raise ValueError("Invalid adaptive-fit ROI identities: " + name)
    return {
        key: _number(value, name + ":" + key, positive=positive)
        for key, value in sorted(values.items())
    }


def create_contract(
    *,
    action_id,
    seed_sha256,
    objective_sha256,
    marks_sha256,
    evaluation_sha256,
    red_tolerances,
    green_limits,
    outside_limit,
    wall_seconds,
    total_iterations=600,
    now=None,
    warm_iterations=100,
    probe_iterations=40,
    minimum_improvement=0.02,
):
    """Declare a NEW action, not a replacement contract for a prepared/running fit.

    Objective identity binds physical surface/ROI/protection terms. The only
    permitted diagnostic changes (basis and movement width) are separately bound
    in each child. Evaluation identity binds the scalar measurement protocol.
    The sample profile is a bounded experiment, not a fit-quality guarantee.
    """
    if not isinstance(action_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", action_id):
        raise ValueError("An adaptive action needs an explicit stable identity")
    created = _number(time.time() if now is None else now, "created_at")
    wall = _number(wall_seconds, "wall_seconds", positive=True)
    improvement = _number(minimum_improvement, "minimum_improvement")
    if improvement >= 1:
        raise ValueError("The declared improvement fraction must be smaller than one")
    if not math.isfinite(created + wall):
        raise ValueError("The adaptive deadline exceeds the finite clock range")
    return dict(
        version=VERSION,
        opt_in=True,
        action_id=action_id,
        seed_sha256=_hash(seed_sha256, "seed"),
        objective_sha256=_hash(objective_sha256, "objective"),
        marks_sha256=_hash(marks_sha256, "marks"),
        evaluation_sha256=_hash(evaluation_sha256, "evaluation"),
        red_tolerances=_rois(red_tolerances, "red", positive=True),
        green_limits=_rois(green_limits, "green", empty=True),
        outside_limit=_number(outside_limit, "outside_limit"),
        total_iterations=_integer(total_iterations, "total_iterations", 1),
        warm_iterations=_integer(warm_iterations, "warm_iterations", 1),
        probe_iterations=_integer(probe_iterations, "probe_iterations", 1),
        minimum_improvement=improvement,
        created_at=created,
        wall_seconds=wall,
        deadline=created + wall,
        anatomical_approval=False,
        automatic_user_preference=False,
    )


def _contract(value):
    fields = {
        k: value[k]
        for k in (
            "action_id",
            "seed_sha256",
            "objective_sha256",
            "marks_sha256",
            "evaluation_sha256",
            "red_tolerances",
            "green_limits",
            "outside_limit",
            "wall_seconds",
            "total_iterations",
            "warm_iterations",
            "probe_iterations",
            "minimum_improvement",
        )
    }
    rebuilt = create_contract(**fields, now=value["created_at"])
    if value != rebuilt or value["minimum_improvement"] >= 1:
        raise ValueError("The adaptive-fit contract changed or is unsupported")
    return rebuilt


def _receipt(value, contract, *, seed=False, stage=None):
    row = deepcopy(value)
    for key in (
        "field_sha256",
        "native_receipt_sha256",
        "objective_sha256",
        "marks_sha256",
        "evaluation_sha256",
        "basis_sha256",
    ):
        _hash(row.get(key), key)
    for key in ("objective_sha256", "marks_sha256", "evaluation_sha256"):
        if row[key] != contract[key]:
            raise ValueError("The accepted-field receipt changed " + key)
    for key in ("finite", "accepted", "normal_terminal"):
        if type(row.get(key)) is not bool:
            raise ValueError("Missing explicit native scalar receipt: " + key)
    warnings = row.get("quality_warnings", [])
    if (
        not isinstance(warnings, list)
        or any(type(key) is not str or key not in HARD_QUALITY_FLAGS for key in warnings)
        or len(warnings) != len(set(warnings))
    ):
        raise ValueError("Invalid adaptive numerical qualification warnings")
    if "native_accepted" in row and type(row["native_accepted"]) is not bool:
        raise ValueError("Missing explicit native accepted-state evidence")
    if not seed and warnings and row["accepted"]:
        raise ValueError("A warning-bearing child cannot become an automatic numerical seed")
    if not row["normal_terminal"]:
        raise ValueError("Unverified shutdown cannot refund a reserved stage budget")
    if row.get("stop") not in {"seed", "maximum_iterations", "tolerance", "accepted_boundary"}:
        raise ValueError("Unknown accepted native stop; no adaptive restart is authorized")
    cap = 0 if seed else stage["plan"]["iterations"]
    _integer(row.get("iterations"), "iterations", maximum=cap)
    if not seed and row["stop"] == "maximum_iterations" and row["iterations"] != cap:
        raise ValueError("The maximum-iteration receipt does not match its reserved native cap")
    _integer(row.get("evaluations"), "evaluations", maximum=10_000_000)
    _number(row.get("duration_seconds"), "duration_seconds")
    row["red_errors"] = _rois(row.get("red_errors"), "red errors")
    row["green_errors"] = _rois(row.get("green_errors"), "green errors", empty=True)
    if set(row["red_errors"]) != set(contract["red_tolerances"]) or set(row["green_errors"]) != set(
        contract["green_limits"]
    ):
        raise ValueError("Every declared red and green ROI must be measured separately")
    _number(row.get("outside_error"), "outside_error")
    _integer(row.get("control_count"), "control_count", 1, 2_000)
    _number(row.get("movement_width"), "movement_width", positive=True)
    if row.get("prefix_sha256") is not None:
        _hash(row["prefix_sha256"], "prefix")
    if seed:
        if row["field_sha256"] != contract["seed_sha256"] or row["stop"] != "seed":
            raise ValueError("The numerical baseline is not this action's declared seed")
    else:
        binding = stage["binding"]
        for key in (
            "child_manifest_sha256",
            "basis_sha256",
            "control_count",
            "movement_width",
            "prefix_sha256",
        ):
            if row.get(key) != binding.get(key):
                raise ValueError("The completed receipt differs from its sealed child: " + key)
        row["stage_id"] = stage["stage_id"]
    return row


def _feasible(receipt, contract):
    return (
        receipt["finite"]
        and receipt["accepted"]
        and receipt["normal_terminal"]
        and receipt["outside_error"] <= contract["outside_limit"]
        and all(
            receipt["green_errors"][key] <= limit for key, limit in contract["green_limits"].items()
        )
    )


def _qc_only_warm_failure(receipt, contract):
    """The unsafe result is discarded; contrasts restart from the prior valid seed."""
    warnings = receipt.get("quality_warnings", [])
    return bool(
        warnings
        and receipt["accepted"] is False
        and receipt.get("native_accepted") is True
        and receipt["finite"]
        and receipt["normal_terminal"]
        and not {"outside_preserved", "explicit_fixed_preserved", "shape_preserved"}.intersection(
            warnings
        )
        and receipt["outside_error"] <= contract["outside_limit"]
        and all(
            receipt["green_errors"][key] <= limit for key, limit in contract["green_limits"].items()
        )
    )


def _score(receipt, contract):
    ratios = [
        receipt["red_errors"][key] / limit for key, limit in contract["red_tolerances"].items()
    ]
    return max(ratios), sum(ratios)


def _dominates(after, before):
    a, b = after["red_errors"], before["red_errors"]
    return all(a[key] <= b[key] for key in b) and any(a[key] < b[key] for key in b)


@dataclass(frozen=True)
class LedgerState:
    contract: dict
    baseline: dict
    head: str
    sequence: int
    stages: tuple
    best_feasible: dict
    spent: int
    held: int
    remaining: int
    now: float

    @property
    def active(self):
        return next((row for row in self.stages if row["status"] == "reserved"), None)

    @property
    def deadline(self):
        return self.contract["deadline"]


def _state(contract, baseline, head, sequence, stages, now):
    best, spent, held = baseline, 0, 0
    for stage in stages:
        if stage["status"] == "reserved":
            held += stage["plan"]["iterations"]
        elif stage["status"] == "aborted":
            spent += stage["plan"]["iterations"]
        else:
            receipt = stage["receipt"]
            spent += receipt["iterations"]
            if (
                _feasible(receipt, contract)
                and _dominates(receipt, best)
                and _score(receipt, contract) < _score(best, contract)
            ):
                best = receipt
    remaining = contract["total_iterations"] - spent - held
    if remaining < 0 or sum(row["status"] == "reserved" for row in stages) > 1:
        raise ValueError("The adaptive action exceeded its cumulative reserved budget")
    return LedgerState(
        deepcopy(contract),
        deepcopy(baseline),
        head,
        sequence,
        tuple(deepcopy(stages)),
        deepcopy(best),
        spent,
        held,
        remaining,
        now,
    )


def next_decision(state):
    """One numerical experiment or a conservative stop; never an anatomical decision."""
    contract, stages = state.contract, state.stages

    def stop(reason):
        result = dict(
            kind="stop",
            reason=reason,
            reference=deepcopy(state.best_feasible),
            requires_review=True,
            anatomical_approval=False,
            state_head=state.head,
        )
        warnings = list(
            dict.fromkeys(
                key for row in stages for key in row.get("receipt", {}).get("quality_warnings", [])
            )
        )
        if warnings:
            result.update(quality_warnings=warnings, cp_bottleneck_proven=False)
        return result

    if state.active and state.now >= state.deadline:
        return dict(
            kind="cancel",
            stage_id=state.active["stage_id"],
            state_head=state.head,
            reason="Request verified supervisor shutdown; the declared deadline ended.",
        )
    if state.active:
        return dict(
            kind="wait",
            stage_id=state.active["stage_id"],
            state_head=state.head,
            reason="A reserved child must be reconciled; its full cap remains held.",
        )
    if state.now >= state.deadline:
        return stop("The declared wall-time allowance ended; retain the best feasible field.")
    if state.remaining == 0:
        return stop("The cumulative iteration allowance ended, including discarded comparisons.")
    if any(row["status"] == "aborted" for row in stages):
        return stop(
            "A child did not finish with verified numerical evidence; inspect the retained field."
        )
    if _score(state.best_feasible, contract)[0] <= 1:
        return stop(
            "The declared red-ROI numerical targets were reached; anatomy still needs review."
        )
    probes = [row for row in stages if row["plan"]["purpose"] in _PROBES]
    if probes and len(probes) < 3:
        purpose = _PROBES[len(probes)]
        seed = probes[0]["plan"]["seed"]
        iterations = contract["probe_iterations"]
    elif probes and stages[-1]["plan"]["purpose"] == "motion_probe":
        group_seed = probes[0]["plan"]["seed"]
        if state.best_feasible["field_sha256"] == group_seed["field_sha256"]:
            return stop(
                "No qualified controlled capacity/movement contrast improved the retained red ROIs."
            )
        purpose, seed = "continue", state.best_feasible
        iterations = min(contract["warm_iterations"], state.remaining)
    elif not stages:
        purpose, seed = "warm", state.baseline
        iterations = min(contract["warm_iterations"], state.remaining)
    else:
        last = stages[-1]
        receipt, seed = last["receipt"], state.best_feasible
        qc_only = (
            last["plan"]["purpose"] == "warm"
            and not probes
            and _qc_only_warm_failure(receipt, contract)
        )
        if not _feasible(receipt, contract) and not qc_only:
            return stop(
                "Native acceptance, qualification or retained-area checks failed; "
                "retain the earlier feasible field."
            )
        before = last["plan"]["seed"]["red_errors"]
        stalled = any(
            receipt["red_errors"][key] > contract["red_tolerances"][key]
            and receipt["red_errors"][key] >= before[key] * (1 - contract["minimum_improvement"])
            for key in before
        )
        if (stalled or qc_only) and not probes:
            if state.remaining < 3 * contract["probe_iterations"]:
                return stop(
                    "Too little declared budget remains for a matched three-arm comparison."
                )
            purpose, iterations = _PROBES[0], contract["probe_iterations"]
        elif stalled:
            return stop(
                "The selected contrast stalled; further adaptation requires researcher review."
            )
        else:
            purpose, iterations = "continue", min(contract["warm_iterations"], state.remaining)
    if iterations > state.remaining:
        return stop("The next sealed stage would exceed the remaining action allowance.")
    return dict(
        kind="stage",
        stage_id=f"stage-{len(stages) + 1:04d}",
        purpose=purpose,
        iterations=iterations,
        seed=deepcopy(seed),
        objective_sha256=contract["objective_sha256"],
        marks_sha256=contract["marks_sha256"],
        evaluation_sha256=contract["evaluation_sha256"],
        initialization="zero_residual" if purpose in _PROBES else "learned",
        optimizer_history="new",
        wall_deadline=state.deadline,
        state_head=state.head,
        anatomical_approval=False,
        cp_bottleneck_proven=False,
    )


def _binding(binding, decision, state):
    row, purpose, seed = deepcopy(binding), decision["purpose"], decision["seed"]
    for key in (
        "child_manifest_sha256",
        "seed_sha256",
        "objective_sha256",
        "marks_sha256",
        "evaluation_sha256",
        "basis_sha256",
        "parent_basis_sha256",
    ):
        _hash(row.get(key), key)
    if (
        row["seed_sha256"] != seed["field_sha256"]
        or any(
            row[key] != decision[key]
            for key in ("objective_sha256", "marks_sha256", "evaluation_sha256")
        )
        or row.get("initialization") != decision["initialization"]
        or row.get("optimizer_history") != "new"
    ):
        raise ValueError(
            "The child changed its seed, objective, marks, or fresh-optimizer contract"
        )
    _integer(row.get("control_count"), "control_count", 1, 2_000)
    _number(row.get("movement_width"), "movement_width", positive=True)
    expected_prefix = seed["field_sha256"] if purpose in _PROBES else seed.get("prefix_sha256")
    if row.get("prefix_sha256") != expected_prefix:
        raise ValueError("The complete accepted field/prefix must remain unchanged")
    if purpose == "cp_probe":
        if (
            row.get("basis_relation") != "nested"
            or row["parent_basis_sha256"] != seed["basis_sha256"]
            or row["control_count"] <= seed["control_count"]
            or row["movement_width"] != seed["movement_width"]
        ):
            raise ValueError(
                "The CP contrast must isolate added zero-field controls at the same width"
            )
    elif purpose == "motion_probe":
        cp = next(s["binding"] for s in state.stages if s["plan"]["purpose"] == "cp_probe")
        if (
            row.get("basis_relation") != "unchanged"
            or row["basis_sha256"] != cp["basis_sha256"]
            or row["parent_basis_sha256"] != cp["basis_sha256"]
            or row["control_count"] != cp["control_count"]
            or row["movement_width"] >= cp["movement_width"]
        ):
            raise ValueError(
                "The motion contrast must retain the CP arm's basis and narrow only its width"
            )
    elif (
        row.get("basis_relation") != "unchanged"
        or row["basis_sha256"] != seed["basis_sha256"]
        or row["parent_basis_sha256"] != seed["basis_sha256"]
        or row["control_count"] != seed["control_count"]
        or row["movement_width"] != seed["movement_width"]
    ):
        raise ValueError("This stage must preserve its exact accepted control basis and width")
    return row


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _LIMIT:
        raise ValueError("Invalid adaptive ledger file")
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError("Nonfinite adaptive ledger JSON: " + value)
        ),
    )


def _publish(path, value):
    """Exclusive complete-file publication; existing journal bytes are never replaced."""
    raw = _json(value).encode()
    temporary = path.with_name(".pending-" + uuid4().hex)
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise StaleLedger(
                    "The adaptive ledger advanced or existing evidence changed"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)


def _marker(root, sequence, head):
    _publish(root / "commits" / f"{sequence:06d}.json", dict(sequence=sequence, head=head))


def create_ledger(path, contract, *, baseline, now=None):
    contract = _contract(contract)
    baseline = _receipt(baseline, contract, seed=True)
    if not _feasible(baseline, contract):
        raise ValueError(
            "The baseline needs a finite accepted field with verified green/outside protection"
        )
    root = Path(path).absolute()
    root.mkdir(parents=False, exist_ok=False)
    if root.resolve() != root or root.is_symlink():
        raise ValueError("Adaptive ledger directory is not a new independent directory")
    (root / "events").mkdir()
    (root / "commits").mkdir()
    header = dict(contract=contract, contract_sha256=digest(contract), baseline=baseline)
    _publish(root / "contract.json", header)
    _marker(root, 0, digest(header))
    return load_ledger(root, now=now)


def load_ledger(path, *, now=None):
    root = Path(path).absolute()
    if root.resolve() != root or root.is_symlink():
        raise ValueError("Adaptive ledger identity changed")
    header = _read(root / "contract.json")
    contract = _contract(header["contract"])
    if header["contract_sha256"] != digest(contract):
        raise ValueError("Adaptive action contract hash changed")
    baseline = _receipt(header["baseline"], contract, seed=True)
    if not _feasible(baseline, contract):
        raise ValueError("Adaptive baseline protection evidence changed")
    head, stages, operations = digest(header), [], set()
    previous_time = contract["created_at"]
    markers = sorted((root / "commits").glob("*.json"))
    if not markers or _read(markers[0]) != dict(sequence=0, head=head):
        raise ValueError("The adaptive ledger lost its initial commit marker")
    paths = sorted((root / "events").glob("*.json"))
    if len(paths) > _MAX_EVENTS:
        raise ValueError("Oversized adaptive action ledger")
    heads = [head]
    for index, path in enumerate(paths, 1):
        event = _read(path)
        payload = {key: value for key, value in event.items() if key != "event_hash"}
        if (
            path.name != f"{index:06d}.json"
            or event.get("sequence") != index
            or event.get("previous_hash") != head
            or event.get("event_hash") != digest(payload)
            or event.get("request_id") in operations
        ):
            raise ValueError("Adaptive ledger chain or operation identity changed")
        stamp = _number(event.get("recorded_at"), "recorded_at")
        if stamp < previous_time:
            raise ValueError("Adaptive action clock moved backwards")
        state = _state(contract, baseline, head, index - 1, stages, stamp)
        if event["event"] == "stage_reserved":
            row = event["payload"]
            if (
                row["plan"] != next_decision(state)
                or row["plan"]["kind"] != "stage"
                or row["stage_id"] != row["plan"]["stage_id"]
            ):
                raise ValueError("Reserved child differs from the bounded adaptive policy")
            _binding(row["binding"], row["plan"], state)
            stages.append(dict(row, status="reserved"))
        else:
            active = state.active
            if not active or event["payload"].get("stage_id") != active["stage_id"]:
                raise ValueError("Adaptive terminal event has no matching reserved child")
            row = stages[-1]
            if event["event"] == "stage_completed":
                receipt = _receipt(event["payload"]["receipt"], contract, stage=active)
                row.update(status="completed", receipt=receipt)
            elif event["event"] == "stage_aborted":
                if event["payload"].get("shutdown_verified") is not True:
                    raise ValueError("An unverified backend cannot release its action reservation")
                row.update(status="aborted", reason=event["payload"]["reason"])
            else:
                raise ValueError("Unknown adaptive ledger event")
        head, previous_time = event["event_hash"], stamp
        operations.add(event["request_id"])
        heads.append(head)
    for marker in markers:
        value = _read(marker)
        sequence = value.get("sequence")
        if (
            type(sequence) is not int
            or not 0 <= sequence < len(heads)
            or marker.name != f"{sequence:06d}.json"
            or value.get("head") != heads[sequence]
        ):
            raise ValueError("A committed adaptive ledger tail was removed or changed")
    stamp = _number(time.time() if now is None else now, "now")
    if stamp < previous_time:
        raise ValueError("Adaptive action clock moved backwards; its budget cannot be reset")
    return _state(contract, baseline, head, len(paths), stages, stamp)


def _events(root):
    return [_read(path) for path in sorted((root / "events").glob("*.json"))]


def _append(root, kind, payload, request_id, expected_head, now):
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id):
        raise ValueError("An adaptive operation needs a stable retry identity")
    state = load_ledger(root, now=now)
    previous = _events(root)
    old = next((event for event in previous if event["request_id"] == request_id), None)
    if old:
        if old["event"] != kind or old["payload"] != payload:
            raise StaleLedger("An adaptive retry changed its already recorded operation")
        _marker(root, old["sequence"], old["event_hash"])
        return load_ledger(root, now=now)
    if state.head != expected_head:
        raise StaleLedger("The adaptive action advanced; reload before preparing another child")
    event = dict(
        sequence=state.sequence + 1,
        previous_hash=state.head,
        event=kind,
        request_id=request_id,
        recorded_at=state.now,
        payload=deepcopy(payload),
    )
    event["event_hash"] = digest(event)
    # Fully validate the proposed operation before any journal file is published.
    if kind == "stage_reserved":
        if payload["plan"] != next_decision(state) or payload["plan"]["kind"] != "stage":
            raise ValueError("Adaptive stage plan is stale or changes the declared budget")
        _binding(payload["binding"], payload["plan"], state)
    elif not state.active or payload["stage_id"] != state.active["stage_id"]:
        raise ValueError("No matching active adaptive stage")
    elif kind == "stage_completed":
        _receipt(payload["receipt"], state.contract, stage=state.active)
    elif kind != "stage_aborted" or payload.get("shutdown_verified") is not True:
        raise ValueError("A verified terminal shutdown is required")
    _publish(root / "events" / f"{event['sequence']:06d}.json", event)
    _marker(root, event["sequence"], event["event_hash"])
    return load_ledger(root, now=now)


def reserve_stage(path, decision, binding, *, request_id, expected_head, now=None):
    """Reserve the full cap durably BEFORE native launch; retry never spends twice."""
    root = Path(path).absolute()
    payload = dict(
        stage_id=decision["stage_id"], plan=deepcopy(decision), binding=deepcopy(binding)
    )
    state = _append(root, "stage_reserved", payload, request_id, expected_head, now)
    return next(deepcopy(row) for row in state.stages if row["stage_id"] == decision["stage_id"])


def complete_stage(path, stage_id, verified_receipt, *, request_id, expected_head, now=None):
    """Reconcile actual effort; only a normally stopped bound child releases unused cap."""
    return _append(
        Path(path).absolute(),
        "stage_completed",
        dict(stage_id=stage_id, receipt=deepcopy(verified_receipt)),
        request_id,
        expected_head,
        now,
    )


def abort_stage(path, stage_id, *, reason, shutdown_verified, request_id, expected_head, now=None):
    """Keep the entire uncertain reservation charged, stop, and retain the feasible field."""
    if not isinstance(reason, str) or not reason or len(reason) > 2000:
        raise ValueError("A bounded adaptive abort reason is required")
    return _append(
        Path(path).absolute(),
        "stage_aborted",
        dict(stage_id=stage_id, reason=reason, shutdown_verified=shutdown_verified),
        request_id,
        expected_head,
        now,
    )

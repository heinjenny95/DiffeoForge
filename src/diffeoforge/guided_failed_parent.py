"""Explicit different trials from an inspected parent after a terminal C5 failure.

Failed fields/checkpoints are never imported. Read-only previews are operation local;
the actual preparation and later strategy verification resolve the evidence afresh.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file

VERSION = "failed-regional-parent-v1"
NUMERICAL_REASONS = frozenset(
    {
        "nonfinite_or_invalid_objective",
        "nonfinite_or_invalid_gradient",
        "nonfinite_or_invalid_parameters",
        "gradient_norm_overflow",
        "accepted_cost_regression",
    }
)


def _json(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Failure evidence is not an object")
    return value


def _terminal(snapshot, identifier):
    """Read only terminal metadata, never coefficients, checkpoint or saved best state."""
    from diffeoforge import runs
    from diffeoforge.reference_finite_accepted_guard import DECLARATION

    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    if candidate.status != "failed" or snapshot.plan.pilot_subject_count != 1:
        raise ValueError("Only a terminal single-form numerical failure has this route")
    run = study.calibration_candidate_run_directory(candidate).resolve(strict=True)
    manifest = runs._read_manifest(run)
    runs._verify_protected_artifacts(run, manifest)
    config = manifest["effective_config"]
    provenance = config["project"].get("parameter_provenance", {})
    if provenance.get("finite_accepted_guard") != DECLARATION or not provenance.get("regional_fit"):
        raise ValueError("This failure lacks the new finite-accepted guard")
    result = _json(run / "result.json")
    control = runs._control_receipt(
        run, (run / "logs/backend-control-token").read_text(encoding="ascii")
    )
    if (
        result.get("run_id") != manifest["run_id"]
        or result.get("status") != "failed"
        or type(result.get("return_code")) is not int
        or result["return_code"] == 0
        or control["state"] != "completed"
        or control.get("backend_return_code") != result["return_code"]
    ):
        raise ValueError("The failed backend has no matching normal terminal shutdown")
    inventory_path, inventory = runs._read_output_inventory(run, result)
    records = {r["path"].replace("\\", "/"): r for r in inventory["files"]}
    seals = {}
    for name in ("numerical-guard/violation.json", "numerical-guard/events.jsonl"):
        record = records.get(name)
        path = run / "output" / name
        if (
            not record
            or path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            raise ValueError("Terminal numerical failure metadata changed")
        seals[name] = record["sha256"]
    violation = _json(run / "output/numerical-guard/violation.json")
    events = [
        json.loads(line)
        for line in (run / "output/numerical-guard/events.jsonl").read_text().splitlines()
        if line
    ]
    terminals = [e for e in events if e.get("kind") == "terminal_violation"]
    reason = violation.get("reason")
    if (
        reason not in NUMERICAL_REASONS
        or violation.get("automatic_restore") is not False
        or not terminals
        or terminals[-1].get("reason") != reason
    ):
        raise ValueError("Unknown/context failure requires input review, not a new numerical test")
    return dict(
        run=str(run),
        reason=reason,
        manifest_sha256=sha256_file(run / "manifest.json"),
        result_sha256=sha256_file(run / "result.json"),
        control_sha256=sha256_file(run / "logs/backend-control.json"),
        inventory_sha256=sha256_file(inventory_path),
        metadata=seals,
    )


def resolve(snapshot, identifier, *, terminal=True, prepared=False):
    from diffeoforge.guided_feedback import _same_source, region_state, selection
    from diffeoforge.guided_strategy import _candidate
    from diffeoforge.pilot_regions import validate

    info = guided.record(snapshot)
    strategy = info.get("strategy") or {}
    ref = (
        (strategy.get("anchor") or strategy.get("baseline"))
        if prepared
        else selection(snapshot, identifier)
    )
    if not ref or Path(ref["directory"]).resolve() == snapshot.study_directory.resolve():
        raise ValueError("Select a verified earlier inspected starting fit")
    parent = _same_source(snapshot, ref)
    _candidate(parent, ref["candidate_id"])
    current = study._verify_manifest(snapshot.study_directory)
    previous = study._verify_manifest(parent.study_directory)
    target = ref["target"]
    current_subject = next(r for r in current["inputs"]["subjects"] if r["filename"] == target)
    parent_subject = next(r for r in previous["inputs"]["subjects"] if r["filename"] == target)
    if (
        current["inputs"]["template"]["sha256"] != previous["inputs"]["template"]["sha256"]
        or current_subject["sha256"] != parent_subject["sha256"]
    ):
        raise ValueError("Earlier fit uses changed original geometry")
    if prepared:
        feedback = info.get("feedback") or {}
        if feedback.get("target") != target:
            raise ValueError("Failed prepared marked-area binding is missing")
        marks = feedback.get("regions", [])
        cleared = feedback.get("regions_cleared", False)
    else:
        marks, cleared = region_state(snapshot, identifier, target)
    validate({target: marks} if marks else {}, {target: current_subject["sha256"]})
    evidence = dict(
        version=VERSION,
        failed_directory=str(snapshot.study_directory),
        failed_manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
        candidate_id=identifier,
        reference=deepcopy(ref),
        marks=deepcopy(marks),
        regions_cleared=cleared,
        failure=_terminal(snapshot, identifier) if terminal else None,
    )
    return parent, evidence


def preview(snapshot, identifier):
    """Trusted-parent inspection remains available even for an unqualified failure."""
    try:
        _parent, evidence = resolve(snapshot, identifier, terminal=False)
    except (ValueError, OSError, RuntimeError, KeyError, StopIteration) as error:
        return dict(reference=None, available=False, reason=str(error))
    try:
        evidence["failure"] = _terminal(snapshot, identifier)
    except (ValueError, OSError, RuntimeError, KeyError, StopIteration) as error:
        return dict(reference=evidence["reference"], available=False, reason=str(error))
    return dict(
        reference=evidence["reference"],
        available=True,
        reason="The failed trial stays saved. Choose a different test from the "
        "inspected earlier fit; its field and all marked areas are preserved.",
    )


def inputs(snapshot, identifier, context):
    from diffeoforge.guided_search import inputs as verified_inputs
    from diffeoforge.guided_strategy import state

    parent, evidence = resolve(snapshot, identifier)
    ref = evidence["reference"]
    parent_context = state(parent)
    # Keep completed history responses; the failed field adds no measured response or approval.
    parent_context["cases"] = context["cases"]
    data = verified_inputs(
        parent,
        ref["candidate_id"],
        parent_context,
        regions_override=evidence["marks"],
        allow_continuation=False,
    )
    data["anchor"] = ref
    data["current_reference"] = None  # No same-objective completion from this failure route.
    data["references"][ref["directory"]] = parent
    return dict(
        parent=parent,
        data=data,
        evidence=evidence,
        failed_objectives=known_failures(snapshot, identifier, evidence),
    )


def _objective(method, values, recipe):
    # Only terms consumed by regional_fit.prepare distinguish this hypothesis.
    # Recipe labels, UUIDs, cap/seed/provenance and unused presentation evidence do not.
    recipe = recipe or {}
    mathematical = {
        key: recipe.get(key)
        for key in (
            "focus_width",
            "focus_noise",
            "protection_noise",
            "protection_halo",
            "guide_noise",
            "protection_close_distance",
            "protection_tolerance",
        )
    }
    if recipe.get("guide_noise") is not None:
        mathematical["guide_points"] = recipe.get("guide_points")
    return dict(method=method, values=values, recipe=mathematical)


def _fingerprint(objective):
    return hashlib.sha256(
        json.dumps(objective, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def known_failures(snapshot, identifier, evidence):
    """Metadata only; no failed CP/M, geometry measurement or optimizer import."""
    from diffeoforge.config import load_config
    from diffeoforge.reference_finite_accepted_guard import DECLARATION

    info = guided.record(snapshot)
    states = [snapshot]
    seen = {str(snapshot.study_directory.resolve())}
    for row in info["history"]:
        root = Path(row["directory"]).resolve()
        if sha256_file(root / study.STUDY_MANIFEST) != row["manifest_sha256"]:
            raise ValueError("Failed-objective history manifest changed")
        if str(root) not in seen:
            states.append(study.load_reference_calibration_study(root))
            seen.add(str(root))
    expected = {}
    for other in states:
        marker = (guided.record(other).get("strategy") or {}).get("failure_parent_recovery")
        if marker:
            expected[(str(Path(marker["failed_directory"]).resolve()), marker["candidate_id"])] = (
                marker["failure"]
            )
            for old in marker.get("failed_objectives", []):
                expected[(str(Path(old["directory"]).resolve()), old["candidate_id"])] = old[
                    "failure"
                ]
    failures = []
    for other in states:
        for candidate in other.candidates:
            if candidate.status != "failed":
                continue
            key = (str(other.study_directory.resolve()), candidate.candidate_id)
            current = other is snapshot and candidate.candidate_id == identifier
            if not current and key not in expected:
                config = load_config(candidate.config_path)
                if (
                    config["project"].get("parameter_provenance", {}).get("finite_accepted_guard")
                    != DECLARATION
                ):
                    continue  # Historical unguarded failures are not this numerical protocol.
            _parent, old = resolve(other, candidate.candidate_id, terminal=False, prepared=True)
            if (
                old["reference"] != evidence["reference"]
                or old["marks"] != evidence["marks"]
                or old["regions_cleared"] != evidence["regions_cleared"]
            ):
                continue
            terminal = _terminal(other, candidate.candidate_id)
            if key in expected and expected[key] != terminal:
                raise ValueError("A known failed-objective terminal receipt changed")
            values = next(
                c.values
                for c in other.current_stage.candidates
                if c.candidate_id == candidate.candidate_id
            )
            objective = _objective(
                other.attachment_comparison["methods"][candidate.candidate_id],
                values,
                (guided.record(other).get("strategy") or {}).get("regional_recipe"),
            )
            failures.append(
                dict(
                    directory=str(other.study_directory),
                    manifest_sha256=old["failed_manifest_sha256"],
                    candidate_id=candidate.candidate_id,
                    objective=objective,
                    fingerprint=_fingerprint(objective),
                    failure=terminal,
                )
            )
    return sorted(failures, key=lambda row: (row["directory"], row["candidate_id"]))


def propose(snapshot, identifier, request, verified):
    from diffeoforge.guided_search import propose as ordinary_proposal

    if (
        not request
        or request == "goal:optimize"
        or ":" not in request
        and request != "other_method"
    ):
        raise ValueError("Choose an explicit different adjustment; no failed optimizer is resumed")
    ref = verified["evidence"]["reference"]
    proposal = ordinary_proposal(verified["parent"], ref["candidate_id"], request, verified["data"])
    mathematical = _objective(
        proposal["method"], proposal["values"], proposal.get("regional_recipe")
    )
    same = any(
        row["fingerprint"] == _fingerprint(mathematical) for row in verified["failed_objectives"]
    )
    if same or proposal.get("numerical_extension") or proposal.get("regional_continuation"):
        proposal.update(
            available=False,
            blocked_reason="This repeats the failed objective. "
            "Choose a different adjustment; the failed field cannot be continued.",
        )
    if proposal.get("initialization_reference") and proposal["initialization_reference"] != ref:
        raise ValueError("Failure recovery cannot seed any field except its verified parent")
    marker = deepcopy(verified["evidence"])
    marker["failed_objectives"] = deepcopy(verified["failed_objectives"])
    proposal["failure_parent_recovery"] = marker
    return proposal


def trial(snapshot, identifier, request, context):
    """Fresh evidence for the explicit preparation; GUI preview objects are not accepted."""
    return propose(snapshot, identifier, request, inputs(snapshot, identifier, context))


def verify_marker(marker, info, record, manifest):
    root = Path(marker["failed_directory"])
    if sha256_file(root / study.STUDY_MANIFEST) != marker["failed_manifest_sha256"]:
        raise ValueError("Failed predecessor changed")
    snapshot = study.load_reference_calibration_study(root)
    _parent, fresh = resolve(snapshot, marker["candidate_id"])
    bare = {key: value for key, value in marker.items() if key != "failed_objectives"}
    if (
        fresh != bare
        or (info.get("feedback") or {}).get("regions") != marker["marks"]
        or (info.get("strategy") or {}).get("baseline") != marker["reference"]
    ):
        raise ValueError("Failure-parent provenance, marked areas or trusted seed changed")

    failures = known_failures(snapshot, marker["candidate_id"], fresh)
    if failures != marker.get("failed_objectives"):
        raise ValueError("Known failed-objective history, parent or marked areas changed")
    strategy = info.get("strategy") or {}
    method = set(record["methods"].values())
    if len(method) != 1 or strategy.get("optimization") or strategy.get("regional_continuation"):
        raise ValueError("Failure-parent successor cannot continue a failed optimizer")
    actual = _objective(
        next(iter(method)),
        manifest["plan"]["baseline_effective_values"],
        strategy.get("regional_recipe"),
    )
    if any(row["fingerprint"] == _fingerprint(actual) for row in failures):
        raise ValueError("Failure-parent successor repeats a known failed objective")

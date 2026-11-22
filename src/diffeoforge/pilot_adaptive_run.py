"""New, explicitly bounded regional actions through the ordinary pilot runner.

The durable policy ledger owns effort.  Every child is a new normal pilot study,
with native supervision and full qualification; ledger membership grants no
inspection, anatomical approval, or researcher preference.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from diffeoforge import pilot_adaptive_fit as policy
from diffeoforge.mesh import sha256_file

WALL_SECONDS = 7200
_EXTENSION_DIRECTORY = "extension-300"
_LATEST_SEARCH = "fit-search-latest.json"
_LIMIT = 4 * 1024 * 1024
_PROBES = {"baseline_probe", "cp_probe", "motion_probe"}
_RECIPE_MECHANISM = {
    "phase",
    "residual",
    "control_support",
    "control_scope",
    "control_budget_policy",
    "protection_reference",
    "capture_evidence",
    "level",
}
_MARKER_KEYS = {
    "version",
    "ledger",
    "contract",
    "plan",
    "seed_reference",
    "basis_source",
    "basis_relation",
    "parent_basis_sha256",
}


def marker(record):
    return ((record.get("guided") or {}).get("strategy") or {}).get("adaptive_fit")


def eligible(proposal):
    """Recognize same-method red/fixed regional requests, not landmark guides."""
    if not isinstance(proposal, dict) or proposal.get("available") is False:
        return False
    goal = proposal.get("goal", proposal.get("request", ""))
    if not isinstance(goal, str) or goal.split(":", 1)[0] != "regional":
        return False
    rows = proposal.get("regions")
    if (
        not isinstance(rows, (list, tuple))
        or not rows
        or any(not isinstance(row, dict) for row in rows)
    ):
        return False
    if not any(row.get("purpose", "problem") == "problem" for row in rows) or any(
        row.get("purpose", "problem") not in {"problem", "fixed"}
        or row.get("symptom") in {"gap", "position"}
        for row in rows
    ):
        return False
    recipe = proposal.get("regional_recipe")
    if recipe is not None and (
        not isinstance(recipe, dict) or recipe.get("guide_noise") is not None
    ):
        return False
    ref = proposal.get("initialization_reference") or proposal.get("reference")
    if not isinstance(ref, dict) or ref.get("method") not in {"current", "varifold"}:
        return False
    return proposal.get("method", ref["method"]) == ref["method"]


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _LIMIT:
        raise ValueError("Adaptive action metadata is absent, linked, or oversized")
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda _v: (_ for _ in ()).throw(
            ValueError("Nonfinite adaptive action metadata")
        ),
    )


def _write(path, value):
    from diffeoforge import reference_calibration_study as study

    study._write_json(Path(path), value, overwrite=False)


def _record(snapshot):
    return snapshot.attachment_comparison


def _reference(snapshot, identifier):
    from diffeoforge.guided_feedback import reference

    return reference(snapshot, identifier)


def _snapshot(ref):
    from diffeoforge import reference_calibration_study as study

    root = Path(ref["directory"])
    if sha256_file(root / study.STUDY_MANIFEST) != ref["manifest_sha256"]:
        raise ValueError("Adaptive saved field manifest changed")
    result = study.load_reference_calibration_study(root)
    if _reference(result, ref["candidate_id"]) != ref:
        raise ValueError("Adaptive saved field result or settings binding changed")
    return result


def _recipe_identity(recipe):
    return {
        key: copy.deepcopy(value) for key, value in recipe.items() if key not in _RECIPE_MECHANISM
    }


def _basis(path, spacing):
    import numpy as np

    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Adaptive control basis is absent or linked")
    path = path.resolve()
    points = np.loadtxt(path, dtype=np.float64).reshape(-1, 3)
    if (
        not 1 <= len(points) <= 2000
        or not np.isfinite(points).all()
        or type(spacing) not in (int, float)
        or not math.isfinite(spacing)
        or spacing <= 0
    ):
        raise ValueError("Adaptive control basis or spacing is invalid")
    return dict(
        path=str(path),
        sha256=sha256_file(path),
        basis_sha256=hashlib.sha256(points.astype("<f8").tobytes()).hexdigest(),
        count=len(points),
        spacing=spacing,
    )


def _context(mark):
    ledger = Path(mark["ledger"])
    if not ledger.is_absolute() or ledger.resolve() != ledger or ledger.is_symlink():
        raise ValueError("Adaptive ledger must retain its exact absolute identity")
    state = policy.load_ledger(ledger)
    context = _read(ledger.parent / "action.json")
    if mark["contract"] != state.contract or policy.digest(context) != state.baseline.get(
        "preparation_sha256"
    ):
        raise ValueError("Adaptive action preparation or contract changed")
    if state.contract.get("extension_of"):
        _verify_extension_parent(ledger, state, context)
    return ledger, state, context


class UnmeasuredRedBaseline(ValueError):
    """A red area's saved field has no surface samples in one direction."""


def _red_baseline(feedback):
    rows, baseline = feedback["regions"], feedback.get("baseline") or []
    errors = {}
    missing_surface = False
    directions = (
        ("original_to_fit_p95", "selected_faces", "forward_count"),
        ("fit_to_original_p95", "reverse_selected_faces", "reverse_count"),
    )
    for index, region in enumerate(rows):
        if region.get("purpose", "problem") != "problem":
            continue
        matches = [row for row in baseline if row.get("region") == region]
        if len(matches) != 1:
            raise ValueError("Each adaptive red area needs its exact captured baseline")
        area = matches[0]
        repeats = area.get("repeats")
        if not repeats:
            raise ValueError("Each adaptive red area needs repeated surface measurements")
        values = []
        for repeat in repeats:
            for distance, faces, count in directions:
                value = repeat.get(distance)
                if (distance in repeat and value is None
                        and type(area.get(faces)) is int and area[faces] == 0
                        and type(repeat.get(count)) is int and repeat[count] == 0):
                    missing_surface = True
                    continue
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError("Adaptive red baseline has invalid surface measurements")
                values.append(value)
        if values:
            errors[f"R{index}"] = max(values)
    if missing_surface:
        raise UnmeasuredRedBaseline(
            "A red area has no surface samples in one direction. Reopen the pilot guidance "
            "to prepare a protected local test from the saved fit."
        )
    return errors


def has_bidirectional_baseline(regions, measurements):
    """Only structural absence rules out adaptation while allowing a local trial."""
    try:
        _red_baseline(dict(regions=regions, baseline=measurements))
    except UnmeasuredRedBaseline:
        return False
    return True


def prepare(arguments):
    """Prepare one NEW bounded action from freshly verified normal batch arguments."""
    action_started = time.time()
    from diffeoforge import pilot_adaptive_native as native
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.guided_feedback import verify_reference

    args = copy.deepcopy(
        {key: value for key, value in arguments.items() if key not in {"source", "previous"}}
    )
    args.update(source=arguments["source"], previous=arguments["previous"])
    strategy = args.get("strategy") or {}
    ref = strategy.get("baseline")
    request = dict(
        goal=args.get("goal"),
        regions=(args.get("feedback") or {}).get("regions"),
        regional_recipe=strategy.get("regional_recipe"),
        reference=ref,
        method=(args.get("methods") or [None])[0],
    )
    if (
        not eligible(request)
        or len(args.get("methods") or ()) != 1
        or not strategy.get("regional_recipe")
        or args.get("phase") != "refine"
    ):
        raise ValueError("Bounded adaptation requires a same-method red/fixed regional fit")
    seed_snapshot = verify_reference(ref)
    field = native.inspect_field(seed_snapshot, ref["candidate_id"])
    if field["reference"] != ref:
        raise ValueError("Adaptive initial field changed; choose an unchanged-field test")
    from diffeoforge.regional_material_frame import (
        PROTECTED_RESIDUAL_NOTE,
        warm_start_requires_residual,
    )

    if warm_start_requires_residual(seed_snapshot, ref["candidate_id"], args["previous"]):
        raise ValueError("Reopen pilot guidance. " + PROTECTED_RESIDUAL_NOTE)
    incoming = args["feedback"]
    identity_keys = ("directory", "candidate_id", "manifest_sha256", "binding", "target")
    if any(incoming.get(key) != ref[key] for key in identity_keys):
        from diffeoforge.pilot_recovery import capture

        refreshed = capture(
            seed_snapshot,
            ref["candidate_id"],
            ref["target"],
            regions=copy.deepcopy(incoming["regions"]),
        )
        if any(refreshed.get(key) != ref[key] for key in identity_keys):
            raise ValueError("The adaptive baseline was not measured on its exact chosen field")
        if "regions_cleared" in incoming:
            refreshed["regions_cleared"] = incoming["regions_cleared"]
        args["feedback"] = refreshed
    recipe = copy.deepcopy(strategy["regional_recipe"])
    tolerance = recipe.get("protection_tolerance")
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Bounded adaptation needs the existing positive protection tolerance")
    recipe.update(residual=False, phase="initial_warm", protection_reference=copy.deepcopy(ref))
    args["values"] = copy.deepcopy(ref["values"])
    strategy = copy.deepcopy(strategy)
    for key in ("optimization", "regional_continuation", "adaptive_fit"):
        strategy.pop(key, None)
    strategy.update(
        regional_recipe=recipe,
        anchor=copy.deepcopy(ref),
        baseline=copy.deepcopy(ref),
        control_basis=copy.deepcopy(ref),
        preference=None,
    )
    args["strategy"] = strategy
    red_errors = _red_baseline(args["feedback"])
    if time.time() >= action_started + WALL_SECONDS:
        raise ValueError("The adaptive preparation used its wall allowance; no child was prepared")
    parent = Path(args.get("destination_parent") or args["source"].study_directory.parent).resolve()
    action = parent / ("adaptive-fit-" + uuid4().hex[:12])
    action.mkdir(exist_ok=False)
    template = {
        key: copy.deepcopy(value)
        for key, value in args.items()
        if key not in {"source", "previous", "destination_parent"}
    }
    template.update(
        source_directory=str(args["source"].study_directory),
        source_manifest_sha256=sha256_file(args["source"].study_directory / "study.json"),
        initial_previous_directory=str(args["previous"].study_directory),
        seed_reference=copy.deepcopy(ref),
    )
    marks = args["feedback"]["regions"]
    contract = policy.create_contract(
        action_id=action.name,
        seed_sha256=field["field_sha256"],
        objective_sha256=policy.digest(dict(recipe=_recipe_identity(recipe), seed=ref)),
        marks_sha256=policy.digest(marks),
        evaluation_sha256=policy.digest(
            dict(
                version="adaptive-original-roi-p95-v1",
                directions="maximum",
                repeats="maximum",
                units="native_coordinates",
            )
        ),
        red_tolerances={
            f"R{i}": tolerance
            for i, row in enumerate(marks)
            if row.get("purpose", "problem") == "problem"
        },
        green_limits={
            f"G{i}": tolerance for i, row in enumerate(marks) if row.get("purpose") == "fixed"
        },
        outside_limit=tolerance,
        wall_seconds=WALL_SECONDS,
        now=action_started,
    )
    baseline = native.baseline_receipt(
        seed_snapshot,
        ref["candidate_id"],
        contract,
        red_errors=red_errors,
        regions=marks,
    )
    baseline.update(reference=copy.deepcopy(ref), preparation_sha256=policy.digest(template))
    _write(action / "action.json", template)
    state = policy.create_ledger(action / "ledger", contract, baseline=baseline)
    decision = policy.next_decision(state)
    if decision["kind"] != "stage":
        raise ValueError("The declared red targets already need review, not a new optimizer")
    basis = _basis(field["control_points_path"], ref["values"]["initial_control_point_spacing"])
    args["destination_parent"] = action
    args["strategy"]["adaptive_fit"] = _marker(action / "ledger", state, decision, ref, basis)
    return guided._batch(**args)


def _marker(ledger, state, decision, human_seed, basis, relation="unchanged"):
    return dict(
        version=policy.VERSION,
        ledger=str(Path(ledger).resolve()),
        contract=copy.deepcopy(state.contract),
        plan=copy.deepcopy(decision),
        seed_reference=copy.deepcopy(human_seed),
        basis_source=copy.deepcopy(basis),
        basis_relation=relation,
        parent_basis_sha256=basis["sha256"],
    )


def verify_declaration(root, manifest, record):
    """Read-only declaration checks; a child is not reserved or approved here."""
    mark = marker(record)
    if not mark:
        return
    root = Path(root).resolve()
    if set(mark) != _MARKER_KEYS or mark.get("version") != policy.VERSION:
        raise ValueError("Unsupported adaptive child declaration")
    ledger, state, context = _context(mark)
    decision = mark["plan"]
    if (
        root.parent != ledger.parent
        or root == ledger
        or root.is_symlink()
        or mark["seed_reference"] != context["seed_reference"]
        or record.get("iterations") != decision.get("iterations")
        or type(decision.get("iterations")) is not int
        or not 1 <= decision["iterations"] <= policy.MAX_ITERATIONS
        or decision.get("anatomical_approval") is not False
    ):
        raise ValueError("Adaptive child scope or sealed effort changed")
    existing = next((row for row in state.stages if row["stage_id"] == decision["stage_id"]), None)
    # Expiry prevents launches, not reopening a previously prepared declaration.
    # Time does not otherwise alter this deterministic next-stage plan.
    declared_state = replace(state, now=state.contract["created_at"])
    if (existing and existing["plan"] != decision) or (
        not existing and decision != policy.next_decision(declared_state)
    ):
        raise ValueError("Adaptive child plan is stale or is not the ledger's next decision")
    strategy = record["guided"]["strategy"]
    recipe = strategy.get("regional_recipe") or {}
    if (
        policy.digest(record["guided"]["feedback"]["regions"]) != state.contract["marks_sha256"]
        or _recipe_identity(recipe) != _recipe_identity(context["strategy"]["regional_recipe"])
        or strategy.get("anchor") != context["seed_reference"]
        or strategy.get("baseline") != decision["seed"]["reference"]
        or strategy.get("control_basis") != decision["seed"]["reference"]
    ):
        raise ValueError("Adaptive original objective, marks, or retained prefix changed")
    basis = mark["basis_source"]
    if (
        _basis(basis["path"], basis["spacing"]) != basis
        or mark["parent_basis_sha256"] != basis["sha256"]
        or mark["basis_relation"] not in {"unchanged", "nested"}
    ):
        raise ValueError("Adaptive incoming exact control basis changed")
    actual = record.get("controls")
    if actual:
        supplied = _basis(root / actual["copy"], actual["spacing"])
        if decision["purpose"] != "cp_probe" and (
            supplied["basis_sha256"] != basis["basis_sha256"] or supplied["count"] != basis["count"]
        ):
            raise ValueError("Adaptive child changed its declared exact control basis")
        if decision["purpose"] == "cp_probe":
            import numpy as np

            previous = np.loadtxt(basis["path"], dtype=np.float64).reshape(-1, 3)
            current = np.loadtxt(root / actual["copy"], dtype=np.float64).reshape(-1, 3)
            if len(current) <= len(previous) or not np.array_equal(
                current[: len(previous)].view(np.uint64), previous.view(np.uint64)
            ):
                raise ValueError("Adaptive CP contrast is not an exact nested basis")
    if set(record.get("methods", {}).values()) != {context["methods"][0]}:
        raise ValueError("Adaptive action changed its requested matching method")
    if manifest.get("plan", {}).get("execution_scope") not in {None, "single_specimen_probe"}:
        raise ValueError("Adaptive fitting cannot authorize a joint Atlas")


def _child_binding(snapshot, mark):
    record = _record(snapshot)
    controls = record["controls"]
    basis = _basis(snapshot.study_directory / controls["copy"], controls["spacing"])
    decision, seed = mark["plan"], mark["plan"]["seed"]
    return dict(
        child_manifest_sha256=sha256_file(snapshot.study_directory / "study.json"),
        seed_sha256=seed["field_sha256"],
        objective_sha256=mark["contract"]["objective_sha256"],
        marks_sha256=mark["contract"]["marks_sha256"],
        evaluation_sha256=mark["contract"]["evaluation_sha256"],
        basis_sha256=basis["basis_sha256"],
        control_count=basis["count"],
        movement_width=snapshot.plan.effective_values["deformation_kernel_width"],
        parent_basis_sha256=mark["basis_source"]["basis_sha256"],
        basis_relation=mark["basis_relation"],
        initialization=decision["initialization"],
        optimizer_history="new",
        prefix_sha256=(
            seed["field_sha256"] if decision["purpose"] in _PROBES else seed.get("prefix_sha256")
        ),
        study_directory=str(snapshot.study_directory),
        candidate_id=snapshot.candidates[0].candidate_id,
    )


def authorize_launch(root, manifest, candidate_id):
    """Reserve the complete declared cap before exactly one fresh native child."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.config import load_config

    record = manifest.get("attachment_comparison") or {}
    mark = marker(record)
    if not mark:
        return
    verify_declaration(root, manifest, record)
    ledger, state, context = _context(mark)
    if state.now >= state.deadline:
        raise ValueError("The adaptive action deadline ended; no native child can launch")
    if any(row["event"] == "adaptive_fit_finished" for row in study._load_events(Path(root))):
        raise ValueError("This adaptive action has finished; prepare a new reviewed action")
    snapshot = study.load_reference_calibration_study(root)
    if len(snapshot.candidates) != 1 or snapshot.candidates[0].candidate_id != candidate_id:
        raise ValueError("An adaptive stage launches exactly its one declared candidate")
    candidate = snapshot.candidates[0]
    if candidate.status != "pending" or candidate.attempts != 0:
        raise ValueError("An adaptive child cannot restart an attempted or unverified native run")
    config = load_config(candidate.config_path)
    if (
        config["optimization"]["max_iterations"] != mark["plan"]["iterations"]
        or not config["optimization"]["freeze_template"]
        or not config["optimization"]["freeze_control_points"]
    ):
        raise ValueError("The native child cap or frozen singleton contract changed")
    binding = _child_binding(snapshot, mark)
    if state.active:
        if state.active["plan"] != mark["plan"] or state.active["binding"] != binding:
            raise ValueError("Another adaptive child still holds the remaining effort")
    if state.contract.get("extension_of"):
        with study.calibration_verification_scope():
            _verify_extension_launch(snapshot, context)
    if state.active:
        return state.active
    return policy.reserve_stage(
        ledger,
        mark["plan"],
        binding,
        request_id="reserve-" + mark["plan"]["stage_id"],
        expected_head=state.head,
    )


def trusted_reference(snapshot, reference):
    """Accept a bound completed internal field, never fabricate inspection."""
    from diffeoforge import pilot_adaptive_native as native

    mark = marker(_record(snapshot))
    if not mark:
        return False
    _, state, _ = _context(mark)
    if _reference(snapshot, reference["candidate_id"]) != reference:
        return False
    completed = [
        row
        for row in state.stages
        if row["status"] == "completed" and row["receipt"].get("reference") == reference
    ]
    if len(completed) != 1:
        return False
    receipt = completed[0]["receipt"]
    if not policy._feasible(receipt, state.contract):
        return False
    field = native.inspect_field(snapshot, reference["candidate_id"])
    return all(field.get(key) is True for key in ("accepted", "finite", "normal_terminal")) and all(
        field[key] == receipt[key]
        for key in ("field_sha256", "basis_sha256", "native_receipt_sha256")
    )


def finished_reference(snapshot):
    from diffeoforge import reference_calibration_study as study

    mark = marker(_record(snapshot))
    if not mark:
        return None
    ledger, state, _ = _context(mark)
    rows = [
        row
        for row in study._load_events(snapshot.study_directory)
        if row["event"] == "adaptive_fit_finished"
    ]
    if not rows:
        return None
    event, ref = rows[-1], state.best_feasible.get("reference")
    if (
        event.get("best_reference") != ref
        or event.get("ledger") != str(ledger)
        or event.get("contract_sha256") != policy.digest(state.contract)
        or event.get("spent") != state.spent
        or event.get("held_iterations") != state.held
    ):
        raise ValueError("Adaptive final recommendation no longer matches its ledger")
    return _verified_best_reference(state)


def _verified_best_reference(state):
    from diffeoforge import pilot_adaptive_native as native

    ref = state.best_feasible["reference"]
    source = _snapshot(ref)
    if ref == state.baseline.get("reference"):
        field = native.inspect_field(source, ref["candidate_id"])
        if field["field_sha256"] != state.baseline["field_sha256"]:
            raise ValueError("Adaptive original retained field changed")
    elif not trusted_reference(source, ref):
        raise ValueError("Adaptive numerical recommendation lost its completed binding")
    return copy.deepcopy(ref)


def _extension_baseline(parent_state, context):
    baseline = copy.deepcopy(parent_state.best_feasible)
    baseline.pop("stage_id")
    return dict(baseline, stop="seed", iterations=0, evaluations=0, duration_seconds=0.0,
                preparation_sha256=policy.digest(context))


def _remaining_regions(state, context):
    from diffeoforge.pilot_region_scope import label

    progress = policy.extension_progress(state)
    if progress is None:
        return None
    return [
        dict(label=label(index), **progress[f"R{index}"])
        for index in range(len(context["feedback"]["regions"])) if f"R{index}" in progress
    ]


def _verify_extension_parent(ledger, state, context):
    """Bind the new allowance to one immutable original adaptive action."""
    if ledger.parent.name != _EXTENSION_DIRECTORY:
        raise ValueError("The additional allowance has an unexpected action directory")
    origin = ledger.parent.parent
    parent = policy.load_ledger(origin / "ledger")
    original = _read(origin / "action.json")
    offer = context["extension_offer"]
    if (
        policy.digest(original) != parent.baseline.get("preparation_sha256")
        or context != dict(original, extension_offer=offer)
        or parent.head != state.contract["extension_of"]
        or offer["state_head"] != parent.head
        or offer["reference"] != parent.best_feasible.get("reference")
        or Path(offer["reference"]["directory"]).parent != origin
        or offer["iterations"] != policy.EXTENSION_ITERATIONS
        or not offer["remaining_regions"]
        or offer["remaining_regions"] != _remaining_regions(parent, original)
        or state.baseline != _extension_baseline(parent, context)
        or any(state.contract[key] != parent.contract[key] for key in (
            "objective_sha256", "marks_sha256", "evaluation_sha256", "green_limits",
            "outside_limit", "red_tolerances", "minimum_improvement", "wall_seconds",
        ))
    ):
        raise ValueError("The additional allowance lost its verified 600-iteration parent")


def _extension_offer(snapshot, ledger, state, context, events, *, linked=False):
    from diffeoforge import guided_feedback as feedback
    from diffeoforge import pilot_adaptive_native as native

    if not linked and (snapshot.study_directory / _LATEST_SEARCH).exists():
        return None
    remaining = _remaining_regions(state, context)
    if not remaining:
        return None
    endings = [event for event in events if event["event"] == "adaptive_fit_finished"]
    reference = state.best_feasible["reference"]
    if (len(endings) != 1 or endings[0]["reason"] != policy.BUDGET_EXHAUSTED
            or endings[0].get("ledger") != str(ledger)
            or endings[0].get("best_reference") != reference
            or endings[0].get("contract_sha256") != policy.digest(state.contract)
            or endings[0].get("spent") != state.spent or endings[0].get("held_iterations") != 0
            or Path(reference["directory"]) != snapshot.study_directory):
        return None
    identifier, target = reference["candidate_id"], reference["target"]
    if snapshot.visual_reviews.get(identifier) is True or feedback.starting_fit_choice(
        snapshot, identifier
    ):
        return None
    marks, cleared = feedback.region_state(snapshot, identifier, target)
    if cleared or policy.digest(marks) != state.contract["marks_sha256"]:
        return None
    decision_events = {"guided_starting_fit_selected", "guided_fit_feedback",
                       "guided_method_preference", "guided_joint_starting_fit_selected"}
    if any(event["event"] in decision_events for event in events[endings[0]["sequence"] + 1:]):
        if feedback.selection(snapshot, identifier) != reference:
            return None
    # Recompute the bound scalars from production native/QC evidence for both
    # sides of the comparison. Ledger scalars alone cannot authorize a run.
    last = state.stages[-1]
    before = last["plan"]["seed"]
    for saved in (before, last["receipt"]):
        saved_ref = saved["reference"]
        source = snapshot if saved_ref == reference else _snapshot(saved_ref)
        actual = native.stage_receipt(source, saved_ref["candidate_id"], state.contract)
        actual.update(reference=_reference(source, saved_ref["candidate_id"]),
                      stage_id=saved["stage_id"])
        if actual != saved:
            return None
    return dict(iterations=policy.EXTENSION_ITERATIONS, remaining_regions=remaining,
                reference=copy.deepcopy(reference), state_head=state.head,
                review_sha256=events[-1]["event_hash"])


def _verify_extension_launch(snapshot, context):
    from diffeoforge import reference_calibration_study as study

    expected = context["extension_offer"]
    predecessor = _snapshot(expected["reference"])
    pointer = _read(predecessor.study_directory / _LATEST_SEARCH)
    expected_pointer = dict(directory=str(snapshot.study_directory),
                            manifest_sha256=sha256_file(snapshot.study_directory / "study.json"))
    if pointer != expected_pointer:
        raise ValueError("This additional allowance is not the current prepared continuation")
    parent_ledger, parent_state, original = _context(marker(_record(predecessor)))
    events = study._load_events(predecessor.study_directory)
    if _extension_offer(predecessor, parent_ledger, parent_state, original, events, linked=True
                        ) != expected:
        raise ValueError("The saved fit, checks or marked areas changed before continuation")


def _unlinked_extension(action, context):
    """Recover the one complete preparation if publication of its pointer stopped."""
    from diffeoforge import reference_calibration_study as study

    children = list(action.glob("guided-pilot-*/study.json"))
    if len(children) != 1 or action.is_symlink():
        return None
    prepared = study.load_reference_calibration_study(children[0].parent)
    mark = marker(_record(prepared))
    if not mark:
        return None
    ledger, state, saved = _context(mark)
    if (ledger == action / "ledger" and saved == context and not state.stages
            and state.now < state.deadline and len(prepared.candidates) == 1
            and prepared.candidates[0].status == "pending"
            and prepared.candidates[0].attempts == 0):
        return prepared
    return None


def prepare_extension(snapshot, expected_offer):
    """Prepare one separately bounded successor. Never launch or approve a fit."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided

    started = time.time()
    mark = marker(_record(snapshot))
    if not mark or not isinstance(expected_offer, dict):
        raise ValueError("Reopen the finished adaptive fit to verify its continuation")
    with study.calibration_verification_scope():
        ledger, state, original = _context(mark)
        verified = _extension_offer(snapshot, ledger, state, original,
                                    study._load_events(snapshot.study_directory))
    if verified is None or verified != expected_offer:
        raise ValueError("The continuation recommendation changed. Reopen the retained fit.")
    if time.time() >= started + state.contract["wall_seconds"]:
        raise ValueError("The continuation preparation used its wall allowance")
    action = ledger.parent / _EXTENSION_DIRECTORY
    context = dict(original, extension_offer=verified)
    if action.exists():
        prepared = _unlinked_extension(action, context)
        if prepared is None:
            raise ValueError("A prior continuation preparation cannot be safely reopened")
        guided._pointer(snapshot.study_directory, prepared.study_directory)
        return prepared
    contract_fields = (
        "objective_sha256", "marks_sha256", "evaluation_sha256", "red_tolerances",
        "green_limits", "outside_limit", "minimum_improvement", "wall_seconds",
        "probe_iterations",
    )
    contract = policy.create_contract(
        **{key: state.contract[key] for key in contract_fields},
        action_id=action.name, seed_sha256=state.best_feasible["field_sha256"],
        now=started, total_iterations=policy.EXTENSION_ITERATIONS,
        warm_iterations=policy.EXTENSION_ITERATIONS, extension_of=state.head,
    )
    action.mkdir(exist_ok=False)
    _write(action / "action.json", context)
    extension = policy.create_ledger(action / "ledger", contract,
                                     baseline=_extension_baseline(state, context))
    decision = policy.next_decision(extension)
    if decision["kind"] != "stage":
        raise ValueError("The continuation preparation used its wall allowance")
    return _next_child(snapshot, action / "ledger", extension, context, decision)


def presentation(snapshot):
    """Read-only, background-verified effort and retained-result presentation."""
    from diffeoforge import reference_calibration_study as study

    mark = marker(_record(snapshot))
    if not mark:
        return None
    ledger, state, context = _context(mark)
    events = study._load_events(snapshot.study_directory)
    endings = [row for row in events if row["event"] == "adaptive_fit_finished"]
    recommendation = finished_reference(snapshot) if endings else None
    expired = state.now >= state.deadline
    historical = bool(state.stages and mark["plan"]["stage_id"]
                      != state.stages[-1]["stage_id"])
    if not endings and (expired or historical):
        recommendation = _verified_best_reference(state)
    extension = None
    extension_incomplete = False
    if endings and not historical:
        try:
            extension = _extension_offer(snapshot, ledger, state, context, events)
        except (OSError, ValueError, KeyError, TypeError):
            # Missing additional trend evidence must not hide the saved fit.
            pass
        action = ledger.parent / _EXTENSION_DIRECTORY
        if extension and action.exists():
            try:
                recoverable = _unlinked_extension(action, dict(context, extension_offer=extension))
            except (OSError, ValueError, KeyError, TypeError):
                recoverable = None
            if recoverable is None:
                extension, extension_incomplete = None, True
    reason = (endings[-1]["reason"] if endings else
              "The action deadline has expired. Earlier fits remain saved." if expired else
              "This is a historical adaptive stage. Open the latest saved stage." if historical
              else "")
    if extension_incomplete:
        reason += " The earlier +300 preparation cannot be safely reopened."
    return dict(
        spent=state.spent, held=state.held, total=state.contract["total_iterations"],
        stage_iterations=mark["plan"]["iterations"], purpose=mark["plan"]["purpose"],
        wall_seconds=state.contract["wall_seconds"], closed=bool(endings) or expired or historical,
        reason=reason,
        recommendation=recommendation, requires_review=bool(recommendation),
        extension=extension,
        extension_from=policy.MAX_ITERATIONS if state.contract.get("extension_of") else None,
    )


def _next_child(current, ledger, state, context, decision):
    from diffeoforge import pilot_adaptive_native as native
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided

    seed = decision["seed"]["reference"]
    seed_snapshot = _snapshot(seed)
    field = native.inspect_field(seed_snapshot, seed["candidate_id"])
    if field["field_sha256"] != decision["seed"]["field_sha256"]:
        raise ValueError("Adaptive retained field changed before preparing its successor")
    args = {
        key: copy.deepcopy(value)
        for key, value in context.items()
        if key
        not in {
            "source_directory",
            "source_manifest_sha256",
            "initial_previous_directory",
            "seed_reference",
            "extension_offer",
        }
    }
    source_root = Path(context["source_directory"])
    if sha256_file(source_root / "study.json") != context["source_manifest_sha256"]:
        raise ValueError("Adaptive pilot source changed")
    args.update(
        source=study.load_reference_calibration_study(source_root),
        previous=current,
        destination_parent=ledger.parent,
        values=copy.deepcopy(seed["values"]),
        methods=(seed["method"],),
    )
    strategy = args["strategy"]
    previous_info = _record(current)["guided"]
    args["spent"] = previous_info["screen_trials_spent"]
    for key in ("optimization", "regional_continuation", "adaptive_fit"):
        strategy.pop(key, None)
    strategy.update(
        anchor=copy.deepcopy(context["seed_reference"]),
        baseline=copy.deepcopy(seed),
        control_basis=copy.deepcopy(seed),
        previous=dict(
            directory=str(current.study_directory),
            manifest_sha256=sha256_file(current.study_directory / "study.json"),
        ),
        preference=None,
    )
    args["history"] = [
        *previous_info["history"],
        dict(**strategy["previous"], outcome="bounded_" + decision["purpose"]),
    ]
    basis = _basis(field["control_points_path"], seed["values"]["initial_control_point_spacing"])
    relation = "unchanged"
    if decision["purpose"] in _PROBES:
        recipe = copy.deepcopy(context["strategy"]["regional_recipe"])
        recipe.update(residual=True, phase="adaptive_probe")
        for key in ("protection_reference", "control_support"):
            recipe.pop(key, None)
        strategy["regional_recipe"] = recipe
        if decision["purpose"] == "cp_probe":
            relation = "nested"
        elif decision["purpose"] == "motion_probe":
            cp_stage = next(row for row in state.stages if row["plan"]["purpose"] == "cp_probe")
            cp_snapshot = _snapshot(cp_stage["receipt"]["reference"])
            cp_info = _record(cp_snapshot)["controls"]
            basis = _basis(cp_snapshot.study_directory / cp_info["copy"], cp_info["spacing"])
            args["values"]["deformation_kernel_width"] *= 0.7
        args["values"]["initial_control_point_spacing"] = basis["spacing"]
    else:
        from diffeoforge.pilot_common_model import EFFORT_VERSION
        from diffeoforge.pilot_iteration_accounting import branch_total
        from diffeoforge.regional_continuation import VERSION

        frozen = field["bundle"]
        candidate = next(
            row for row in seed_snapshot.candidates if row.candidate_id == seed["candidate_id"]
        )
        strategy["regional_recipe"] = copy.deepcopy(
            _record(seed_snapshot)["guided"]["strategy"]["regional_recipe"]
        )
        strategy["regional_continuation"] = dict(
            version=VERSION,
            reference=copy.deepcopy(seed),
            marks=copy.deepcopy(args["feedback"]["regions"]),
            objective_sha256=frozen["objective_sha256"],
            source_seals=frozen["seals"],
            accepted_parameter_sha256=frozen["accepted_parameter_sha256"],
            guard_objective_fingerprint=frozen["guard_objective_fingerprint"],
            optimizer_history="new; exact accepted field, no old optimizer memory",
            anatomical_approval=False,
        )
        strategy["optimization"] = dict(
            version=EFFORT_VERSION,
            reference=copy.deepcopy(seed),
            iterations=decision["iterations"],
            initial_iterations=branch_total(seed_snapshot, candidate),
            common_model=False,
        )
    strategy["adaptive_fit"] = _marker(
        ledger, state, decision, context["seed_reference"], basis, relation
    )
    return guided._batch(**args)


def _finish(snapshot, state, ledger, reason, callback):
    from diffeoforge import reference_calibration_study as study

    payload = dict(
        best_reference=copy.deepcopy(state.best_feasible["reference"]),
        spent=state.spent,
        total=state.contract["total_iterations"],
        reason=reason,
        requires_review=True,
        anatomical_approval=False,
        ledger=str(ledger),
        contract_sha256=policy.digest(state.contract),
        held_iterations=state.held,
    )
    existing = [
        row
        for row in study._load_events(snapshot.study_directory)
        if row["event"] == "adaptive_fit_finished"
    ]
    if not existing:
        study._append_event(snapshot.study_directory, "adaptive_fit_finished", payload)
    if callback:
        callback(dict(event="adaptive_fit_finished", snapshot=snapshot, **payload))
    return study.load_reference_calibration_study(snapshot.study_directory)


def run(runner, event_callback=None, *, candidate_ids=None):
    """Run sealed children serially with their normal native/QC/cancellation route."""
    from diffeoforge import pilot_adaptive_native as native
    from diffeoforge import reference_calibration_study as study

    current = study.load_reference_calibration_study(runner.study_directory)
    mark = marker(_record(current))
    ledger, state, context = _context(mark)
    if any(
        row["event"] == "adaptive_fit_finished"
        for row in study._load_events(current.study_directory)
    ):
        return current
    if state.stages and mark["plan"]["stage_id"] != state.stages[-1]["stage_id"]:
        if mark["plan"] != policy.next_decision(state):
            raise ValueError("Reopen the latest adaptive child; this stage is historical")
    if candidate_ids is not None and candidate_ids != {current.candidates[0].candidate_id}:
        raise ValueError("A bounded action cannot dispatch a different candidate subset")
    old_flag = getattr(runner, "_bounded_adaptive_dispatch", False)
    runner._bounded_adaptive_dispatch = True
    deadline = threading.Timer(max(0, state.deadline - time.time()), runner.request_cancel)
    deadline.daemon = True
    deadline.start()
    try:
        while True:
            state = policy.load_ledger(ledger)
            mark = marker(_record(current))
            if runner._cancel_requested:
                return _finish(
                    current,
                    state,
                    ledger,
                    "Stopped by cancellation or the deadline; retained field needs review.",
                    event_callback,
                )
            if state.active and state.active["stage_id"] != mark["plan"]["stage_id"]:
                raise ValueError("Another unresolved adaptive child still holds the action budget")
            candidate = current.candidates[0]
            if candidate.status == "pending" and candidate.attempts == 0:
                authorize_launch(
                    current.study_directory,
                    study._verify_manifest(current.study_directory),
                    candidate.candidate_id,
                )
                state = policy.load_ledger(ledger)
                if event_callback:
                    event_callback(
                        dict(
                            event="bounded_adaptive_progress",
                            snapshot=current,
                            purpose=mark["plan"]["purpose"],
                            spent=state.spent,
                            total=state.contract["total_iterations"],
                            message="Running a sealed regional stage within the shared allowance.",
                        )
                    )
                current = runner.run_current_stage(
                    event_callback=event_callback, candidate_ids={candidate.candidate_id}
                )
                candidate = current.candidates[0]
            state = policy.load_ledger(ledger)
            active = state.active
            if active:
                if candidate.status != "completed":
                    return _finish(
                        current,
                        state,
                        ledger,
                        "Native or QC evidence is incomplete; the reservation remains held. "
                        "Review the retained field.",
                        event_callback,
                    )
                try:
                    receipt = native.stage_receipt(current, candidate.candidate_id, state.contract)
                except (OSError, ValueError) as error:
                    return _finish(
                        current,
                        state,
                        ledger,
                        "Completed-child evidence could not be verified; its reservation "
                        "remains held. " + str(error)[:1000],
                        event_callback,
                    )
                receipt["reference"] = _reference(current, candidate.candidate_id)
                state = policy.complete_stage(
                    ledger,
                    active["stage_id"],
                    receipt,
                    request_id="complete-" + active["stage_id"],
                    expected_head=state.head,
                )
            decision = policy.next_decision(state)
            if decision["kind"] != "stage":
                return _finish(current, state, ledger, decision["reason"], event_callback)
            try:
                current = _next_child(current, ledger, state, context, decision)
            except (OSError, ValueError, InterruptedError) as error:
                # Preparation can refuse an unsupported complete basis or an
                # unresolved frame. It spent no new optimizer allowance and
                # must not replace the last qualified field with a dead end.
                return _finish(current, state, ledger,
                    "The next controlled stage could not be prepared. Retained fields "
                    "and partial preparation evidence stay saved; no fallback ran. "
                    + str(error)[:1000], event_callback)
            runner.study_directory = current.study_directory
    finally:
        deadline.cancel()
        runner._bounded_adaptive_dispatch = old_flag

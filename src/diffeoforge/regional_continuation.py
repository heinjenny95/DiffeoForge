"""Explicit same-objective numerical successors; never restore optimizer history.

Only newly guarded, inspected, finite capped regional fields qualify. Historical
unguarded fields retain their existing interpretation and are never promoted by
an inferred or untrusted stop. This module prepares files only; it cannot fit.
"""

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import numpy as np

from diffeoforge.mesh import sha256_file

VERSION = "regional-numerical-successor-v1"
GUARD = dict(version="new-regional-c5-v1", scope="new_single_specimen_probe", recovery="none")


def _json(path):
    def invalid(value):
        raise ValueError("Nonfinite JSON in numerical evidence: " + value)

    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=invalid)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _key(array):
    return hashlib.sha256(
        str(array.shape).encode() + array.dtype.str.encode() + array.tobytes()
    ).hexdigest()


def physics(config):
    """Exclude only coefficient initialization/path and the NEW iteration allowance."""
    model = copy.deepcopy(config["model"])
    for name in ("initial_control_points", "initial_momenta", "initial_momenta_subjects"):
        model["deformation"].pop(name, None)
    optimization = copy.deepcopy(config["optimization"])
    optimization.pop("max_iterations", None)
    return dict(model=model, optimization=optimization, runtime=config["runtime"])


def bundle(run):
    """Recheck prior actual staged geometry, accepted coefficients and input basis."""
    from diffeoforge.regional_evaluation import field_inputs
    from diffeoforge.regional_fit import assets, read_plan

    run = Path(run).resolve()
    inputs = field_inputs(run, None)
    config = inputs.run_report.manifest["effective_config"]
    provenance = config["project"].get("parameter_provenance", {})
    if (
        provenance.get("finite_accepted_guard") != GUARD
        or len(inputs.subject_labels) != 1
        or config["optimization"]["method"] != "lbfgs"
        or not config["optimization"]["freeze_template"]
        or not config["optimization"]["freeze_control_points"]
    ):
        raise ValueError("Same-objective continuation needs a newly guarded frozen singleton")
    declaration = provenance.get("regional_fit")
    if not declaration:
        raise ValueError("Same-objective continuation needs a bound regional objective")
    staged = run / "input/regional/plan.json"
    if sha256_file(staged) != declaration["sha256"]:
        raise ValueError("The actual staged regional plan differs from its declaration")
    bound_config = copy.deepcopy(config)
    bound_config["project"]["parameter_provenance"]["regional_fit"] = dict(
        declaration, manifest=str(staged)
    )
    plan = read_plan(bound_config)
    guard = run / "output/numerical-guard"
    if (guard / "violation.json").exists():
        raise ValueError("A failed guard cannot authorize numerical recovery")
    session = _json(guard / "session.json")
    native = session.get("provenance", {})
    basis = native.get("actual_control_basis", {})
    cp = inputs.control_points
    if (
        cp.dtype != np.dtype("float64")
        or not np.isfinite(cp).all()
        or basis.get("shape") != list(cp.shape)
        or basis.get("dtype") != cp.dtype.str
        or basis.get("sha256") != hashlib.sha256(cp.tobytes()).hexdigest()
        or basis.get("basis") != "staged_control_points"
        or native.get("scope") != GUARD
        or not isinstance(native.get("objective_fingerprint"), str)
    ):
        raise ValueError("Exact original native input control basis is not bound")
    events = [
        _json_line(line)
        for line in (guard / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    evaluations, accepted, exports, finals, returned = {}, [], [], [], []
    for event in events:
        kind = event["kind"]
        if kind == "terminal_violation":
            raise ValueError("A terminal numerical violation prevents continuation")
        if kind == "objective_evaluation":
            if (
                event.get("objective_finite") is not True
                or event.get("gradient_finite") is not True
                or event.get("objective_fingerprint") != native["objective_fingerprint"]
                or not math.isfinite(float.fromhex(event["f_hex"]))
            ):
                raise ValueError("Nonfinite or changed-objective numerical evidence")
            if event["evaluation_id"] in evaluations:
                raise ValueError("Duplicate objective evaluation identity")
            evaluations[event["evaluation_id"]] = event
        elif kind in {"initial_accepted", "accepted_callback"}:
            evaluation = evaluations.get(event["evaluation_reference"])
            if (
                not evaluation
                or event.get("gradient_finite") is not True
                or event["parameter_sha256"] != evaluation["parameter_sha256"]
                or (accepted and float.fromhex(evaluation["f_hex"]) > accepted[-1]["f"])
            ):
                raise ValueError("Accepted state is unbound, nonfinite or regressed")
            accepted.append(dict(event, f=float.fromhex(evaluation["f_hex"])))
        elif kind == "native_export_parameter_binding" and not event.get("internal_callback"):
            exports.append(event)
        elif kind == "final_result_bound_to_accepted_evaluation":
            finals.append(event)
        elif kind == "native_update_returned_bound_to_accepted":
            returned.append(event)
    if not accepted or not exports or not (finals or returned):
        raise ValueError("Missing final finite accepted/export binding")
    final_key = accepted[-1]["parameter_sha256"]
    final_evaluation = accepted[-1]["evaluation_reference"]
    if (
        exports[-1]["parameter_sha256"] != final_key
        or exports[-1]["evaluation_reference"] != final_evaluation
        or any(
            event["parameter_sha256"] != final_key
            or event["evaluation_reference"] != final_evaluation
            for event in [*finals[-1:], *returned[-1:]]
        )
    ):
        raise ValueError("Final export is not the last finite accepted field")
    result = _json(run / "result.json")
    cap = config["optimization"]["max_iterations"]
    log = (run / "logs/deformetrica.log").read_text(errors="replace")
    iterations = re.findall(r"Iteration:\s*(\d+)", log)
    if (
        result.get("status") != "completed"
        or type(result.get("return_code")) is not int
        or result.get("return_code") != 0
        or result.get("execution_error") is not None
        or type(cap) is not int
        or cap < 1
        or not re.search(r"STOP:\s*TOTAL\s+NO\.\s*of\s+ITERATIONS\s+EXCEEDS\s+LIMIT", log, re.I)
        or not iterations
        or int(iterations[-1]) < cap
        or re.search(
            r"tolerance threshold met|number of line search loops exceeded|"
            r"Traceback \(most recent call last\)|FloatingPointError:|RuntimeError:",
            log,
            re.I,
        )
    ):
        raise ValueError(
            "Only a normal completed explicit native maximum-iteration stop can continue"
        )
    if returned and (
        returned[-1].get("original_update_returned_normally") is not True
        or type(returned[-1].get("configured_max_iterations")) is not int
        or returned[-1].get("configured_max_iterations") != cap
        or returned[-1].get("native_iteration") != accepted[-1]["native_iteration"]
    ):
        raise ValueError("Normal native update return/cap binding differs from accepted state")
    pointer = _json(guard / "best-latest.json")
    folder = _snapshot_folder(guard, pointer["directory"])
    if sha256_file(folder / "receipt.json") != pointer["receipt_sha256"]:
        raise ValueError("Accepted snapshot receipt changed")
    receipt = _json(folder / "receipt.json")
    for name, row in receipt["files"].items():
        if (
            Path(name).name != name
            or (folder / name).stat().st_size != row["bytes"]
            or sha256_file(folder / name) != row["sha256"]
        ):
            raise ValueError("Accepted snapshot content changed")
    x = np.load(folder / "parameters.npy", allow_pickle=False)
    gradient = np.load(folder / "gradient.npy", allow_pickle=False)
    if (
        x.dtype != np.dtype("float64")
        or x.shape != (cp.size,)
        or gradient.dtype != x.dtype
        or gradient.shape != x.shape
        or not np.isfinite(x).all()
        or not np.isfinite(gradient).all()
        or _key(x) != final_key
        or receipt["parameter_sha256"] != final_key
        or receipt["f_hex"] != float(accepted[-1]["f"]).hex()
        or hashlib.sha256(gradient.tobytes()).hexdigest() != receipt["gradient_sha256"]
        or not np.array_equal(inputs.momenta.ravel().view(np.uint64), x.view(np.uint64))
    ):
        raise ValueError("Accepted seed is not exactly the inspected exported field")
    from diffeoforge.reference_guarded_checkpoint import read_guarded_checkpoint

    checkpoint = result.get("checkpoint") or {}
    if (
        checkpoint.get("available") is not True
        or checkpoint.get("path") != "output/deformetrica-state.p"
    ):
        raise ValueError("Normal native final checkpoint is not bound")
    final_checkpoint = run / checkpoint["path"]
    if final_checkpoint.stat().st_size != checkpoint.get("bytes"):
        raise ValueError("Normal native final checkpoint size changed")
    for path, digest in [
        (final_checkpoint, checkpoint["sha256"]),
        (folder / "native-state.p", receipt["files"]["native-state.p"]["sha256"]),
    ]:
        saved = read_guarded_checkpoint(
            path, values=x.size, iteration=accepted[-1]["native_iteration"], expected_sha256=digest
        )
        if not np.array_equal(saved.parameters.view(np.uint64), x.view(np.uint64)):
            raise ValueError("Native checkpoint parameters differ from the accepted field")
    files = [
        run / name
        for name in (
            "manifest.json",
            "result.json",
            "output-inventory.json",
            "engine/model.xml",
            "engine/optimization_parameters.xml",
            "engine/data_set.xml",
        )
    ]
    files += [
        inputs.control_points_path,
        inputs.momenta_path,
        final_checkpoint,
        run / "logs/deformetrica.log",
        guard / "session.json",
        guard / "events.jsonl",
        guard / "best-latest.json",
        folder / "receipt.json",
    ]
    files += [folder / name for name in receipt["files"]]
    files += [source for source, _, _ in assets(bound_config)]
    seals = {str(path): sha256_file(path) for path in files}
    identity = dict(
        physics=physics(config), staged_plan_sha256=sha256_file(staged), actual_control_basis=basis
    )
    return dict(
        config=config,
        plan=plan,
        inputs=inputs,
        accepted=x.reshape(1, len(cp), 3),
        assets=assets(bound_config),
        seals=seals,
        objective_sha256=_digest(identity),
        guard_objective_fingerprint=native["objective_fingerprint"],
        accepted_parameter_sha256=final_key,
        accepted_objective_progress=accepted[-1]["f"] < accepted[0]["f"],
        accepted_gradient_nonzero=bool(np.any(gradient != 0)),
        last_logged_native_iteration=int(iterations[-1]),
        accepted_native_iteration=accepted[-1]["native_iteration"],
    )


def _snapshot_folder(guard, declared):
    """Confine a native Windows/WSL pointer to its SAME existing guarded folder."""
    text = str(declared).replace("\\", "/").rstrip("/")
    name = text.rsplit("/", 1)[-1]
    if not re.fullmatch(r"best-[0-9]{4,}", name):
        raise ValueError("Accepted snapshot name is outside the guarded schema")
    folder = (guard / name).resolve()
    expected = str(folder).replace("\\", "/")
    aliases = {expected.casefold()}
    windows = PureWindowsPath(expected)
    if re.fullmatch(r"[A-Za-z]:", windows.drive):
        aliases.add(
            ("/mnt/" + windows.drive[0].lower() + "/" + "/".join(windows.parts[1:])).casefold()
        )
    if folder.parent != guard.resolve() or text.casefold() not in aliases:
        raise ValueError("Accepted snapshot leaves the guarded run")
    return folder


def _json_line(line):
    return json.loads(
        line,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite event: " + value)),
    )


def _proposal(snapshot, identifier, data):
    """Return an eligible numerical proposal, or None without changing old flows."""
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.guided_progress import iteration_limited
    from diffeoforge.reference_calibration_study import calibration_candidate_run_directory

    info = guided.record(snapshot)
    recipe = (info.get("strategy") or {}).get("regional_recipe")
    current, ref = data["current"], data.get("current_reference")
    feedback = (data["context"].get("feedback", {}).get(identifier) or {}).get("feedback") or {}
    previous_marks = (info.get("feedback") or {}).get("regions")
    marks = data["regions"]
    if (
        not recipe
        or not ref
        or getattr(snapshot, "visual_reviews", {}).get(identifier) is True
        or snapshot.plan.pilot_subject_count != 1
        or feedback.get("outcome") not in {"same", "better"}
        or not iteration_limited(current)
        or not marks
        or previous_marks != marks
    ):
        return None
    # Historical unguarded runs need no field import or mesh-derived report work
    # merely to discover that they have no trusted continuation protocol.
    from diffeoforge.config import load_config

    config = load_config(current.config_path)
    if config["project"].get("parameter_provenance", {}).get("finite_accepted_guard") != GUARD:
        return None
    row = (
        (current.metrics or {})
        .get("attachment_comparison", {})
        .get("subjects", {})
        .get(ref["target"], {})
    )
    quality = row.get("regional_quality", {})
    if (
        row.get("refinement_guard", {}).get("severe") is True
        or quality.get("marked_regions") != marks
        or quality.get("outside_preserved") is not True
        or quality.get("shape_preserved") is not True
    ):
        return None
    try:
        frozen = bundle(calibration_candidate_run_directory(current))
    except (KeyError, ValueError, OSError):
        return None
    if (
        current.metrics["maximum_iterations"] != frozen["config"]["optimization"]["max_iterations"]
        or current.metrics["final_iteration"] != frozen["last_logged_native_iteration"]
        or frozen["accepted_native_iteration"] < current.metrics["maximum_iterations"]
        or not frozen["accepted_objective_progress"]
        or not frozen["accepted_gradient_nonzero"]
    ):
        return None
    marker = dict(
        version=VERSION,
        reference=ref,
        marks=copy.deepcopy(marks),
        objective_sha256=frozen["objective_sha256"],
        source_seals=frozen["seals"],
        accepted_parameter_sha256=frozen["accepted_parameter_sha256"],
        guard_objective_fingerprint=frozen["guard_objective_fingerprint"],
        optimizer_history="new; previous SciPy Hessian/line-search memory is not restored",
        anatomical_approval=False,
    )
    return dict(
        goal="optimize",
        title="Optimize longer with the same regional settings",
        reason="The finite fit stopped at its iteration limit. Continue the same original "
        "objective, marked areas, incoming geometry, prefix and exact control basis from "
        "the inspected accepted field. This is a new optimizer history and needs fresh review.",
        available=True,
        blocked_reason="",
        regions=marks,
        trials=1,
        target=ref["target"],
        values=dict(ref["values"]),
        method=ref["method"],
        anchor=data["anchor"] or ref,
        initialization_reference=ref,
        initialization="learned",
        regional_recipe=copy.deepcopy(recipe),
        regional_continuation=marker,
        numerical_extension=True,
        optimization_iterations=current.metrics["maximum_iterations"] * 2,
        remaining_checks=max(0, len(info["pilot_order"]) - 1),
        hypothesis_count=(info.get("strategy") or {}).get("hypothesis_count", 0),
        contrast_level=0,
        response_evidence=[],
        from_base=False,
    )


@dataclass(frozen=True)
class _Preview:
    """Immutable presentation evidence, owned only by one inputs() operation."""

    binding: str
    payload: str


def _preview_binding(snapshot, identifier, data):
    from diffeoforge import reference_guided_pilot as guided

    info = guided.record(snapshot)
    return _digest(
        dict(
            identifier=identifier,
            current_reference=data.get("current_reference"),
            regions=data["regions"],
            feedback=(data["context"].get("feedback", {}).get(identifier) or {}).get("feedback"),
            recipe=(info.get("strategy") or {}).get("regional_recipe"),
            previous_marks=info.get("feedback"),
            suitable=getattr(snapshot, "visual_reviews", {}).get(identifier),
        )
    )


def prepare_preview(snapshot, identifier, data):
    """Verify at most once here; this value is never an authorization cache."""
    result = _proposal(snapshot, identifier, data)
    return _Preview(
        _preview_binding(snapshot, identifier, data),
        json.dumps(result, sort_keys=True, allow_nan=False),
    )


def proposal(snapshot, identifier, data, *, symptom=None):
    """Reuse one read-only preview, or verify direct calls with no preview input.

    Actual transition code calls inputs() again; bind/configure also independently
    re-read all scientific evidence. This object is neither persisted nor shared
    across operations. Returning a fresh decoded value protects sibling options
    from one option's presentation edits.
    """
    from diffeoforge import reference_guided_pilot as guided

    recipe = (guided.record(snapshot).get("strategy") or {}).get("regional_recipe") or {}
    if symptom not in {None, "unsure", recipe.get("symptom")}:
        return None
    preview = data.get("_regional_continuation_preview")
    if isinstance(preview, _Preview):
        if preview.binding != _preview_binding(snapshot, identifier, data):
            return None
        return json.loads(preview.payload)
    return _proposal(snapshot, identifier, data)


def marker(record):
    return (record.get("guided", {}).get("strategy") or {}).get("regional_continuation")


def bind(root, manifest, record):
    """Copy the actual old objective, never generate a finer mesh/new recipe/basis."""
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_calibration_study import (
        _copy_bound,
        calibration_candidate_run_directory,
    )
    from diffeoforge.reference_pca_deformations import _write_momenta

    continuation = marker(record)
    if not continuation:
        return record
    ref = continuation["reference"]
    parent = verify_reference(ref)
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    run = calibration_candidate_run_directory(candidate)
    frozen = bundle(run)
    from diffeoforge import reference_guided_pilot as guided

    previous_recipe = (guided.record(parent).get("strategy") or {}).get("regional_recipe")
    if (
        continuation["version"] != VERSION
        or continuation["anatomical_approval"] is not False
        or continuation["objective_sha256"] != frozen["objective_sha256"]
        or continuation["source_seals"] != frozen["seals"]
        or continuation["accepted_parameter_sha256"] != frozen["accepted_parameter_sha256"]
        or record["guided"]["feedback"]["regions"] != continuation["marks"]
        or record["refinement"]["reference"] != ref
        or record["guided"]["strategy"].get("regional_recipe") != previous_recipe
        or manifest["plan"]["baseline_effective_values"] != ref["values"]
    ):
        raise ValueError("Regional continuation marks/objective/accepted state changed")
    directory = Path(root) / "regional-continuation-objective"
    directory.mkdir(exist_ok=False)
    for source, staged, digest in frozen["assets"]:
        _copy_bound(source, directory / staged.name, digest)
    inputs = frozen["inputs"]
    cp, mp = Path(root) / "continuation-controls.txt", Path(root) / "continuation-momenta.txt"
    _copy_bound(inputs.control_points_path, cp, sha256_file(inputs.control_points_path))
    _write_momenta(mp, frozen["accepted"])
    from diffeoforge.reference_pca import read_deformetrica_momenta

    if not np.array_equal(
        read_deformetrica_momenta(mp, allow_singleton=True).view(np.uint64),
        frozen["accepted"].view(np.uint64),
    ):
        raise ValueError("Text seed serialization changed accepted coefficient bits")
    declaration = dict(
        frozen["config"]["project"]["parameter_provenance"]["regional_fit"],
        manifest=str(directory / "plan.json"),
    )
    return dict(
        record,
        controls=dict(
            copy=cp.name,
            sha256=sha256_file(cp),
            count=len(inputs.control_points),
            spacing=ref["values"]["initial_control_point_spacing"],
        ),
        refinement=dict(
            record["refinement"],
            initialization="learned",
            reason=continuation["optimizer_history"],
            momenta=dict(copy=mp.name, sha256=sha256_file(mp)),
            source_run_sha256=sha256_file(run / "manifest.json"),
            regional_continuation=copy.deepcopy(continuation),
        ),
        regional_objective=declaration,
    )


def verify(root, manifest, record):
    continuation = marker(record)
    if not continuation:
        return
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_calibration_study import calibration_candidate_run_directory
    from diffeoforge.reference_pca import read_deformetrica_momenta
    from diffeoforge.regional_fit import read_plan

    parent = verify_reference(continuation["reference"])
    current = next(
        c for c in parent.candidates if c.candidate_id == continuation["reference"]["candidate_id"]
    )
    frozen = bundle(calibration_candidate_run_directory(current))
    from diffeoforge import reference_guided_pilot as guided

    previous_recipe = (guided.record(parent).get("strategy") or {}).get("regional_recipe")
    if (
        frozen["seals"] != continuation["source_seals"]
        or frozen["objective_sha256"] != continuation["objective_sha256"]
        or continuation["marks"] != record["guided"]["feedback"]["regions"]
        or record["refinement"].get("regional_continuation") != continuation
        or record["guided"]["strategy"].get("regional_recipe") != previous_recipe
        or sha256_file(Path(record["regional_objective"]["manifest"]))
        != frozen["config"]["project"]["parameter_provenance"]["regional_fit"]["sha256"]
    ):
        raise ValueError("Frozen same-objective numerical successor binding changed")
    read_plan(
        dict(project=dict(parameter_provenance=dict(regional_fit=record["regional_objective"])))
    )
    cp = np.loadtxt(Path(root) / record["controls"]["copy"], dtype=np.float64).reshape(-1, 3)
    mp = read_deformetrica_momenta(
        Path(root) / record["refinement"]["momenta"]["copy"], allow_singleton=True
    )
    if not np.array_equal(
        cp.view(np.uint64), frozen["inputs"].control_points.view(np.uint64)
    ) or not np.array_equal(mp.view(np.uint64), frozen["accepted"].view(np.uint64)):
        raise ValueError("Original basis or accepted coefficient bits changed")


def configure(config, record):
    """Final candidate hook: restore SAME numerical/scientific settings, only new cap/seed."""
    continuation = marker(record)
    if not continuation:
        return False
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_calibration_study import calibration_candidate_run_directory

    parent = verify_reference(continuation["reference"])
    candidate = next(
        c for c in parent.candidates if c.candidate_id == continuation["reference"]["candidate_id"]
    )
    frozen = bundle(calibration_candidate_run_directory(candidate))
    if (
        frozen["seals"] != continuation["source_seals"]
        or frozen["objective_sha256"] != continuation["objective_sha256"]
    ):
        raise ValueError("Continuation source changed before candidate configuration")
    old = frozen["config"]
    seeds = {
        key: config["model"]["deformation"][key]
        for key in ("initial_control_points", "initial_momenta", "initial_momenta_subjects")
    }
    config["model"] = copy.deepcopy(old["model"])
    config["model"]["deformation"].update(seeds)
    config["runtime"] = copy.deepcopy(old["runtime"])
    config["optimization"] = dict(
        copy.deepcopy(old["optimization"]), max_iterations=record["iterations"]
    )
    config["project"]["parameter_provenance"]["regional_fit"] = record["regional_objective"]
    config["project"]["parameter_provenance"]["finite_accepted_guard"] = copy.deepcopy(GUARD)
    if physics(config) != physics(old):
        raise ValueError("A numerical successor must retain the exact objective and integrator")
    return True

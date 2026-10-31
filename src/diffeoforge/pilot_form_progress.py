"""Retain individual shape decisions without inventing common-model coverage."""

from copy import deepcopy
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file

VERSION = "individual-form-progress-v1"


def marker(snapshot):
    result = (guided.record(snapshot).get("strategy") or {}).get("form_progress")
    for event in study._load_events(snapshot.study_directory):
        if event["event"] == "guided_form_reviews_saved":
            result = event["form_progress"]
    return deepcopy(result) if result else None


def _protocol(snapshot, identifier):
    from diffeoforge.guided_feedback import reference, verify_reference

    current = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    config = load_config(current.config_path)
    parent, ref, seen = snapshot, reference(snapshot, identifier), set()
    while parent.attachment_comparison.get("regional_objective"):
        key = ref["directory"], ref["candidate_id"]
        if key in seen:
            raise ValueError("Cyclic saved-field history")
        seen.add(key)
        ref = parent.attachment_comparison.get("refinement", {}).get("reference")
        if not ref:
            raise ValueError("A verified original-basis starting protocol is required")
        parent = verify_reference(ref)
        if guided.record(parent)["origin"] != guided.record(snapshot)["origin"]:
            raise ValueError("Original-basis protocol belongs to another cohort")
    if parent.plan.pilot_subject_count != 1:
        raise ValueError("Choose a saved single-form original-basis protocol")
    basis_candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    basis_config = load_config(basis_candidate.config_path)
    if not all(basis_config["optimization"][k]
               for k in ("freeze_template", "freeze_control_points")):
        raise ValueError("The original-basis protocol must keep template and controls fixed")
    return dict(reference=ref,
        integration={k: config["model"]["deformation"][k] for k in ("timepoints", "use_rk2")},
        precision=config["runtime"]["precision"],
        tolerance=config["optimization"]["convergence_tolerance"])


def compatible(row, protocol):
    from diffeoforge.guided_feedback import verify_reference

    parent = study.load_reference_calibration_study(Path(row["directory"]))
    basis = verify_reference(protocol["reference"])
    candidate = next(c for c in parent.candidates if c.candidate_id == row["candidate_id"])
    config = load_config(candidate.config_path)
    return (not parent.attachment_comparison.get("regional_objective")
        and parent.plan.pilot_subject_count == 1
        and row["method"] == protocol["reference"]["method"]
        and row["values"] == protocol["reference"]["values"]
        and all(config["optimization"][k] for k in ("freeze_template", "freeze_control_points"))
        and parent.attachment_comparison["controls"]["sha256"]
        == basis.attachment_comparison["controls"]["sha256"]
        and study._verify_manifest(parent.study_directory)["inputs"]["template"]["sha256"]
        == study._verify_manifest(basis.study_directory)["inputs"]["template"]["sha256"]
        and all(config["model"]["deformation"][k] == v
                for k, v in protocol["integration"].items())
        and config["runtime"]["precision"] == protocol["precision"]
        and config["optimization"]["convergence_tolerance"] == protocol["tolerance"])


def verify_marker(value, origin, pilot_order):
    from diffeoforge.guided_feedback import verify_reference

    if (value.get("version") != VERSION or value.get("stage") not in {"forms", "model"}
            or value.get("common_approval_created") is not False):
        raise ValueError("Invalid individual-form progress record")
    rows = value["reviews"]
    if len({r["filename"] for r in rows}) != len(rows):
        raise ValueError("Duplicate individual-form approval")
    guided.verify_approvals(rows)
    origin_review = value["origin_review"]
    guided.verify_approvals([origin_review])
    origin_snapshot = study.load_reference_calibration_study(Path(origin_review["directory"]))
    protocol = value["protocol"]
    if protocol != _protocol(origin_snapshot, origin_review["candidate_id"]):
        raise ValueError("The retained starting protocol or its original review changed")
    parent = verify_reference(protocol["reference"])
    if (parent.attachment_comparison.get("regional_objective")
            or parent.plan.pilot_subject_count != 1
            or guided.record(parent)["origin"] != origin):
        raise ValueError("Common starting protocol requires the verified original basis")
    for row in rows:
        saved = study.load_reference_calibration_study(Path(row["directory"]))
        if row["filename"] not in pilot_order or guided.record(saved)["origin"] != origin:
            raise ValueError("Individual-form approval belongs to another cohort")
    if (set(protocol["integration"]) != {"timepoints", "use_rk2"}
            or type(protocol["integration"]["timepoints"]) is not int
            or protocol["integration"]["timepoints"] < 2
            or type(protocol["integration"]["use_rk2"]) is not bool
            or protocol["precision"] not in {"float32", "float64"}
            or not 0 < protocol["tolerance"] <= 1):
        raise ValueError("Invalid retained numerical protocol")


def proposal(snapshot, identifier, context, *, model=False):
    row = guided._approved_record(snapshot, identifier)
    info = guided.record(snapshot)
    if snapshot.plan.pilot_subject_count != 1 or info["phase"] == "joint":
        raise ValueError("Review an individual form before continuing to another")
    saved = marker(snapshot)
    if saved:
        verify_marker(saved, info["origin"], info["pilot_order"])
    value = deepcopy(saved) if saved else dict(version=VERSION, reviews=[], origin_review=row,
                         protocol=_protocol(snapshot, identifier),
                         stage="forms", common_approval_created=False)
    if (saved and not snapshot.attachment_comparison.get("regional_objective")
            and not compatible(row, value["protocol"])):
        # As in ordinary pilot confirmation, explicitly choosing a new standard
        # fit chooses its shared starting settings. Old shapes stay saved; only
        # matching-model approvals can count towards the new joint check.
        value.update(origin_review=row, protocol=_protocol(snapshot, identifier))
    value["reviews"] = list({r["filename"]: r for r in [*value["reviews"], row]}.values())
    if model:
        value["stage"] = "model"
    candidates = [*info["approved"], *(r["approval"] for r in context["cases"]
                                      if r.get("approval")), row]
    common = list({r["filename"]: r for r in candidates
                   if compatible(r, value["protocol"])}.values())
    shapes = {r["filename"] for r in value["reviews"]} | {r["filename"] for r in common}
    covered = {r["filename"] for r in common} if value["stage"] == "model" else shapes
    order = info["pilot_order"]
    pos = order.index(info["target"])
    ordered = [*order[pos + 1:], *order[:pos + 1]]
    target = next((name for name in ordered if name not in covered), None)
    joint = len(common) == len(order)
    recorded = bool(saved and any(r == row for r in saved["reviews"]))
    if target is None and not joint and recorded and value["stage"] == "forms":
        # All shapes were explicitly saved; the next opt-in action checks the
        # common protocol. It never relabels regional approval as atlas coverage.
        return proposal(snapshot, identifier, context, model=True)
    return dict(available=True, target=target, marker=value, common=common,
                shapes=len(shapes), checked=len(common), total=len(order), joint=joint,
                action="form_model_check" if value["stage"] == "model" else "next_form",
                label="Prepare joint check" if joint else
                      "Prepare common-model check · " + target if value["stage"] == "model"
                      and target else "Use suitable fit → next pilot form · " + target
                      if target else "Save suitable fit → finish individual reviews")


def preview(snapshot, identifier, context):
    try:
        return proposal(snapshot, identifier, context)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return dict(available=False, reason=str(error))


def configure(config, value, cohort_method):
    from diffeoforge.reference_finite_accepted_guard import clear_runtime_markers

    config["project"]["parameter_provenance"].pop("regional_fit", None)
    clear_runtime_markers(config)
    config["optimization"]["method"] = cohort_method
    config["optimization"]["convergence_tolerance"] = value["protocol"]["tolerance"]
    config["model"]["deformation"].update(value["protocol"]["integration"])
    config["runtime"]["precision"] = value["protocol"]["precision"]


def verify(info, record, manifest, root):
    from diffeoforge.reference_attachment_comparison import ITERATIONS

    value = info["strategy"]["form_progress"]
    verify_marker(value, info["origin"], info["pilot_order"])
    if info.get("goal") not in {"next_form", "form_model_check"}:
        return
    protocol = value["protocol"]
    config = load_config(study._safe_study_path(root, manifest["source_config"]["copy"]))
    if (record.get("regional_objective") or record.get("refinement")
            or record["iterations"] != ITERATIONS
            or info["phase"] != "validate" or info["target"] in {
                r["filename"] for r in value["reviews"]} and value["stage"] == "forms"
            or info["strategy"].get("baseline") or info["strategy"].get("anchor")
            or info["strategy"].get("control_basis") != protocol["reference"]
            or manifest["plan"]["baseline_effective_values"] != protocol["reference"]["values"]
            or config["runtime"]["precision"] != protocol["precision"]
            or config["optimization"]["convergence_tolerance"] != protocol["tolerance"]
            or any(config["model"]["deformation"][k] != v
                   for k, v in protocol["integration"].items())):
        raise ValueError("Next-form check must retain its declared shared starting protocol")


def transition(snapshot, identifier, *, model=False):
    from diffeoforge.guided_strategy import state

    with study.calibration_verification_scope():
        snapshot = study.load_reference_calibration_study(snapshot.study_directory)
        info = guided.record(snapshot)
        proposed = proposal(snapshot, identifier, state(snapshot), model=model)
        value = proposed["marker"]
        if proposed["target"] is None and not proposed["joint"]:
            plan = None
        else:
            source, _ = guided._origin(snapshot.study_directory)
            strategy = dict(info.get("strategy") or {})
            for key in ("baseline", "anchor", "regional_recipe", "regional_continuation",
                        "optimization", "failure_parent_recovery", "shared_model_check",
                        "search_family"):
                strategy.pop(key, None)
            previous = dict(directory=str(snapshot.study_directory),
                manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST))
            strategy.update(form_progress=value, previous=previous, preference=None,
                            control_basis=value["protocol"]["reference"])
            plan = dict(source=source, previous=snapshot,
                phase="joint" if proposed["joint"] else "validate", target=proposed["target"],
                methods=(value["protocol"]["reference"]["method"],),
                values=value["protocol"]["reference"]["values"], approved=proposed["common"],
                history=[*info["history"],
                         dict(previous, outcome="adaptive_" + proposed["action"])],
                spent=info["screen_trials_spent"], strategy=strategy,
                goal=None if proposed["joint"] else proposed["action"], feedback=None)
    if plan is None:
        study._append_event(snapshot.study_directory, "guided_form_reviews_saved", dict(
            form_progress=value, anatomical_approval_created=False, optimizer_started=False))
        return study.load_reference_calibration_study(snapshot.study_directory)
    result = guided._batch(**plan)
    study._append_event(snapshot.study_directory, "guided_pilot_decision", dict(
        action="adaptive_" + proposed["action"], candidate_id=identifier,
        next_directory=str(result.study_directory),
        next_manifest_sha256=sha256_file(result.study_directory / study.STUDY_MANIFEST),
        anatomical_approval_created=False, optimizer_started=False))
    return result

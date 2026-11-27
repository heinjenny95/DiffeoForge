"""Bounded common-model contrasts initialized from a verified suitable individual."""

from copy import deepcopy
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.guided_density import controls_for
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_attachment_comparison import ITERATIONS

LEGACY_VERSION = "accepted-direct-common-start-v1"
VERSION = "accepted-direct-common-start-v2"
ACCEPTED_WARM_VERSIONS = {LEGACY_VERSION, VERSION}

_REVIEWABLE = {
    "no_new_intersection_flags": "surface intersections",
    "spatial_resolution_sufficient": "source-surface resolution",
}


def reviewed_warnings(candidate, target, *, regional):
    """A reviewed regional warning can qualify a starting field, never the result."""
    subject = (candidate.metrics or {}).get("attachment_comparison", {}).get(
        "subjects", {}).get(target, {})
    if (not subject or subject.get("warnings")
            or subject.get("refinement_guard", {}).get("severe")):
        return None
    if any(subject.get(key) and subject[key].get("numerical_selection_suitable") is not True
           for key in ("ordinary_quality", "cohort_quality")):
        return None
    if not regional:
        return []
    quality = subject.get("regional_quality") or {}
    protected = ("temporal_grid_stable", "explicit_fixed_preserved", "shape_preserved",
                 "transition_preserved", "outside_preserved")
    if quality.get("numerical_selection_suitable") is True:
        return None if any(quality.get(key) is False for key in (*protected, *_REVIEWABLE)) else []
    if (quality.get("version") != "regional-quality-v1"
            or quality.get("numerical_selection_suitable") is not False
            or any(quality.get(key) is not True for key in (*protected, "local_improved"))
            or any(type(quality.get(key)) is not bool for key in _REVIEWABLE)):
        return None
    warnings = [key for key in _REVIEWABLE if not quality[key]]
    return warnings or None


def seed_evidence(value, target, *, legacy=False):
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.pilot_common_basis import transferable_direct_field
    from diffeoforge.regional_fit import declaration

    row = next((r for r in value["reviews"] if r["filename"] == target), None)
    if not row:
        return None
    ref = dict(row)
    ref["target"] = ref.pop("filename")
    seed = verify_reference(ref)
    basis_ref = value["protocol"]["reference"]
    basis = verify_reference(basis_ref)
    seed_record, basis_record = seed.attachment_comparison, basis.attachment_comparison
    regional = bool(seed_record.get("regional_objective"))
    if ((legacy and not regional)
            or seed.plan.pilot_subject_count != 1
            or controls_for(seed_record, ref["candidate_id"])["sha256"]
            != controls_for(basis_record, basis_ref["candidate_id"])["sha256"]
            or ref["method"] != basis_ref["method"]
            or guided.record(seed)["origin"] != guided.record(basis)["origin"]
            or guided._approved_record(seed, ref["candidate_id"]) != row):
        return None
    candidate = next(c for c in seed.candidates if c.candidate_id == ref["candidate_id"])
    config = load_config(candidate.config_path)
    deformation = config["model"]["deformation"]
    if legacy:
        quality = (candidate.metrics.get("attachment_comparison", {}).get("subjects", {})
                   .get(target, {}).get("regional_quality", {}))
        warnings = [] if quality.get("numerical_selection_suitable") is True else None
    else:
        warnings = reviewed_warnings(candidate, target, regional=regional)
        if bool(declaration(config)) != regional:
            return None
    if (warnings is None or not transferable_direct_field(config)
            or config["runtime"]["precision"] != value["protocol"]["precision"]
            or any(deformation[k] != v for k, v in value["protocol"]["integration"].items())
            or any(ref["values"][k] != value["protocol"]["reference"]["values"][k]
                   for k in ("deformation_kernel_width", "initial_control_point_spacing"))
            or study._verify_manifest(seed.study_directory)["inputs"]["template"]["sha256"]
            != study._verify_manifest(basis.study_directory)["inputs"]["template"]["sha256"]):
        return None
    return dict(reference=ref, reviewed_warnings=warnings,
                test_number=guided.record(seed)["screen_trials_spent"])


def trials(snapshot, protocol, seed):
    result, seen = [], set()
    for entry in [*guided.record(snapshot)["history"], None]:
        parent = snapshot
        if entry:
            root = Path(entry["directory"])
            if sha256_file(root / study.STUDY_MANIFEST) != entry["manifest_sha256"]:
                raise ValueError("Common warm-start history changed")
            parent = study.load_reference_calibration_study(root)
        if parent.study_directory in seen:
            continue
        seen.add(parent.study_directory)
        marker = (guided.record(parent).get("strategy") or {}).get("common_basis_step") or {}
        if (marker.get("version") in ACCEPTED_WARM_VERSIONS and marker["protocol"] == protocol
                and marker["reference"] == seed):
            result.append((parent, marker["kind"]))
    return result


def values_for(protocol, kind):
    values = protocol["reference"]["values"]
    if kind == "warm":
        return values
    if kind == "detail":
        return guided.adjusted_values(values, "detail", conservative=True)
    raise ValueError("Unknown accepted-field common test")


def detail_warranted(diagnosis):
    return bool(diagnosis and diagnosis["local_losses"] and not diagnosis["warnings"])


def review_event(snapshot, candidate_id, event_hash=None):
    return next((e for e in reversed(study._load_events(snapshot.study_directory))
                 if e["event"] == "candidate_visual_review"
                 and e["candidate_id"] == candidate_id
                 and (event_hash is None or e["event_hash"] == event_hash)), None)


def preview(snapshot, value, target, seed, *, evidence=None):
    from diffeoforge.guided_feedback import reference
    from diffeoforge.pilot_common_diagnosis import diagnose

    history = trials(snapshot, value["protocol"], seed)
    base = dict(target=target, mode="accepted_warm", available=True, reference=seed,
                kind="warm",
                label="Test common settings from the accepted individual fit · " + target,
                reason="Start from this form's verified field on the same controls. "
                       "Test the shared surface objective for one bounded 120-step block.")
    if evidence:
        warnings = evidence["reviewed_warnings"]
        base.update(reviewed_warnings=warnings, test_number=evidence["test_number"],
                    reason=f"Start {target} from its approved Test {evidence['test_number']} "
                           "with its learned momenta on the same controls. Check the shared "
                           "whole-surface objective for up to 120 iterations.")
        if warnings:
            names = " and ".join(_REVIEWABLE[key] for key in warnings)
            base["reason"] += (f" The starting fit has warnings about {names}. "
                               "Review the new result and its independent checks.")
    if not history:
        return base
    last, kind = history[-1]
    candidate = last.candidates[0]
    if candidate.status in {"pending", "running"}:
        return dict(base, mode="prepared", available=False,
                    label="Complete the prepared accepted-field common test · " + target,
                    reason="This test already exists. Use its normal Run and review controls.")
    try:
        current = reference(last, candidate.candidate_id)
    except ValueError:
        return dict(base, mode="stalled", available=False,
                    label="Inspect the common test's technical result · " + target,
                    reason="Inspect its checks before choosing another numerical test.")
    if candidate.candidate_id not in last.visual_reviews:
        return dict(base, mode="review", reference=current,
                    label="Review saved accepted-field common test · " + target,
                    reason="Review this exact result against the accepted individual fit.")
    if last.visual_reviews[candidate.candidate_id] is True:
        return dict(base, mode="adopt" if kind == "detail" else "approved",
                    available=False, reference=current,
                    label="Use the reviewed common result · " + target,
                    reason="This result has your suitability decision. Use the next-form "
                           "or explicit common-settings adoption action.")
    measured = diagnose(snapshot, value, current)
    rejection = review_event(last, candidate.candidate_id) if kind == "warm" else None
    if rejection and rejection["approved"] is False and detail_warranted(measured):
        return dict(base, kind="detail", diagnosis=measured, review_hash=rejection["event_hash"],
                    label="Test finer surface matching from the accepted fit · " + target,
                    reason="The common objective lost local detail from the accepted start. "
                           "Test a finer attachment scale with the same field, controls, "
                           "optimizer and budget. A new review is required.")
    return dict(base, mode="stalled", available=False, reference=current, diagnosis=measured,
                label="Compare the remaining mismatch · " + target,
                reason="Inspect the remaining mismatch against the accepted individual fit. "
                       "This comparison gives no basis for another unchanged iteration block.")


def apply(plan, choice, protocol):
    seed = choice["reference"]
    kind = choice["kind"]
    plan["strategy"].update(baseline=seed, anchor=seed, control_basis=protocol["reference"],
        common_basis_step=dict(version=VERSION, reference=seed, protocol=deepcopy(protocol),
            kind=kind, additional_iterations=ITERATIONS, approval_transferred=False,
            reviewed_warnings=list(choice.get("reviewed_warnings", [])),
            review_hash=choice.get("review_hash")))
    plan.update(phase="refine", goal="form_model_check", values=values_for(protocol, kind))
    return plan


def verify(info, record, manifest, root):
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.guided_refinement import load_field
    from diffeoforge.pilot_form_progress import compatible

    strategy = info["strategy"]
    step, value = strategy["common_basis_step"], strategy["form_progress"]
    protocol, seed, kind = step["protocol"], step["reference"], step["kind"]
    legacy = step["version"] == LEGACY_VERSION
    evidence = seed_evidence(value, info["target"], legacy=legacy)
    if (value["stage"] != "model" or protocol != value["protocol"]
            or step["approval_transferred"] is not False
            or step["additional_iterations"] != ITERATIONS or record["iterations"] != ITERATIONS
            or info["phase"] != "refine" or info["goal"] != "form_model_check"
            or record.get("regional_objective")
            or strategy.get("baseline") != seed or strategy.get("anchor") != seed
            or strategy.get("control_basis") != protocol["reference"]
            or not evidence or evidence["reference"] != seed
            or (not legacy and step.get("reviewed_warnings") != evidence["reviewed_warnings"])
            or manifest["plan"]["baseline_effective_values"] != values_for(protocol, kind)
            or any(not compatible(r, protocol) for r in info["approved"])):
        raise ValueError("Common warm start must retain the accepted field and shared basis")
    parent = study.load_reference_calibration_study(strategy["previous"]["directory"])
    earlier = trials(parent, protocol, seed)
    if kind == "detail":
        if [name for _, name in earlier] != ["warm"]:
            raise ValueError("A detail contrast needs one prior common warm test")
        tested = earlier[0][0]
        candidate = tested.candidates[0]
        review_hash = step.get("review_hash")
        event = review_event(tested, candidate.candidate_id, review_hash)
        if not review_hash or not event or event["approved"] is not False:
            raise ValueError("A detail contrast needs a reviewed unsuitable warm test")
    elif earlier or step.get("review_hash") is not None:
        raise ValueError("This approved field already has a common warm test")
    config = load_config(study._safe_study_path(root, manifest["source_config"]["copy"]))
    original = study._verify_manifest(Path(info["origin"]))
    origin_config = load_config(study._safe_study_path(
        Path(info["origin"]), original["source_config"]["copy"]))
    source = verify_reference(seed)
    candidate = next(c for c in source.candidates if c.candidate_id == seed["candidate_id"])
    field = load_field(study.calibration_candidate_run_directory(candidate))
    bound = record["refinement"]
    if (bound["initialization"] != "learned" or bound["reference"] != seed
            or bound["momenta"]["sha256"] != sha256_file(field.momenta_path)
            or record["controls"]["sha256"] != controls_for(
                source.attachment_comparison, seed["candidate_id"])["sha256"]
            or config["runtime"]["precision"] != protocol["precision"]
            or config["optimization"]["convergence_tolerance"] != protocol["tolerance"]
            or any(config["model"]["deformation"][k] != v
                   for k, v in protocol["integration"].items())
            or any(config["optimization"][k] != origin_config["optimization"][k]
                   for k in ("method", "initial_step_size", "max_line_search_iterations"))):
        raise ValueError("Common warm start changed its field or optimization protocol")

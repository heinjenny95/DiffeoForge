"""Warm transfer to an explicitly adopted nested common basis, never approval transfer."""
from pathlib import Path

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file

LEGACY_VERSION = "nested-common-basis-step-v1"
VERSION = "retained-direct-common-basis-step-v2"


def _physics(config):
    from diffeoforge.pilot_common_model import physics

    result = physics(config)
    result["model"]["deformation"].pop("initial_control_point_spacing", None)
    return result


def field_physics(config):
    """Attachment/noise contrasts change the objective, not an unchanged ambient field."""
    result = _physics(config)
    result["model"].pop("noise_std", None)
    for key in ("kernel_width", "noise_std"):
        result["model"]["attachment"].pop(key, None)
    return result


def direct_field_physics(config):
    """A new optimizer may initialize from the same learned ambient field."""
    result = field_physics(config)
    result["optimization"].pop("method", None)
    return result


def transferable_direct_field(config):
    """Regional losses may learn a direct field; a residual is not the whole map."""
    from diffeoforge.regional_fit import read_plan

    plan = read_plan(config) or {}
    return bool(config["optimization"]["freeze_template"]
                and config["optimization"]["freeze_control_points"]
                and not plan.get("residual"))


def _prefix_basis(parent, shared):
    controls = parent.attachment_comparison["controls"]
    path = study._safe_study_path(parent.study_directory, controls["copy"])
    if sha256_file(path) != controls["sha256"]:
        raise ValueError("Retained control basis changed")
    source = np.loadtxt(path, ndmin=2)
    return len(source) < len(shared) and np.array_equal(shared[:len(source)], source)


def nested_source(basis, *, seen=None):
    from diffeoforge.guided_feedback import verify_reference

    seen = set() if seen is None else seen
    if basis.study_directory in seen:
        raise ValueError("Cyclic common-basis provenance")
    seen.add(basis.study_directory)
    record = basis.attachment_comparison
    if record.get("regional_objective"):
        return {}
    nested = record.get("refinement") or {}
    if nested.get("initialization") == "nested":
        return nested
    strategy = guided.record(basis).get("strategy") or {}
    capacity = strategy.get("common_capacity_request")
    if capacity:
        previous = verify_reference(capacity["protocol"]["reference"])
        return dict(initialization="nested", source_controls=previous.attachment_comparison[
            "controls"])
    step = strategy.get("common_candidate_step")
    ref = step["capacity_origin"] if step else nested.get("reference")
    if ref and nested.get("initialization") == "learned":
        parent = verify_reference(ref)
        if record["controls"]["sha256"] == parent.attachment_comparison["controls"]["sha256"]:
            return nested_source(parent, seen=seen)
    return {}


def preview(snapshot, target, protocol):
    from diffeoforge.guided_feedback import reference, verify_reference
    from diffeoforge.pilot_iteration_accounting import branch_total

    basis = verify_reference(protocol["reference"])
    nested = nested_source(basis)
    if nested.get("initialization") != "nested":
        return None
    info = guided.record(snapshot)
    active = (info.get("strategy") or {}).get("common_basis_step")
    if (active and info["target"] == target
            and any(c.status != "completed" for c in snapshot.candidates)):
        return dict(mode="prepared", available=False, target=target,
            label="Complete the prepared shared-basis check · " + target,
            reason="The warm shared-basis test is already prepared or running. "
                   "No duplicate is needed.")
    basis_candidate = next(c for c in basis.candidates
                           if c.candidate_id == protocol["reference"]["candidate_id"])
    expected = direct_field_physics(load_config(basis_candidate.config_path))
    row = basis.attachment_comparison["controls"]
    shared = np.loadtxt(study._safe_study_path(basis.study_directory, row["copy"]), ndmin=2)
    if sha256_file(study._safe_study_path(basis.study_directory, row["copy"])) != row["sha256"]:
        raise ValueError("Adopted shared control basis changed")
    value = (info.get("strategy") or {}).get("form_progress") or {}
    original = next((r for r in value.get("reviews", []) if r["filename"] == target), None)
    found, seen = [], set()
    for entry in [*info["history"], None]:
        parent = snapshot
        if entry:
            root = Path(entry["directory"])
            if sha256_file(root / study.STUDY_MANIFEST) != entry["manifest_sha256"]:
                raise ValueError("Shared-basis history changed")
            parent = study.load_reference_calibration_study(root)
        if parent.study_directory in seen:
            continue
        seen.add(parent.study_directory)
        other = guided.record(parent)
        if (other["origin"] != info["origin"] or other["target"] != target
                or not _prefix_basis(parent, shared)):
            continue
        for candidate in parent.candidates:
            try:
                ref = reference(parent, candidate.candidate_id)
                verify_reference(ref)
            except ValueError:
                continue
            config = load_config(candidate.config_path)
            if (ref["method"] == protocol["reference"]["method"]
                    and protocol["reference"]["values"]["initial_control_point_spacing"]
                    == ref["values"]["initial_control_point_spacing"] * .8
                    and transferable_direct_field(config)
                    and direct_field_physics(config) == expected):
                found.append((ref, parent, candidate))
    if not found:
        return None
    preferred = [item for item in found if original
                 and item[0]["directory"] == original["directory"]
                 and item[0]["candidate_id"] == original["candidate_id"]
                 and item[1].visual_reviews.get(item[2].candidate_id) is True]
    ref, parent, candidate = (preferred or found)[-1]
    return dict(mode="basis", available=True, target=target, reference=ref,
        additional_iterations=120, previous_iterations=branch_total(parent, candidate),
        label="Test common basis from this form's saved fit · 120-step budget · " + target,
        reason="Keep this form's own saved direct field on the explicitly adopted basis. "
               "Added controls start at zero; no cold restart or approval transfer. "
               "The new result needs review under the new common model.")


def apply(plan, choice, protocol):
    from copy import deepcopy

    if not choice["available"]:
        raise ValueError(choice["reason"])
    ref = choice["reference"]
    plan["strategy"].update(baseline=ref, anchor=ref,
        control_basis=protocol["reference"], initialization="nested",
        common_basis_step=dict(version=VERSION, reference=ref, protocol=deepcopy(protocol),
                               additional_iterations=120, approval_transferred=False,
                               initialization_only=True))
    plan.update(phase="refine", goal="density", values=protocol["reference"]["values"])
    return plan


def verify(info, record, manifest, root):
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge import pilot_common_warm_start

    marker = info["strategy"]["common_basis_step"]
    if marker["version"] == pilot_common_warm_start.VERSION:
        return pilot_common_warm_start.verify(info, record, manifest, root)
    ref, protocol = marker["reference"], marker["protocol"]
    seed = verify_reference(ref)
    basis = verify_reference(protocol["reference"])
    candidate = next(c for c in seed.candidates if c.candidate_id == ref["candidate_id"])
    previous = info["strategy"]["previous"]
    parent_snapshot = study.load_reference_calibration_study(Path(previous["directory"]))
    parent = guided.record(parent_snapshot)
    prior = parent["strategy"]["form_progress"]
    value = info["strategy"]["form_progress"]
    from diffeoforge.pilot_form_progress import compatible

    revised = prior["protocol"] != protocol
    first_common = prior["stage"] == "forms" and len(value["reviews"]) == len(info["pilot_order"])
    reviews = {r["filename"]: r for r in prior["reviews"]}
    if first_common:
        for c in parent_snapshot.candidates:
            if parent_snapshot.visual_reviews.get(c.candidate_id) is True:
                row = guided._approved_record(parent_snapshot, c.candidate_id)
                reviews[row["filename"]] = row
    approved_basis = basis.visual_reviews.get(protocol["reference"]["candidate_id"]) is True
    retained = {r["filename"]: r for r in info["approved"]}
    physics = _physics
    if marker["version"] == VERSION:
        if (marker.get("initialization_only") is not True
                or not transferable_direct_field(load_config(candidate.config_path))):
            raise ValueError("Only a complete direct field may initialize a new common fit")
        physics = direct_field_physics
    if (marker["version"] not in {LEGACY_VERSION, VERSION} or marker["additional_iterations"] != 120
            or marker["approval_transferred"] is not False or record["iterations"] != 120
            or info["goal"] != "density" or info["target"] != ref["target"]
            or record.get("regional_objective")
            or record.get("refinement", {}).get("initialization") != "nested"
            or record["refinement"]["reference"] != ref
            or record["controls"]["sha256"] != basis.attachment_comparison["controls"]["sha256"]
            or manifest["plan"]["baseline_effective_values"] != protocol["reference"]["values"]
            or value["reviews"] != list(reviews.values()) or protocol != value["protocol"]
            or not approved_basis
            or (revised and not first_common
                and basis.study_directory != parent_snapshot.study_directory)
            or any(not compatible(r, protocol) for r in info["approved"])
            or (not revised and any(retained.get(r["filename"]) != r for r in parent["approved"]))
            or guided.record(seed)["origin"] != info["origin"]
            or physics(load_config(candidate.config_path)) != physics(load_config(
                study._safe_study_path(root, manifest["source_config"]["copy"])))):
        raise ValueError("A nested common basis must keep this form's own field and approvals")

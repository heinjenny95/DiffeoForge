"""Warm transfer to an explicitly adopted nested common basis, never approval transfer."""
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file

VERSION = "nested-common-basis-step-v1"


def _physics(config):
    from diffeoforge.pilot_common_model import physics

    result = physics(config)
    result["model"]["deformation"].pop("initial_control_point_spacing", None)
    return result


def preview(snapshot, target, protocol):
    from diffeoforge.guided_feedback import reference, verify_reference
    from diffeoforge.pilot_iteration_accounting import branch_total

    basis = verify_reference(protocol["reference"])
    nested = basis.attachment_comparison.get("refinement") or {}
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
    expected = _physics(load_config(basis_candidate.config_path))
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
                or parent.attachment_comparison.get("regional_objective")
                or parent.attachment_comparison["controls"]["sha256"]
                != nested["source_controls"]["sha256"]):
            continue
        for candidate in parent.candidates:
            try:
                ref = reference(parent, candidate.candidate_id)
                verify_reference(ref)
            except ValueError:
                continue
            if (ref["method"] == protocol["reference"]["method"]
                    and _physics(load_config(candidate.config_path)) == expected):
                found.append((ref, parent, candidate))
    if not found:
        return None
    ref, parent, candidate = found[-1]
    return dict(mode="basis", available=True, target=target, reference=ref,
        additional_iterations=120, previous_iterations=branch_total(parent, candidate),
        label="Check new common basis from this form's saved field · +120 · " + target,
        reason="Keep this form's own saved field on the explicitly adopted nested basis. "
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
                               additional_iterations=120, approval_transferred=False))
    plan.update(phase="refine", goal="density", values=protocol["reference"]["values"])
    return plan


def verify(info, record, manifest, root):
    from diffeoforge.guided_feedback import verify_reference

    marker = info["strategy"]["common_basis_step"]
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
    if (marker["version"] != VERSION or marker["additional_iterations"] != 120
            or marker["approval_transferred"] is not False or record["iterations"] != 120
            or info["goal"] != "density" or info["target"] != ref["target"]
            or record.get("regional_objective")
            or record.get("refinement", {}).get("initialization") != "nested"
            or record["refinement"]["reference"] != ref
            or record["controls"]["sha256"] != basis.attachment_comparison["controls"]["sha256"]
            or value["reviews"] != list(reviews.values()) or protocol != value["protocol"]
            or not approved_basis
            or (revised and not first_common
                and basis.study_directory != parent_snapshot.study_directory)
            or any(not compatible(r, protocol) for r in info["approved"])
            or (not revised and any(retained.get(r["filename"]) != r for r in parent["approved"]))
            or guided.record(seed)["origin"] != info["origin"]
            or _physics(load_config(candidate.config_path)) != _physics(load_config(
                study._safe_study_path(root, manifest["source_config"]["copy"])))):
        raise ValueError("A nested common basis must keep this form's own field and approvals")

"""Locate the specimen's exact, verified saved surfaces for a read-only retention review."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.anatomy_retention import (
    RetentionStage,
    SurfaceEvidence,
    _check_cancelled,
    assess_stages,
)
from diffeoforge.guided_feedback import region_state, verify_reference
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_common_diagnosis import accepted_reference, comparison_regions
from diffeoforge.pilot_form_progress import marker
from diffeoforge.regional_evaluation import endpoint
from diffeoforge.result_report import collect_run_report

_LABELS = {"approved": "Approved individual", "transfer": "Shared starting field",
           "common": "After fitting the original", "pilot_joint": "Joint pilot",
           "atlas_start": "Full atlas before joint optimization", "atlas": "Final joint atlas"}


def _stage(key, surface=None, reason="", material_template=None):
    return RetentionStage(key, _LABELS[key], surface, reason, material_template)


def _template(snapshot):
    row = study._verify_manifest(snapshot.study_directory)["inputs"]["template"]
    return SurfaceEvidence(study._safe_study_path(snapshot.study_directory, row["copy"]),
                           row["sha256"])


def _candidate(snapshot, identifier):
    candidate = next((c for c in snapshot.candidates if c.candidate_id == identifier), None)
    if candidate is None or candidate.status != "completed":
        raise ValueError("This specimen needs a completed pilot fit for comparison")
    return candidate


def _original(snapshot, target):
    manifest = study._verify_manifest(snapshot.study_directory)
    rows = [r for r in manifest["inputs"]["subjects"] if r["filename"] == target]
    if len(rows) != 1:
        raise ValueError("Could not identify the same original pilot specimen")
    return SurfaceEvidence(study._safe_study_path(snapshot.study_directory, rows[0]["copy"]),
                           rows[0]["sha256"])


def _output(report, target):
    if report.result["status"] != "completed" or any(c.status == "fail" for c in report.checks):
        raise ValueError("The completed run and its output inventory could not be verified")
    obj = report.manifest["effective_config"]["model"]["object_id"]
    rows = [r for r in report.inventory
            if Path(r["path"]).name.endswith(f"__Reconstruction__{obj}__subject_{target}.vtk")]
    if len(rows) != 1:
        raise ValueError("Expected exactly one native reconstruction for this specimen")
    return SurfaceEvidence(study._safe_study_path(report.run_directory / "output", rows[0]["path"]),
                           rows[0]["sha256"])


def _surface(candidate, target, cancelled):
    _check_cancelled(cancelled)
    qualified = endpoint(candidate, subject=target)
    if qualified:
        from diffeoforge.reconstruction_material_lineage import from_evaluation

        row = candidate.metrics["attachment_comparison"]["subjects"][target]
        receipt, = [row[k]["evaluation"] for k in (
            "regional_quality", "ordinary_quality", "cohort_quality") if row.get(k)]
        lineage = from_evaluation(receipt, cancelled=cancelled or (lambda: False))
        return SurfaceEvidence(Path(qualified["path"]), qualified["sha256"]), lineage
    run = study.calibration_candidate_run_directory(candidate)
    return _output(collect_run_report(run), target), None


def approved_source(ref, cancelled=None):
    """Resolve the exact anatomical approval, including any verified complete residual endpoint."""
    parent = verify_reference(ref)
    cid, target = ref["candidate_id"], ref["target"]
    if parent.plan.pilot_subject_count != 1 or parent.visual_reviews.get(cid) is not True:
        raise ValueError("Select the recorded approved individual fit for this specimen")
    surface, lineage = _surface(_candidate(parent, cid), target, cancelled)
    marks, _ = region_state(parent, cid, target)
    approved = _stage("approved", surface, material_template=_template(parent))
    return _original(parent, target), approved, marks, lineage


def _flow_settings(config):
    """Scientific settings for shooting fixed coefficients, before optimizer steps."""
    from diffeoforge.pilot_common_basis import direct_field_physics

    shared = direct_field_physics(config)
    model = shared["model"]
    return (model["type"], model["dimension"], model["object_id"], model["deformation"],
            shared["runtime"], config["optimization"]["downsampling_factor"])


def _starting_field(snapshot, candidate, target, approved_ref):
    """Identify a bound direct field's native source export, independently of display proxies."""
    from diffeoforge.config import load_config
    from diffeoforge.guided_density import refinement_for
    from diffeoforge.pilot_common_basis import transferable_direct_field
    from diffeoforge.pilot_common_projection_child import mark

    record = snapshot.attachment_comparison
    request = mark(record)
    if request:
        from diffeoforge.pilot_common_projection import verified_endpoint

        projection = verified_endpoint(request["directory"], "projection")
        if (projection["approved_reference"] != approved_ref or projection["target"] != target
                or projection["original_sha256"] != _original(snapshot, target).sha256
                or projection["template_sha256"] != _template(snapshot).sha256):
            raise ValueError("The projected starting field belongs to another approved fit")
        return _stage("transfer", SurfaceEvidence(Path(projection["path"]), projection["sha256"]),
                      "Verified projection endpoint used to initialize fitting the original.")
    refinement = refinement_for(record, candidate.candidate_id)
    initialization = refinement.get("initialization")
    reason = "This study has no verified surface for the field before fitting."
    current = load_config(candidate.config_path)
    if initialization in {None, "fresh"} and not current["model"]["deformation"].get(
            "initial_momenta") and transferable_direct_field(current):
        manifest = study._verify_manifest(snapshot.study_directory)
        row = manifest["inputs"]["template"]
        surface = SurfaceEvidence(study._safe_study_path(snapshot.study_directory, row["copy"]),
                                  row["sha256"])
        return _stage("transfer", surface, "Undeformed template at a zero-momentum start.")
    if initialization not in {"learned", "nested"} or refinement.get("numerical_upgrade"):
        return _stage("transfer", reason=reason)
    ref = refinement["reference"]
    parent = verify_reference(ref)
    if (ref["target"] != target
            or guided.record(parent)["origin"] != guided.record(snapshot)["origin"]
            or _original(parent, target).sha256 != _original(snapshot, target).sha256
            or _template(parent).sha256 != _template(snapshot).sha256):
        raise ValueError("The shared starting field refers to another specimen or pilot")
    source = _candidate(parent, ref["candidate_id"])
    config = load_config(source.config_path)
    if (not transferable_direct_field(config) or not transferable_direct_field(current)
            or _flow_settings(config) != _flow_settings(current)):
        return _stage("transfer", reason=reason)
    # Remeshed or qualified endpoints may use different integration grids. Use only the
    # preceding native optimization export, identified as the source of this initialization.
    run = study.calibration_candidate_run_directory(source)
    sf = _output(collect_run_report(run), target)
    return _stage("transfer", sf, "Native surface of the retained starting field. "
                  "This is the saved source of initialization, not a new iteration-zero export.")


def _common_parts(parent, candidate, target, approved_ref, context, cancelled, *,
                  shared_approved=False):
    from diffeoforge.guided_feedback import reference

    if guided.record(parent)["origin"] != guided.record(verify_reference(approved_ref))["origin"]:
        raise ValueError("The common model and anatomical approval belong to different pilots")
    ref = reference(parent, candidate.candidate_id, target)
    approved_original, approved, default_marks, lineage = approved_source(approved_ref, cancelled)
    if _original(parent, target).sha256 != approved_original.sha256:
        raise ValueError("The common fit and individual approval have different originals")
    marks = comparison_regions(context, parent, ref)
    common, common_lineage = _surface(candidate, target, cancelled)
    template = _template(parent)
    if shared_approved and ref == approved_ref:
        if endpoint(candidate, subject=target):
            run = study.calibration_candidate_run_directory(candidate)
            seed = _output(collect_run_report(run), target)
        else:
            seed = common
        transfer = _stage("transfer", seed, "This approved fit already used the shared protocol. "
                          "Its saved native field initialized the joint pilot.")
        detail = "This original-target fit supplied the common check."
    else:
        transfer = _starting_field(parent, candidate, target, approved_ref)
        detail = ""
    stages = [approved, replace(transfer, material_template=template),
              _stage("common", common, detail, template)]
    return (approved_original, default_marks if marks is None else marks, stages,
            {"approved": lineage, "common": common_lineage})


def _joint_parts(snapshot, target, cancelled):
    info = guided.record(snapshot)
    if not info or info["phase"] != "joint":
        raise ValueError("The atlas has no linked guided joint pilot for this comparison")
    # Older guided pilots went straight from compatible individually assessed forms
    # to a joint test. Only those actually recorded approvals can supply a baseline.
    individual = accepted_reference(marker(snapshot) or {"reviews": info.get("approved", [])},
                                    target)
    request = snapshot.attachment_comparison.get("joint_initialization") or {}
    common = [r for r in request.get("references", []) if r["target"] == target]
    if not individual:
        raise ValueError("This specimen has no saved individual anatomical approval in the pilot")
    if guided.record(verify_reference(individual))["origin"] != info["origin"]:
        raise ValueError("The individual anatomical reference belongs to another pilot")
    if len(common) == 1:
        parent = verify_reference(common[0])
        if parent.visual_reviews.get(common[0]["candidate_id"]) is not True:
            raise ValueError("The joint field did not retain this specimen's common-model approval")
        parts = _common_parts(parent, _candidate(parent, common[0]["candidate_id"]), target,
                              individual, snapshot, cancelled, shared_approved=True)
    elif not common:
        original, approved, marks, lineage = approved_source(individual, cancelled)
        parts = (original, marks, [approved, _stage("transfer", reason="No bound starting field."),
                 _stage("common", reason="No separate common-model endpoint was recorded.")],
                 {"approved": lineage})
    else:
        raise ValueError("The joint study lists more than one shared field for this specimen")
    if _original(snapshot, target).sha256 != parts[0].sha256:
        raise ValueError("The joint and individual original surfaces differ")
    return parts


def pilot_report(directory, candidate_id, target, context_directory, cancelled):
    from diffeoforge.pilot_common_review import common_review

    with study.calibration_verification_scope():
        _check_cancelled(cancelled)
        current = study.load_reference_calibration_study(Path(directory))
        info = guided.record(current)
        if not info:
            raise ValueError("This pilot has no anatomical comparison record")
        candidate = _candidate(current, candidate_id)
        if info["phase"] == "joint":
            original, marks, stages, lineages = _joint_parts(current, target, cancelled)
            surface, lineages["pilot_joint"] = _surface(candidate, target, cancelled)
            stages.append(_stage("pilot_joint", surface, material_template=_template(current)))
        else:
            context = (study.load_reference_calibration_study(Path(context_directory))
                       if context_directory else current)
            review = common_review(current, candidate_id, origin=context)
            if (not review or not review["approved_individual"]
                    or review["current"]["target"] != target):
                raise ValueError("No verified approved individual fit is linked to this common fit")
            original, marks, stages, lineages = _common_parts(
                current, candidate, target, review["approved_individual"], context, cancelled)
            stages.append(_stage("pilot_joint", reason="Open the joint pilot after it completes."))
        stages.append(_stage("atlas", reason="Open the saved full atlas to compare this stage."))
        return assess_stages(target, original, marks, stages,
                             lineages=lineages, cancelled=cancelled)


def _source_joint(config, target):
    from diffeoforge.reference_atlas_handoff import METHOD, initialization
    from diffeoforge.reference_stage_retention import _candidate as historical_candidate

    plan = initialization(config)
    if not plan or plan["method"] != METHOD or target not in plan.get("pilot_subject_labels", []):
        raise ValueError("This specimen has no preserved pilot handoff in the selected atlas")
    source_run = Path(plan["source_run_directory"]).resolve()
    if sha256_file(source_run / "manifest.json") != plan["source_run_manifest_sha256"]:
        raise ValueError("The joint pilot run used by the final atlas changed")
    root = next((p for p in source_run.parents if (p / study.STUDY_MANIFEST).is_file()), None)
    if root is None:
        raise ValueError("Restore the saved pilot study to compare its approved surfaces")
    parent = study.load_reference_calibration_study(root)
    events = study._load_events(root)
    owners = [e for e in events if e["event"] == "candidate_completed"
              and study._safe_study_path(root, e["run_directory"]) == source_run]
    if len(owners) != 1:
        raise ValueError("Could not bind the saved pilot run to one exact candidate")
    event = owners[0]
    stage = next(s for s in parent.plan.stages if s.stage_id == event["stage_id"])
    cand, _ = historical_candidate(root, stage.stage_id, event["candidate_id"], events=events)
    parent = replace(parent, current_stage=stage, candidates=(cand,))
    if study.calibration_candidate_run_directory(cand).resolve() != source_run:
        raise ValueError("The selected final pilot field and the atlas starting source differ")
    return parent, cand, plan


def _atlas_start(report, plan, target):
    """Read a sealed before-joint snapshot, including after its old checkpoint was resumed."""
    from diffeoforge.reference_atlas_handoff import EARLY_CHECK

    ledger = {r["path"]: r["sha256"] for r in report.inventory}
    if EARLY_CHECK not in ledger:
        return None
    root = report.run_directory / "output"
    receipt_path = root / EARLY_CHECK
    if sha256_file(receipt_path) != ledger[EARLY_CHECK]:
        raise ValueError("The archived before-joint receipt changed")
    data = study._read_json(receipt_path, "archived before-joint receipt")
    if data.get("phase") == "initialization":
        return None  # Individual screening has no before-joint pilot snapshot.
    if (data.get("version") != "0.1" or data.get("pilot_momenta_preserved_exactly") is not True
            or data.get("subject_labels") != plan["subject_labels"]
            or data.get("pilot_indices") != plan["pilot_indices"]
            or [m["index"] for m in data["meshes"]] != plan["pilot_indices"]):
        raise ValueError("The before-joint export does not match the preserved pilot rows")
    index = plan["subject_labels"].index(target)
    rows = [m["before"] for m in data["meshes"] if m["index"] == index]
    if (len(rows) != 1 or rows[0].get("index") != index
            or ledger.get(rows[0]["path"]) != rows[0]["sha256"]):
        raise ValueError("The before-joint surface is missing or belongs to another specimen")
    return SurfaceEvidence(study._safe_study_path(root, rows[0]["path"]), rows[0]["sha256"])


def atlas_report(directory, target, cancelled):
    with study.calibration_verification_scope():
        _check_cancelled(cancelled)
        report = collect_run_report(Path(directory))
        final = _output(report, target)
        joint, candidate, plan = _source_joint(report.manifest["effective_config"], target)
        original, marks, stages, lineages = _joint_parts(joint, target, cancelled)
        inputs = [r for r in report.manifest["inputs"] if r["role"] == "subject"
                  and Path(r["staged_path"]).name == target]
        if (len(inputs) != 1 or inputs[0]["geometry"]["sha256"] != original.sha256
                or plan.get("subject_sha256", {}).get(target) != original.sha256):
            raise ValueError("The atlas and approved fit have different original specimens")
        shared, lineages["pilot_joint"] = _surface(candidate, target, cancelled)
        fixed_marks = any(m.get("purpose") == "fixed" for m in marks)
        template = _template(joint) if fixed_marks else None
        stages.append(_stage("pilot_joint", shared, material_template=template))
        atlas_template = None
        if template:
            source = collect_run_report(study.calibration_candidate_run_directory(candidate))
            obj = source.manifest["effective_config"]["model"]["object_id"]
            shared_templates = [r for r in source.inventory if Path(r["path"]).name.endswith(
                f"__EstimatedParameters__Template_{obj}.vtk")]
            staged = [r for r in report.manifest["inputs"] if r["role"] == "template"]
            if (len(shared_templates) == len(staged) == 1 and shared_templates[0]["sha256"]
                    == staged[0]["geometry"]["sha256"] == plan.get("template_sha256")):
                atlas_template = template
        before = _atlas_start(report, plan, target)
        if before:
            stages.append(_stage("atlas_start", before, "Native export before joint optimization.",
                                 atlas_template))
        stages.append(_stage("atlas", final, "" if before else
                             "This run has no separate export from the start of the full atlas.",
                             atlas_template))
        return assess_stages(target, original, marks, stages,
                             lineages=lineages, cancelled=cancelled)


def projection_report(directory, cancelled):
    """Inspect actual native endpoints on the original in a staged transfer experiment."""
    from diffeoforge.pilot_common_projection import contract, status, verified_endpoint

    with study.calibration_verification_scope():
        _check_cancelled(cancelled)
        data = contract(directory)
        state = status(directory)
        ref = state["approved_reference"]
        original, approved, _, lineage = approved_source(ref, cancelled)
        stages = [approved]
        for proof, key in (("projection", "transfer"), ("original", "common")):
            if state[proof] != "completed":
                stages.append(_stage(key, reason=f"This native stage is {state[proof]}."))
                continue
            _check_cancelled(cancelled)
            item = verified_endpoint(directory, proof)
            if (item["approved_reference"] != ref or item["target"] != ref["target"]
                    or item["original_sha256"] != original.sha256):
                raise ValueError("The transfer evidence and approved individual differ")
            template = approved.material_template
            if not template or template.sha256 != item.get("template_sha256"):
                template = None
            stages.append(_stage(key, SurfaceEvidence(Path(item["path"]), item["sha256"]),
                                 material_template=template))
        return assess_stages(ref["target"], original, data["regions"], stages,
                             lineages={"approved": lineage}, cancelled=cancelled)

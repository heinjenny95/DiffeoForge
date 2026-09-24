"""Prepare a bounded, source-bound QC successor. Never launch or alter an old run."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path, PurePosixPath

import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import validate_schema
from diffeoforge.desktop.registration_release import inspection_binding
from diffeoforge.desktop.result_review import ModernResultReview, verify_result_artifact
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import (
    CalibrationCandidate,
    PilotSubjectDeclaration,
    build_reference_calibration_plan,
    reference_calibration_plan_from_provenance,
)
from diffeoforge.reference_calibration_study import create_reference_calibration_study
from diffeoforge.reference_recommendation import recommend_reference_parameters


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def recalibration_concerns(review, decisions) -> tuple[str, ...]:
    names = {item.subject_name for item in review.registration_qc}
    if set(decisions) - names or any(
        v not in {"pass", "fail", "uncertain"} for v in decisions.values()
    ):
        raise ValueError("QC decisions do not match the reviewed cohort")
    return tuple(
        sorted(name for name, value in decisions.items() if value in {"fail", "uncertain"})
    )


def prepare_qc_recalibration(
    review: ModernResultReview,
    decisions,
    inspections,
    destination: Path,
    *,
    reason: str,
    technical_checks_confirmed: bool,
    progress_callback=None,
) -> Path:
    """Make an 11-candidate, four-stage successor with all concerns and controls.

    Uses verified staged originals in their existing atlas frame; retains full
    cohort references for the *new* final atlas. No replacement, PCA or approval.
    The original template is retained: this is not an automatic template search.
    """
    if review.engine_route != "deformetrica_reference":
        raise ValueError("QC recalibration currently supports Deformetrica results only")
    concerns = recalibration_concerns(review, decisions)
    if not concerns:
        raise ValueError("Record at least one Uncertain or Implausible case first")
    if not technical_checks_confirmed or not reason.strip():
        raise ValueError("Review orientation, units and input quality, and record the fit problem")
    for name in concerns:
        if inspections.get(name) != inspection_binding(review, name):
            raise ValueError(f"QC concern needs a current visual inspection: {name}")
    root = Path(destination).expanduser().resolve()
    if (
        root.exists()
        or root == review.run_directory.resolve()
        or review.run_directory.resolve() in root.parents
    ):
        raise ValueError("Choose a new successor folder outside the source run")
    # verify_result_artifact also rechecks the run/analysis manifest bindings.
    for index, item in enumerate(review.registration_qc):
        verify_result_artifact(review, item.original_artifact_key)
        if item.subject_name in concerns:
            verify_result_artifact(review, item.reconstruction_artifact_key)
        if progress_callback:
            progress_callback(index + 1, len(review.registration_qc), "Verifying source cohort")
    manifest = json.loads(review.workflow_manifest_path.read_text(encoding="utf-8"))
    config = copy.deepcopy(manifest["effective_config"])
    records = manifest["inputs"]
    templates = [record for record in records if record["role"] == "template"]
    if len(templates) != 1:
        raise ValueError("QC recalibration requires exactly one template")
    template_record = templates[0]
    relative = PurePosixPath(template_record["staged_path"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in str(relative)
        or ":" in str(relative)
    ):
        raise ValueError("Unsafe source template path")
    template = review.run_directory.joinpath(*relative.parts)
    cursor = template
    while cursor != review.run_directory:
        if cursor.is_symlink():
            raise ValueError("Symbolic source template path")
        cursor = cursor.parent
    if sha256_file(template) != template_record["geometry"]["sha256"]:
        raise ValueError("Source template changed")
    paths = sorted(
        (review.artifact(i.original_artifact_key).path for i in review.registration_qc),
        key=lambda p: p.name,
    )
    if len({p.parent for p in paths}) != 1 or len({p.name for p in paths}) != len(paths):
        raise ValueError("Source subjects need one directory and unique filenames")
    if set(paths[0].parent.glob("*.vtk")) != set(paths):
        raise ValueError("The source subject directory contains unreviewed or missing meshes")
    source_guidance = config["project"].get("parameter_provenance", {}).get("recommendation", {})
    prior = source_guidance.get("calibration_plan", {})
    by_name = {p.name: p for p in paths}
    mandatory = set(concerns)
    # Keep the earlier stress/coverage set to expose regressions, not just the failure.
    mandatory.update(item["filename"] for item in prior.get("selected_pilot_subjects", []))
    good = sorted(
        (i for i in review.registration_qc if decisions.get(i.subject_name) == "pass"),
        key=lambda i: (i.residual_p95, i.subject_name),
    )
    mandatory.update(i.subject_name for i in good[:2])
    if not mandatory <= set(by_name):
        raise ValueError("QC subject names do not map exactly to the stored original meshes")
    count = min(len(paths), max(8, len(mandatory) + min(2, len(paths) - len(mandatory))))
    if count > 20:
        raise ValueError(
            "More than 20 cases are required to retain QC concerns and controls. "
            "Review global alignment/template suitability before another small pilot; "
            "no cases were dropped."
        )
    declarations = tuple(PilotSubjectDeclaration(name, None, True) for name in sorted(mandatory))
    if progress_callback:
        progress_callback(0, len(paths) + 1, "Measuring aligned surface shape")
    recommendation = recommend_reference_parameters(
        (template, *paths),
        alignment_basis="declared_gpa",
        surface_detail_intent=source_guidance.get("surface_detail_intent", "balanced"),
        deformation_scale_intent=source_guidance.get("deformation_scale_intent", "balanced"),
        expected_shape_disparity=source_guidance.get("expected_shape_disparity", "moderate"),
        progress_callback=progress_callback,
    )
    request = {
        "version": "qc-recalibration-v1",
        "source_run": str(review.run_directory),
        "run_manifest_sha256": review.workflow_manifest_sha256,
        "analysis_manifest_sha256": review.bundle_manifest_sha256,
        "reason": reason.strip(),
        "technical_checks_confirmed": True,
        "decisions": dict(sorted(decisions.items())),
        "visual_inspections": dict(inspections),
        "required_concerns": list(concerns),
        "retained_controls": sorted(mandatory - set(concerns)),
        "source_calibration_plan_fingerprint": prior.get("fingerprint"),
        "boundary": (
            "Adaptive calibration, not independent validation. No anatomy approved, "
            "no old result replaced. A new full-cohort atlas and QC are required. "
            "Template search is not automatic."
        ),
    }
    source_binding = {
        "run_manifest_sha256": review.workflow_manifest_sha256,
        "analysis_manifest_sha256": review.bundle_manifest_sha256,
        "request_sha256": _hash(request),
    }
    plan = build_reference_calibration_plan(
        recommendation,
        coordinate_unit=config["input"]["units"],
        requested_pilot_subject_count=count,
        pilot_subject_declarations=declarations,
    )
    model = config["model"]
    baseline = {
        "attachment_kernel_width": model["attachment"]["kernel_width"],
        "deformation_kernel_width": model["deformation"]["kernel_width"],
        "initial_control_point_spacing": model["deformation"]["initial_control_point_spacing"],
        "noise_std": model["noise_std"],
    }
    if model["deformation"].get("initial_control_points"):
        raise ValueError(
            "An explicit initial control-point file requires a separately reviewed "
            "diagnostic; this workflow will not replace it silently"
        )
    groups = (
        ("attachment_kernel_width",),
        ("deformation_kernel_width", "initial_control_point_spacing"),
        ("noise_std",),
        ("timepoints",),
    )
    stages = []
    for stage, parameters in zip(plan.stages, groups, strict=True):
        candidates = []
        for index, factor in enumerate(
            (1.0, 2.0) if stage.stage_id == "timepoints" else (0.5, 1.0, 2.0)
        ):
            values = {
                name: (
                    model["deformation"]["timepoints"] if name == "timepoints" else baseline[name]
                )
                * factor
                for name in parameters
            }
            candidates.append(
                CalibrationCandidate(
                    f"{stage.stage_id}-{index + 1:02d}",
                    f"{factor:g} × previous setting",
                    tuple(values.items()),
                    "Bounded neighboring setting on the same QC stress cases and controls; "
                    "no automatic anatomical approval.",
                )
            )
        stages.append(
            replace(
                stage,
                title=(
                    "Surface-detail follow-up" if stage.stage_id == "attachment" else stage.title
                ),
                candidates=tuple(candidates),
            )
        )
    selected = tuple(
        replace(
            item,
            selection_role=(
                "QC concern (mandatory)"
                if item.filename in concerns
                else "Retained prior-pilot / plausible control"
                if item.filename in mandatory
                else item.selection_role
            ),
        )
        for item in plan.selected_pilot_subjects
    )
    ratios = {
        key: float(value) / recommendation.template_diagonal for key, value in baseline.items()
    }
    plan = replace(
        plan,
        stages=tuple(stages),
        selected_pilot_subjects=selected,
        baseline_effective_values=tuple(baseline.items()),
        baseline_parameter_ratios=tuple(ratios.items()),
        qc_recalibration_source=tuple(source_binding.items()),
        limitations=(*plan.limitations, request["boundary"]),
    )
    payload = plan.provenance
    for key in ("fingerprint", "status", "pilot_subject_count"):
        payload.pop(key)
    plan = replace(plan, fingerprint=_hash(payload))
    reference_calibration_plan_from_provenance(plan.provenance)
    config["project"]["name"] += " — QC recalibration"
    config["project"]["parameter_provenance"] = {
        "profile": "data_assisted",
        "scale_reference": "template_bounding_box_diagonal",
        "ratios": ratios,
        "sources": {key: "absolute_override" for key in ratios},
        "recommendation": {**recommendation.provenance, "calibration_plan": plan.provenance},
    }
    config["input"].update(
        directory=str(paths[0].parent), template=str(template), subject_pattern="*.vtk"
    )
    # The run inputs are already transformed. Keep original GPA evidence in the
    # bound parent manifest, never reapply it to these coordinates.
    config.pop("preprocessing", None)
    config["output"]["directory"] = "./runs"
    validate_schema(config)
    if sha256_file(review.workflow_manifest_path) != review.workflow_manifest_sha256:
        raise ValueError("Source manifest changed while preparing recalibration")
    root.mkdir(parents=True, exist_ok=False)
    write_text_safely(
        root / "qc-request.json",
        json.dumps(request, indent=2, sort_keys=True) + "\n",
        overwrite=False,
    )
    write_text_safely(
        root / "shape-evidence.json",
        json.dumps(recommendation.as_manifest(), indent=2) + "\n",
        overwrite=False,
    )
    config_path = root / "atlas.yaml"
    write_text_safely(
        config_path,
        "# Generated by diffeoforge init.\n" + yaml.safe_dump(config, sort_keys=False),
        overwrite=False,
    )
    create_reference_calibration_study(
        config_path,
        root / "calibration" / f"reference-pilot-{plan.fingerprint[:12]}",
        pilot_max_iterations=150,
    )
    return config_path

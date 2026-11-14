"""Axis-separated pilot refinement after a Validation Lab width boundary."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import load_config, validate_schema
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import (
    bind_axis_separated_width_refinement_plan,
    propose_axis_separated_width_refinement,
    reference_calibration_plan_from_provenance,
)
from diffeoforge.reference_calibration_study import (
    ReferenceCalibrationStudySnapshot,
    create_reference_calibration_study,
)
from diffeoforge.reference_sensitivity_assessment import (
    SENSITIVITY_ASSESSMENT_JSON,
    verify_reference_sensitivity_assessment,
)
from diffeoforge.reference_validation_study import (
    VALIDATION_EVENTS,
    VALIDATION_MANIFEST,
    load_reference_validation_study,
)

WIDTH_REFINEMENT_VERSION = "0.1"
WIDTH_REFINEMENT_MANIFEST = "width-refinement.json"
WIDTH_REFINEMENT_DIGEST = "width-refinement.sha256"
WIDTH_PARAMETERS = (
    "attachment_kernel_width",
    "deformation_kernel_width",
    "initial_control_point_spacing",
)


class ReferenceWidthRefinementError(RuntimeError):
    """Raised when a width-refinement pilot cannot be frozen safely."""


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _calibration_plan(config: dict[str, Any]):
    try:
        provenance = config["project"]["parameter_provenance"]["recommendation"][
            "calibration_plan"
        ]
    except (KeyError, TypeError) as error:
        raise ReferenceWidthRefinementError(
            "Validation source config has no bound calibration plan"
        ) from error
    return reference_calibration_plan_from_provenance(provenance)


def _set_widths(
    config: dict[str, Any],
    *,
    values: dict[str, float],
    template_diagonal: float,
) -> None:
    config["model"]["attachment"]["kernel_width"] = values[
        "attachment_kernel_width"
    ]
    config["model"]["deformation"]["kernel_width"] = values[
        "deformation_kernel_width"
    ]
    config["model"]["deformation"]["initial_control_point_spacing"] = values[
        "initial_control_point_spacing"
    ]
    provenance = config["project"]["parameter_provenance"]
    for name, value in values.items():
        provenance["ratios"][name] = float(value) / template_diagonal
        provenance["sources"][name] = "absolute_override"


def default_reference_width_refinement_directory(
    validation_study_directory: Path | str,
) -> Path:
    """Return the deterministic sibling for the first local refinement pilot."""

    source = Path(validation_study_directory).expanduser().resolve()
    return source.parent / f"{source.name}-width-refinement-01"


def create_reference_width_refinement_study(
    validation_study_directory: Path | str,
    sensitivity_assessment_directory: Path | str,
    destination: Path | str,
    *,
    pilot_max_iterations: int = 150,
) -> ReferenceCalibrationStudySnapshot:
    """Freeze a seven-candidate local width pilot without starting a process."""

    validation = load_reference_validation_study(validation_study_directory)
    if validation.status != "completed" or validation.assessment is None:
        raise ReferenceWidthRefinementError(
            "Width refinement requires a completed Validation Lab study"
        )
    sensitivity = verify_reference_sensitivity_assessment(
        sensitivity_assessment_directory
    )
    report = sensitivity.manifest
    source = report["source"]
    if Path(str(source["validation_study_directory"])).resolve() != (
        validation.study_directory
    ):
        raise ReferenceWidthRefinementError(
            "Sensitivity assessment belongs to another Validation Lab study"
        )
    boundary = report["search_boundary"]
    if boundary.get("at_tested_boundary") is not True:
        raise ReferenceWidthRefinementError(
            "Sensitivity assessment does not report a width search boundary"
        )
    selected_id = boundary.get("recommended_finalist_id")
    if (
        not isinstance(selected_id, str)
        or selected_id != validation.assessment.recommended_finalist_id
    ):
        raise ReferenceWidthRefinementError(
            "Sensitivity and Validation Lab preferred finalists differ"
        )
    boundary_by_name = {
        str(item["parameter"]): str(item["location"])
        for item in boundary.get("parameters", [])
    }
    invalid_boundaries = {
        name: boundary_by_name.get(name)
        for name in WIDTH_PARAMETERS
        if boundary_by_name.get(name) != "minimum"
    }
    if invalid_boundaries:
        raise ReferenceWidthRefinementError(
            "This refinement path requires all three widths at the tested minimum: "
            + ", ".join(
                f"{name}={location or 'missing'}"
                for name, location in invalid_boundaries.items()
            )
        )
    finalist = next(
        (item for item in validation.plan.finalists if item.finalist_id == selected_id),
        None,
    )
    if finalist is None:
        raise ReferenceWidthRefinementError("Preferred Validation Lab finalist is absent")
    center = {name: float(finalist.values[name]) for name in WIDTH_PARAMETERS}

    source_config_path = validation.study_directory / "source" / "atlas-calibrated.yaml"
    config = load_config(source_config_path)
    plan = _calibration_plan(config)
    sensitivity_fingerprint = sha256_file(
        sensitivity.artifact_directory / SENSITIVITY_ASSESSMENT_JSON
    )
    proposal = propose_axis_separated_width_refinement(
        plan,
        selected_values=center,
        source_assessment_fingerprint=sensitivity_fingerprint,
    )
    refinement_plan = bind_axis_separated_width_refinement_plan(plan, proposal)

    seed = copy.deepcopy(config)
    seed["project"]["name"] = f"{config['project']['name']} width refinement"
    _set_widths(
        seed,
        values=center,
        template_diagonal=float(validation.plan.template_diagonal),
    )
    seed["project"]["parameter_provenance"]["recommendation"][
        "calibration_plan"
    ] = refinement_plan.provenance
    validate_schema(seed)

    root = Path(destination).expanduser().resolve()
    if root.exists():
        raise FileExistsError(f"Width-refinement destination exists: {root}")
    if (
        isinstance(pilot_max_iterations, bool)
        or not isinstance(pilot_max_iterations, int)
        or pilot_max_iterations < 1
    ):
        raise ReferenceWidthRefinementError(
            "pilot_max_iterations must be a positive integer"
        )
    root.mkdir(parents=True)
    try:
        seed_path = root / "seed" / "atlas-width-refinement.yaml"
        seed_path.parent.mkdir()
        write_text_safely(
            seed_path,
            yaml.safe_dump(seed, sort_keys=False, allow_unicode=True),
            overwrite=False,
        )
        snapshot = create_reference_calibration_study(
            seed_path,
            root / "study",
            pilot_max_iterations=pilot_max_iterations,
        )
        manifest = {
            "version": WIDTH_REFINEMENT_VERSION,
            "status": "planned_not_executed",
            "proposal": proposal.as_manifest(),
            "source": {
                "validation_study_directory": str(validation.study_directory),
                "validation_study_id": validation.study_id,
                "validation_plan_fingerprint": validation.plan.fingerprint,
                "validation_manifest_sha256": sha256_file(
                    validation.study_directory / VALIDATION_MANIFEST
                ),
                "validation_events_sha256": sha256_file(
                    validation.study_directory / VALIDATION_EVENTS
                ),
                "sensitivity_assessment_directory": str(
                    sensitivity.artifact_directory
                ),
                "sensitivity_assessment_sha256": sensitivity_fingerprint,
                "preferred_finalist_id": selected_id,
            },
            "execution": {
                "study_directory": "study",
                "study_id": snapshot.study_id,
                "plan_fingerprint": snapshot.plan.fingerprint,
                "pilot_subject_count": snapshot.plan.pilot_subject_count,
                "pilot_max_iterations": pilot_max_iterations,
                "seed_config": "seed/atlas-width-refinement.yaml",
                "seed_config_sha256": sha256_file(seed_path),
            },
            "decision_scope": (
                "Axis-separated numerical screening on the immutable calibration pilot. "
                "A retained candidate still requires full-training and heldout confirmation."
            ),
        }
        manifest["fingerprint"] = _canonical_hash(manifest)
        manifest_path = root / WIDTH_REFINEMENT_MANIFEST
        write_text_safely(manifest_path, _canonical_json(manifest), overwrite=False)
        write_text_safely(
            root / WIDTH_REFINEMENT_DIGEST,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
        )
        return snapshot
    except BaseException:
        shutil.rmtree(root)
        raise


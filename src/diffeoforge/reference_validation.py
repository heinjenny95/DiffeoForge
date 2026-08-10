"""Predeclared robustness validation for calibrated Deformetrica parameters.

The pilot calibration searches a deliberately limited parameter neighborhood.
This module defines the separate confirmation layer: finalists are frozen,
subjects are assigned to deterministic cohorts before execution, and every
candidate is compared on the same external evidence.  The resulting evidence
can support a claim about robustness *within the declared search space*; it
cannot establish a universal biological optimum.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import reference_calibration_plan_from_provenance
from diffeoforge.reference_recommendation import (
    MeshGeometryObservation,
    recommend_reference_parameters,
)

VALIDATION_PLAN_VERSION = "0.1"
VALIDATION_ASSESSMENT_VERSION = "0.1"
ValidationPhase = Literal["training_confirmation", "resampling_stability"]


class ReferenceValidationError(ConfigurationError):
    """Raised when a validation plan or its evidence is invalid."""


def _canonical_json(value: object, *, indent: int | None = None) -> str:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":") if indent is None else None,
            indent=indent,
            ensure_ascii=False,
            allow_nan=False,
        )
        + ("\n" if indent is not None else "")
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite_nonnegative(name: str, value: float) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ReferenceValidationError(f"{name} must be finite and nonnegative")
    return normalized


@dataclass(frozen=True)
class ValidationSubject:
    filename: str
    sha256: str
    source_subject_index: int
    role: str

    def as_manifest(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "source_subject_index": self.source_subject_index,
            "role": self.role,
        }


@dataclass(frozen=True)
class ValidationFinalist:
    finalist_id: str
    label: str
    parameter_values: tuple[tuple[str, float], ...]
    relationship_to_pilot: str

    @property
    def values(self) -> dict[str, float]:
        return dict(self.parameter_values)

    def as_manifest(self) -> dict[str, object]:
        return {
            "finalist_id": self.finalist_id,
            "label": self.label,
            "parameter_values": self.values,
            "relationship_to_pilot": self.relationship_to_pilot,
        }


@dataclass(frozen=True)
class ValidationCohort:
    cohort_id: str
    phase: ValidationPhase
    subject_filenames: tuple[str, ...]
    rationale: str

    def as_manifest(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "phase": self.phase,
            "subject_filenames": list(self.subject_filenames),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ValidationRunSpec:
    run_id: str
    phase: ValidationPhase
    cohort_id: str
    finalist_id: str
    subject_filenames: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "cohort_id": self.cohort_id,
            "finalist_id": self.finalist_id,
            "subject_filenames": list(self.subject_filenames),
        }


@dataclass(frozen=True)
class ReferenceValidationPlan:
    version: str
    fingerprint: str
    source_config_sha256: str
    calibration_plan_fingerprint: str
    calibration_study_id: str
    template_filename: str
    template_sha256: str
    template_diagonal: float
    coordinate_unit: str
    subjects: tuple[ValidationSubject, ...]
    finalists: tuple[ValidationFinalist, ...]
    training_subjects: tuple[str, ...]
    heldout_subjects: tuple[str, ...]
    cohorts: tuple[ValidationCohort, ...]
    run_specs: tuple[ValidationRunSpec, ...]
    resample_count: int
    resample_fraction: float
    smallest_relevant_feature: float | None
    selection_rule: tuple[str, ...]
    confidence_gates: tuple[str, ...]
    required_future_evidence: tuple[str, ...]
    limitations: tuple[str, ...]

    @property
    def subject_count(self) -> int:
        return len(self.subjects)

    def as_manifest(self) -> dict[str, object]:
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "status": "planned_not_executed",
            "source_config_sha256": self.source_config_sha256,
            "calibration_plan_fingerprint": self.calibration_plan_fingerprint,
            "calibration_study_id": self.calibration_study_id,
            "template_filename": self.template_filename,
            "template_sha256": self.template_sha256,
            "template_diagonal": self.template_diagonal,
            "coordinate_unit": self.coordinate_unit,
            "subject_count": self.subject_count,
            "subjects": [subject.as_manifest() for subject in self.subjects],
            "finalists": [finalist.as_manifest() for finalist in self.finalists],
            "training_subjects": list(self.training_subjects),
            "heldout_subjects": list(self.heldout_subjects),
            "cohorts": [cohort.as_manifest() for cohort in self.cohorts],
            "run_specs": [run.as_manifest() for run in self.run_specs],
            "resample_count": self.resample_count,
            "resample_fraction": self.resample_fraction,
            "smallest_relevant_feature": self.smallest_relevant_feature,
            "selection_rule": list(self.selection_rule),
            "confidence_gates": list(self.confidence_gates),
            "required_future_evidence": list(self.required_future_evidence),
            "limitations": list(self.limitations),
        }


def _parameter_values(config: Mapping[str, object]) -> dict[str, float]:
    model = config["model"]
    assert isinstance(model, Mapping)
    attachment = model["attachment"]
    deformation = model["deformation"]
    assert isinstance(attachment, Mapping) and isinstance(deformation, Mapping)
    return {
        "attachment_kernel_width": float(attachment["kernel_width"]),
        "deformation_kernel_width": float(deformation["kernel_width"]),
        "initial_control_point_spacing": float(
            deformation["initial_control_point_spacing"]
        ),
        "noise_std": float(model["noise_std"]),
        "timepoints": float(deformation["timepoints"]),
    }


def _neighbor(
    selected: float,
    candidates: Sequence[float],
    *,
    direction: int,
) -> float:
    unique = sorted({float(value) for value in candidates if float(value) > 0})
    if direction < 0:
        values = [value for value in unique if value < selected * (1.0 - 1e-10)]
        return values[-1] if values else selected
    values = [value for value in unique if value > selected * (1.0 + 1e-10)]
    return values[0] if values else selected


def _finalists(
    config: Mapping[str, object],
    calibration_plan: object,
) -> tuple[ValidationFinalist, ...]:
    selected = _parameter_values(config)
    parameter_candidates: dict[str, list[float]] = {
        name: [value] for name, value in selected.items()
    }
    for stage in calibration_plan.stages:
        for candidate in stage.candidates:
            for name, value in candidate.values.items():
                parameter_candidates.setdefault(name, []).append(float(value))

    candidates: list[ValidationFinalist] = [
        ValidationFinalist(
            finalist_id="pilot-selected",
            label="Pilot-selected center",
            parameter_values=tuple(sorted(selected.items())),
            relationship_to_pilot=(
                "Exact parameter set retained by the completed staged pilot."
            ),
        )
    ]
    alternatives = (
        (
            "more-local",
            "Neighboring more-local finalist",
            -1,
            "Nearest tested lower matching/deformation scales; more flexible and "
            "potentially more sensitive to mesh texture.",
        ),
        (
            "more-global",
            "Neighboring smoother finalist",
            1,
            "Nearest tested higher matching/deformation scales; smoother and "
            "potentially less able to retain localized anatomy.",
        ),
    )
    for finalist_id, label, direction, rationale in alternatives:
        values = dict(selected)
        for name in (
            "attachment_kernel_width",
            "deformation_kernel_width",
            "initial_control_point_spacing",
        ):
            values[name] = _neighbor(
                selected[name], parameter_candidates[name], direction=direction
            )
        if any(
            all(
                math.isclose(
                    values[name], existing.values[name], rel_tol=1e-12, abs_tol=1e-15
                )
                for name in values
            )
            for existing in candidates
        ):
            continue
        candidates.append(
            ValidationFinalist(
                finalist_id=finalist_id,
                label=label,
                parameter_values=tuple(sorted(values.items())),
                relationship_to_pilot=rationale,
            )
        )
    if len(candidates) < 2:
        raise ReferenceValidationError(
            "The calibration search contains no distinct neighboring finalist"
        )
    return tuple(candidates)


def _descriptor_matrix(
    observations: Sequence[MeshGeometryObservation],
) -> np.ndarray:
    raw = np.asarray(
        [
            (
                math.log(observation.bounding_box_diagonal),
                math.log(observation.rms_radius),
                math.log(observation.median_sampled_edge_length),
                math.log(float(observation.triangles)),
            )
            for observation in observations
        ],
        dtype=np.float64,
    )
    median = np.median(raw, axis=0)
    scale = np.median(np.abs(raw - median), axis=0)
    scale[scale <= np.finfo(float).eps] = 1.0
    return (raw - median) / scale


def _diverse_selection(
    observations: Sequence[MeshGeometryObservation],
    count: int,
) -> tuple[str, ...]:
    if count < 1 or count > len(observations):
        raise ReferenceValidationError("Invalid deterministic holdout size")
    matrix = _descriptor_matrix(observations)
    medoid = int(np.argmin(np.sum((matrix - np.median(matrix, axis=0)) ** 2, axis=1)))
    selected = [medoid]
    while len(selected) < count:
        distances = np.min(
            np.sum((matrix[:, None, :] - matrix[selected][None, :, :]) ** 2, axis=2),
            axis=1,
        )
        distances[selected] = -1.0
        maximum = float(np.max(distances))
        tied = np.flatnonzero(np.isclose(distances, maximum, rtol=1e-12, atol=1e-15))
        selected.append(
            min(tied.tolist(), key=lambda index: observations[index].filename.casefold())
        )
    return tuple(observations[index].filename for index in selected)


def _resample_cohorts(
    training: tuple[str, ...],
    *,
    count: int,
    fraction: float,
    seed: str,
) -> tuple[ValidationCohort, ...]:
    size = max(3, min(len(training), int(round(len(training) * fraction))))
    ranked: list[tuple[str, ...]] = []
    for index in range(count):
        order = sorted(
            training,
            key=lambda name: hashlib.sha256(
                f"{seed}:{index}:{name}".encode()
            ).hexdigest(),
        )
        ranked.append(tuple(sorted(order[:size], key=str.casefold)))
    return tuple(
        ValidationCohort(
            cohort_id=f"resample-{index + 1:02d}",
            phase="resampling_stability",
            subject_filenames=subjects,
            rationale=(
                "Deterministic without-replacement training-cohort resample used to "
                "test whether the finalist preference changes with cohort composition."
            ),
        )
        for index, subjects in enumerate(ranked)
    )


def build_reference_validation_plan(
    config_path: Path | str,
    *,
    holdout_fraction: float = 0.20,
    resample_count: int = 5,
    resample_fraction: float = 0.80,
) -> ReferenceValidationPlan:
    """Build a deterministic, hash-bound post-pilot validation plan."""

    source = Path(config_path).expanduser().resolve()
    config = load_config(source)
    inputs = validate_input_paths(config, source)
    if not 0.1 <= holdout_fraction <= 0.4:
        raise ReferenceValidationError("holdout_fraction must be between 0.1 and 0.4")
    if not 1 <= resample_count <= 20:
        raise ReferenceValidationError("resample_count must be between 1 and 20")
    if not 0.5 <= resample_fraction <= 0.95:
        raise ReferenceValidationError("resample_fraction must be between 0.5 and 0.95")
    if inputs.subject_count < 8:
        raise ReferenceValidationError(
            "Validation Lab requires at least eight subjects; smaller cohorts cannot "
            "support a separate holdout and resampling analysis."
        )
    try:
        recommendation_record = config["project"]["parameter_provenance"][
            "recommendation"
        ]
        calibration_record = recommendation_record["calibration_result"]
        calibration_plan_record = recommendation_record["calibration_plan"]
    except (KeyError, TypeError) as error:
        raise ReferenceValidationError(
            "Validation Lab requires a completed DiffeoForge pilot-calibrated config"
        ) from error
    if calibration_record.get("status") != "completed":
        raise ReferenceValidationError("Pilot calibration is not complete")
    calibration_plan = reference_calibration_plan_from_provenance(
        calibration_plan_record
    )
    if calibration_record.get("plan_fingerprint") != calibration_plan.fingerprint:
        raise ReferenceValidationError(
            "Pilot result and calibration plan fingerprints do not match"
        )
    if calibration_plan.subject_count != inputs.subject_count:
        raise ReferenceValidationError(
            "Pilot plan subject count differs from the current full cohort"
        )
    if calibration_plan.template_sha256 != sha256_file(inputs.template):
        raise ReferenceValidationError(
            "Pilot plan template bytes differ from the current template"
        )

    recommendation = recommend_reference_parameters(
        (inputs.template, *inputs.subjects),
        alignment_basis="declared_gpa",
        surface_detail_intent=str(
            recommendation_record.get("surface_detail_intent", "balanced")
        ),
        deformation_scale_intent=str(
            recommendation_record.get("deformation_scale_intent", "balanced")
        ),
    )
    subject_observations = tuple(
        observation
        for observation in recommendation.observations
        if observation.filename != inputs.template.name
    )
    pilot_names = {
        subject.filename for subject in calibration_plan.selected_pilot_subjects
    }
    holdout_pool = tuple(
        observation
        for observation in subject_observations
        if observation.filename not in pilot_names
    )
    if len(holdout_pool) < 2:
        raise ReferenceValidationError(
            "At least two subjects that were not used in pilot selection are required "
            "for an untouched holdout"
        )
    desired_holdout = max(2, int(round(inputs.subject_count * holdout_fraction)))
    desired_holdout = min(desired_holdout, len(holdout_pool))
    heldout = _diverse_selection(holdout_pool, desired_holdout)
    heldout_set = set(heldout)
    training = tuple(
        path.name for path in inputs.subjects if path.name not in heldout_set
    )
    if len(training) < 5:
        raise ReferenceValidationError("Training partition contains fewer than five subjects")

    finalists = _finalists(config, calibration_plan)
    subjects = tuple(
        ValidationSubject(
            filename=path.name,
            sha256=sha256_file(path),
            source_subject_index=index,
            role="heldout" if path.name in heldout_set else "training",
        )
        for index, path in enumerate(inputs.subjects)
    )
    seed_payload = {
        "source_config_sha256": sha256_file(source),
        "subjects": [subject.as_manifest() for subject in subjects],
        "training": training,
        "heldout": heldout,
        "finalists": [finalist.as_manifest() for finalist in finalists],
        "resample_count": resample_count,
        "resample_fraction": resample_fraction,
    }
    seed = _canonical_hash(seed_payload)
    cohorts = (
        ValidationCohort(
            cohort_id="training-confirmation",
            phase="training_confirmation",
            subject_filenames=training,
            rationale=(
                "All non-heldout subjects; compares frozen finalists without using "
                "the reserved validation cohort."
            ),
        ),
        *_resample_cohorts(
            training,
            count=resample_count,
            fraction=resample_fraction,
            seed=seed,
        ),
    )
    runs = tuple(
        ValidationRunSpec(
            run_id=f"{cohort.cohort_id}--{finalist.finalist_id}",
            phase=cohort.phase,
            cohort_id=cohort.cohort_id,
            finalist_id=finalist.finalist_id,
            subject_filenames=cohort.subject_filenames,
        )
        for cohort in cohorts
        for finalist in finalists
    )
    smallest = calibration_plan.smallest_relevant_feature
    payload = {
        "version": VALIDATION_PLAN_VERSION,
        **seed_payload,
        "calibration_plan_fingerprint": calibration_plan.fingerprint,
        "calibration_study_id": str(calibration_record["study_id"]),
        "template": {
            "filename": inputs.template.name,
            "sha256": sha256_file(inputs.template),
            "diagonal": recommendation.template_diagonal,
        },
        "coordinate_unit": str(config["input"]["units"]),
        "cohorts": [cohort.as_manifest() for cohort in cohorts],
        "runs": [run.as_manifest() for run in runs],
        "smallest_relevant_feature": smallest,
    }
    fingerprint = _canonical_hash(payload)
    return ReferenceValidationPlan(
        version=VALIDATION_PLAN_VERSION,
        fingerprint=fingerprint,
        source_config_sha256=sha256_file(source),
        calibration_plan_fingerprint=calibration_plan.fingerprint,
        calibration_study_id=str(calibration_record["study_id"]),
        template_filename=inputs.template.name,
        template_sha256=sha256_file(inputs.template),
        template_diagonal=recommendation.template_diagonal,
        coordinate_unit=str(config["input"]["units"]),
        subjects=subjects,
        finalists=finalists,
        training_subjects=training,
        heldout_subjects=heldout,
        cohorts=cohorts,
        run_specs=runs,
        resample_count=resample_count,
        resample_fraction=resample_fraction,
        smallest_relevant_feature=smallest,
        selection_rule=(
            "Reject incomplete, nonconverged, or geometrically invalid runs.",
            "Within each identical cohort, retain candidates whose external surface "
            "error is practically equivalent to the lowest observed error.",
            "Among equivalent candidates prefer lower deformation distortion, then "
            "the smoother deformation model; runtime is reported but is not an "
            "anatomical-quality metric.",
            "Require the same finalist to win at least 80% of predeclared cohort "
            "comparisons before calling the recommendation robust.",
        ),
        confidence_gates=(
            "All frozen finalist runs completed and passed geometric validity checks.",
            "Winner support is at least 80% across the full training comparison and "
            "predeclared resamples.",
            "The preference remains stable under uncertainty-aware metric comparison.",
            "Reserved-subject registration and independent biological evidence remain "
            "separate gates and may not be inferred from training reconstructions.",
        ),
        required_future_evidence=(
            "Fixed-template registration of the untouched heldout subjects.",
            "Independent validation landmarks or another anatomy-specific criterion "
            "that was not used for GPA or parameter selection.",
            "A final full-cohort atlas using the locked validated parameters.",
        ),
        limitations=(
            "This design compares the selected pilot solution with its nearest tested "
            "neighbors; it does not search all possible Deformetrica parameters.",
            "Resampling measures cohort-composition stability and is not a substitute "
            "for external heldout validation.",
            "Automatic geometric evidence cannot decide biological plausibility.",
        ),
    )


def validation_plan_json(plan: ReferenceValidationPlan) -> str:
    return _canonical_json(plan.as_manifest(), indent=2)


def reference_validation_plan_from_manifest(
    value: Mapping[str, object],
) -> ReferenceValidationPlan:
    """Reconstruct a plan stored inside a separately SHA-bound study manifest."""

    try:
        if value["version"] != VALIDATION_PLAN_VERSION:
            raise ReferenceValidationError(
                f"Unsupported validation-plan version: {value['version']}"
            )
        subjects = tuple(
            ValidationSubject(
                filename=str(item["filename"]),
                sha256=str(item["sha256"]),
                source_subject_index=int(item["source_subject_index"]),
                role=str(item["role"]),
            )
            for item in value["subjects"]
        )
        finalists = tuple(
            ValidationFinalist(
                finalist_id=str(item["finalist_id"]),
                label=str(item["label"]),
                parameter_values=tuple(
                    sorted(
                        (str(name), float(parameter))
                        for name, parameter in item["parameter_values"].items()
                    )
                ),
                relationship_to_pilot=str(item["relationship_to_pilot"]),
            )
            for item in value["finalists"]
        )
        cohorts = tuple(
            ValidationCohort(
                cohort_id=str(item["cohort_id"]),
                phase=str(item["phase"]),
                subject_filenames=tuple(str(name) for name in item["subject_filenames"]),
                rationale=str(item["rationale"]),
            )
            for item in value["cohorts"]
        )
        runs = tuple(
            ValidationRunSpec(
                run_id=str(item["run_id"]),
                phase=str(item["phase"]),
                cohort_id=str(item["cohort_id"]),
                finalist_id=str(item["finalist_id"]),
                subject_filenames=tuple(str(name) for name in item["subject_filenames"]),
            )
            for item in value["run_specs"]
        )
        plan = ReferenceValidationPlan(
            version=str(value["version"]),
            fingerprint=str(value["fingerprint"]),
            source_config_sha256=str(value["source_config_sha256"]),
            calibration_plan_fingerprint=str(value["calibration_plan_fingerprint"]),
            calibration_study_id=str(value["calibration_study_id"]),
            template_filename=str(value["template_filename"]),
            template_sha256=str(value["template_sha256"]),
            template_diagonal=float(value["template_diagonal"]),
            coordinate_unit=str(value["coordinate_unit"]),
            subjects=subjects,
            finalists=finalists,
            training_subjects=tuple(str(name) for name in value["training_subjects"]),
            heldout_subjects=tuple(str(name) for name in value["heldout_subjects"]),
            cohorts=cohorts,
            run_specs=runs,
            resample_count=int(value["resample_count"]),
            resample_fraction=float(value["resample_fraction"]),
            smallest_relevant_feature=(
                None
                if value["smallest_relevant_feature"] is None
                else float(value["smallest_relevant_feature"])
            ),
            selection_rule=tuple(str(item) for item in value["selection_rule"]),
            confidence_gates=tuple(str(item) for item in value["confidence_gates"]),
            required_future_evidence=tuple(
                str(item) for item in value["required_future_evidence"]
            ),
            limitations=tuple(str(item) for item in value["limitations"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ReferenceValidationError(
            f"Stored validation plan is incomplete or invalid: {error}"
        ) from error
    if len(plan.fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in plan.fingerprint
    ):
        raise ReferenceValidationError("Stored validation fingerprint is invalid")
    if len({subject.filename.casefold() for subject in subjects}) != len(subjects):
        raise ReferenceValidationError("Stored validation subjects are not unique")
    if len({item.finalist_id for item in finalists}) != len(finalists):
        raise ReferenceValidationError("Stored validation finalists are not unique")
    if len({item.run_id for item in runs}) != len(runs):
        raise ReferenceValidationError("Stored validation run IDs are not unique")
    if set(plan.training_subjects) & set(plan.heldout_subjects):
        raise ReferenceValidationError("Stored training and holdout cohorts overlap")
    return plan


@dataclass(frozen=True)
class ValidationRunEvidence:
    run_id: str
    finalist_id: str
    cohort_id: str
    completed: bool
    converged: bool
    invalid_face_count: int
    external_residual_p95: float | None
    distortion_p95: float | None
    runtime_seconds: float | None
    atlas_path: str | None = None
    subject_residual_p95: tuple[tuple[str, float], ...] = ()

    def as_manifest(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "finalist_id": self.finalist_id,
            "cohort_id": self.cohort_id,
            "completed": self.completed,
            "converged": self.converged,
            "invalid_face_count": self.invalid_face_count,
            "external_residual_p95": self.external_residual_p95,
            "distortion_p95": self.distortion_p95,
            "runtime_seconds": self.runtime_seconds,
            "atlas_path": self.atlas_path,
            "subject_residual_p95": dict(self.subject_residual_p95),
        }


@dataclass(frozen=True)
class ValidationFinalistAssessment:
    finalist_id: str
    eligible_group_count: int
    group_win_count: int
    group_win_fraction: float
    median_external_residual_p95: float | None
    median_distortion_p95: float | None
    median_runtime_seconds: float | None
    rejection_reasons: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "finalist_id": self.finalist_id,
            "eligible_group_count": self.eligible_group_count,
            "group_win_count": self.group_win_count,
            "group_win_fraction": self.group_win_fraction,
            "median_external_residual_p95": self.median_external_residual_p95,
            "median_distortion_p95": self.median_distortion_p95,
            "median_runtime_seconds": self.median_runtime_seconds,
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True)
class ReferenceValidationAssessment:
    version: str
    plan_fingerprint: str
    status: str
    recommended_finalist_id: str | None
    confidence: str
    winner_support: float | None
    practical_error_margin: float
    practical_error_margin_basis: str
    finalists: tuple[ValidationFinalistAssessment, ...]
    missing_run_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    next_gates: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "version": self.version,
            "plan_fingerprint": self.plan_fingerprint,
            "status": self.status,
            "recommended_finalist_id": self.recommended_finalist_id,
            "confidence": self.confidence,
            "winner_support": self.winner_support,
            "practical_error_margin": self.practical_error_margin,
            "practical_error_margin_basis": self.practical_error_margin_basis,
            "finalists": [item.as_manifest() for item in self.finalists],
            "missing_run_ids": list(self.missing_run_ids),
            "warnings": list(self.warnings),
            "next_gates": list(self.next_gates),
        }


def assess_reference_validation(
    plan: ReferenceValidationPlan,
    evidence: Sequence[ValidationRunEvidence],
) -> ReferenceValidationAssessment:
    """Assess frozen finalists using only predeclared common external metrics."""

    expected = {run.run_id: run for run in plan.run_specs}
    supplied: dict[str, ValidationRunEvidence] = {}
    for item in evidence:
        if item.run_id not in expected:
            raise ReferenceValidationError(f"Unexpected validation run: {item.run_id}")
        if item.run_id in supplied:
            raise ReferenceValidationError(f"Duplicate validation evidence: {item.run_id}")
        spec = expected[item.run_id]
        if item.finalist_id != spec.finalist_id or item.cohort_id != spec.cohort_id:
            raise ReferenceValidationError(
                f"Validation evidence identity differs from plan: {item.run_id}"
            )
        supplied[item.run_id] = item
    missing = tuple(sorted(set(expected) - set(supplied)))
    margin = (
        float(plan.smallest_relevant_feature) * 0.05
        if plan.smallest_relevant_feature is not None
        else plan.template_diagonal * 0.005
    )
    margin_basis = (
        "5% of the researcher-declared smallest relevant feature"
        if plan.smallest_relevant_feature is not None
        else "0.5% of template diagonal; a numerical fallback, not a biological threshold"
    )
    wins: Counter[str] = Counter()
    eligible_groups: Counter[str] = Counter()
    reasons: dict[str, list[str]] = {
        finalist.finalist_id: [] for finalist in plan.finalists
    }
    for cohort in plan.cohorts:
        group = [
            supplied.get(f"{cohort.cohort_id}--{finalist.finalist_id}")
            for finalist in plan.finalists
        ]
        if any(item is None for item in group):
            continue
        valid: list[ValidationRunEvidence] = []
        for item in group:
            assert item is not None
            rejection = None
            if not item.completed:
                rejection = "run did not complete"
            elif not item.converged:
                rejection = "optimizer convergence was not evidenced"
            elif item.invalid_face_count:
                rejection = f"{item.invalid_face_count} invalid faces"
            elif item.external_residual_p95 is None or item.distortion_p95 is None:
                rejection = "external comparison metrics are incomplete"
            if rejection:
                reasons[item.finalist_id].append(f"{cohort.cohort_id}: {rejection}")
            else:
                _finite_nonnegative("external residual", item.external_residual_p95)
                _finite_nonnegative("distortion", item.distortion_p95)
                valid.append(item)
                eligible_groups[item.finalist_id] += 1
        if not valid:
            continue
        best_error = min(float(item.external_residual_p95) for item in valid)
        equivalent = [
            item
            for item in valid
            if float(item.external_residual_p95) <= best_error + margin
        ]
        best_distortion = min(float(item.distortion_p95) for item in equivalent)
        distortion_equivalent = [
            item
            for item in equivalent
            if float(item.distortion_p95)
            <= best_distortion + max(best_distortion * 0.02, 1e-12)
        ]
        finalist_by_id = {item.finalist_id: item for item in plan.finalists}
        winner = max(
            distortion_equivalent,
            key=lambda item: (
                finalist_by_id[item.finalist_id].values[
                    "deformation_kernel_width"
                ],
                -float(item.runtime_seconds or math.inf),
                item.finalist_id,
            ),
        )
        wins[winner.finalist_id] += 1

    completed_group_count = sum(
        all(f"{cohort.cohort_id}--{item.finalist_id}" in supplied for item in plan.finalists)
        for cohort in plan.cohorts
    )
    assessments: list[ValidationFinalistAssessment] = []
    for finalist in plan.finalists:
        finalist_evidence = [
            item
            for item in supplied.values()
            if item.finalist_id == finalist.finalist_id
            and item.completed
            and item.invalid_face_count == 0
        ]
        def median(
            field: str,
            values_source: Sequence[ValidationRunEvidence] = finalist_evidence,
        ) -> float | None:
            values = [
                float(value)
                for item in values_source
                if (value := getattr(item, field)) is not None
            ]
            return float(np.median(values)) if values else None

        assessments.append(
            ValidationFinalistAssessment(
                finalist_id=finalist.finalist_id,
                eligible_group_count=eligible_groups[finalist.finalist_id],
                group_win_count=wins[finalist.finalist_id],
                group_win_fraction=(
                    wins[finalist.finalist_id] / completed_group_count
                    if completed_group_count
                    else 0.0
                ),
                median_external_residual_p95=median("external_residual_p95"),
                median_distortion_p95=median("distortion_p95"),
                median_runtime_seconds=median("runtime_seconds"),
                rejection_reasons=tuple(dict.fromkeys(reasons[finalist.finalist_id])),
            )
        )
    ranked = sorted(
        assessments,
        key=lambda item: (-item.group_win_count, item.finalist_id),
    )
    winner = ranked[0] if ranked and ranked[0].group_win_count else None
    support = winner.group_win_fraction if winner else None
    all_complete = not missing and completed_group_count == len(plan.cohorts)
    all_valid = all(
        item.completed
        and item.converged
        and item.invalid_face_count == 0
        and item.external_residual_p95 is not None
        and item.distortion_p95 is not None
        for item in supplied.values()
    )
    if not all_complete:
        status = "incomplete"
        confidence = "not assessed"
    elif not all_valid:
        status = "failed_validity_gate"
        confidence = "not robust; at least one finalist failed a validity gate"
    elif winner is None or support is None or support < 0.60:
        status = "ambiguous"
        confidence = "ambiguous"
    elif support < 0.80:
        status = "sensitive"
        confidence = "sensitive to cohort composition"
    else:
        status = "robust_within_search_space"
        confidence = "robust within the predeclared finalist search space"
    warnings: list[str] = []
    if plan.smallest_relevant_feature is None:
        warnings.append(
            "No biological equivalence margin was supplied; the numerical fallback "
            "must not be described as an anatomical threshold."
        )
    if all_complete and not all_valid:
        warnings.append(
            "At least one frozen finalist was incomplete, nonconverged, invalid, or "
            "missing a common external metric; automatic robustness is refused."
        )
    if all_complete and support is not None and support < 0.80:
        warnings.append(
            "The preferred finalist changed too often across cohort resamples for a "
            "robust automatic recommendation."
        )
    return ReferenceValidationAssessment(
        version=VALIDATION_ASSESSMENT_VERSION,
        plan_fingerprint=plan.fingerprint,
        status=status,
        recommended_finalist_id=winner.finalist_id if winner else None,
        confidence=confidence,
        winner_support=support,
        practical_error_margin=margin,
        practical_error_margin_basis=margin_basis,
        finalists=tuple(assessments),
        missing_run_ids=missing,
        warnings=tuple(warnings),
        next_gates=plan.required_future_evidence,
    )

"""Transparent, versioned calibration planning for the Deformetrica reference route.

The planner deliberately does not claim to discover a biologically optimal
parameter set from mesh geometry.  It converts a hash-bound aligned-mesh
recommendation into:

* a deterministic, geometrically diverse pilot cohort;
* a staged set of neighboring parameter values;
* explicit rejection and comparison evidence; and
* a publication-oriented provenance record.

The resulting object is a predeclared study plan.  It is not evidence that the
listed pilot runs were executed or that any candidate was scientifically
validated.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_recommendation import (
    MeshGeometryObservation,
    ReferenceParameterRecommendation,
)

CALIBRATION_PLAN_VERSION = "0.1"
CalibrationStageKind = Literal[
    "attachment_width",
    "deformation_width",
    "noise_weight",
    "integration_accuracy",
]


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _positive_finite(name: str, value: float) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return normalized


def _unique_positive(values: tuple[float, ...]) -> tuple[float, ...]:
    result: list[float] = []
    for value in values:
        normalized = _positive_finite("candidate value", value)
        if not any(
            math.isclose(normalized, existing, rel_tol=1e-12, abs_tol=1e-15)
            for existing in result
        ):
            result.append(normalized)
    return tuple(result)


@dataclass(frozen=True)
class RepresentativePilotSubject:
    """One subject selected deterministically for the calibration pilot."""

    filename: str
    sha256: str
    source_subject_index: int
    selection_order: int
    selection_role: str
    descriptor_distance: float

    def as_manifest(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "source_subject_index": self.source_subject_index,
            "selection_order": self.selection_order,
            "selection_role": self.selection_role,
            "descriptor_distance": self.descriptor_distance,
        }


@dataclass(frozen=True)
class CalibrationCandidate:
    """One predeclared candidate within a sequential calibration stage."""

    candidate_id: str
    label: str
    parameter_values: tuple[tuple[str, float], ...]
    rationale: str

    @property
    def values(self) -> dict[str, float]:
        return dict(self.parameter_values)

    def as_manifest(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "label": self.label,
            "parameter_values": self.values,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class CalibrationStage:
    """One sequential comparison with an explicit scientific decision rule."""

    stage_id: str
    order: int
    kind: CalibrationStageKind
    title: str
    candidates: tuple[CalibrationCandidate, ...]
    locked_from_previous_stages: tuple[str, ...]
    evidence_required: tuple[str, ...]
    reject_when: tuple[str, ...]
    decision_rule: str

    def as_manifest(self) -> dict[str, object]:
        return {
            "stage_id": self.stage_id,
            "order": self.order,
            "kind": self.kind,
            "title": self.title,
            "candidates": [candidate.as_manifest() for candidate in self.candidates],
            "locked_from_previous_stages": list(self.locked_from_previous_stages),
            "evidence_required": list(self.evidence_required),
            "reject_when": list(self.reject_when),
            "decision_rule": self.decision_rule,
        }


@dataclass(frozen=True)
class ReferenceCalibrationPlan:
    """Hash-bound, non-executing Deformetrica parameter calibration plan."""

    version: str
    fingerprint: str
    recommendation_fingerprint: str
    template_filename: str
    template_sha256: str
    coordinate_unit: str
    subject_count: int
    requested_pilot_subject_count: int
    selected_pilot_subjects: tuple[RepresentativePilotSubject, ...]
    smallest_relevant_feature: float | None
    attachment_center_source: str
    baseline_parameter_ratios: tuple[tuple[str, float], ...]
    baseline_effective_values: tuple[tuple[str, float], ...]
    stages: tuple[CalibrationStage, ...]
    final_confirmation_required: tuple[str, ...]
    limitations: tuple[str, ...]

    @property
    def pilot_subject_count(self) -> int:
        return len(self.selected_pilot_subjects)

    @property
    def parameter_ratios(self) -> dict[str, float]:
        return dict(self.baseline_parameter_ratios)

    @property
    def effective_values(self) -> dict[str, float]:
        return dict(self.baseline_effective_values)

    @property
    def provenance(self) -> dict[str, object]:
        """Return the complete compact record suitable for ``atlas.yaml``."""

        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "status": "planned_not_executed",
            "recommendation_fingerprint": self.recommendation_fingerprint,
            "template_filename": self.template_filename,
            "template_sha256": self.template_sha256,
            "coordinate_unit": self.coordinate_unit,
            "subject_count": self.subject_count,
            "requested_pilot_subject_count": self.requested_pilot_subject_count,
            "pilot_subject_count": self.pilot_subject_count,
            "selected_pilot_subjects": [
                subject.as_manifest() for subject in self.selected_pilot_subjects
            ],
            "smallest_relevant_feature": self.smallest_relevant_feature,
            "attachment_center_source": self.attachment_center_source,
            "baseline_parameter_ratios": self.parameter_ratios,
            "baseline_effective_values": self.effective_values,
            "stages": [stage.as_manifest() for stage in self.stages],
            "final_confirmation_required": list(self.final_confirmation_required),
            "limitations": list(self.limitations),
        }

    def as_manifest(self) -> dict[str, object]:
        return self.provenance

    def summary_text(self) -> str:
        unit = self.coordinate_unit
        unit_suffix = "" if unit == "unitless" else f" {unit}"
        lines = [
            "Transparent parameter-calibration plan",
            (
                f"Pilot cohort: {self.pilot_subject_count} of {self.subject_count} "
                "subjects (deterministic geometry-diversity selection)."
            ),
            "Selected: "
            + ", ".join(subject.filename for subject in self.selected_pilot_subjects),
        ]
        if self.smallest_relevant_feature is None:
            lines.append(
                "Smallest biologically relevant feature: not measured; the attachment "
                "stage remains centered on the declared surface-detail intent."
            )
        else:
            lines.append(
                "Smallest biologically relevant feature: "
                f"{self.smallest_relevant_feature:.6g}{unit_suffix} "
                "(researcher measurement)."
            )
        for stage in self.stages:
            rendered: list[str] = []
            for candidate in stage.candidates:
                values = candidate.values
                if stage.kind == "integration_accuracy":
                    rendered.append(str(int(values["timepoints"])))
                else:
                    first_value = next(iter(values.values()))
                    rendered.append(f"{first_value:.6g}{unit_suffix}")
            lines.append(f"{stage.order}. {stage.title}: " + " / ".join(rendered))
        lines.extend(
            (
                "Status: planned, not executed. No candidate is scientifically approved.",
                f"Plan fingerprint: {self.fingerprint}",
            )
        )
        return "\n".join(lines)


def _descriptor_matrix(
    observations: tuple[MeshGeometryObservation, ...],
) -> np.ndarray:
    """Return robustly scaled, inexpensive shape/sampling descriptors."""

    raw = np.asarray(
        [
            (
                observation.bounding_box_diagonal,
                observation.rms_radius,
                observation.median_sampled_edge_length,
                math.log1p(observation.points),
                math.log1p(observation.triangles),
            )
            for observation in observations
        ],
        dtype=np.float64,
    )
    center = np.median(raw, axis=0)
    absolute_deviation = np.median(np.abs(raw - center), axis=0)
    standard_deviation = np.std(raw, axis=0)
    scale = np.where(
        absolute_deviation > 1e-15,
        1.4826 * absolute_deviation,
        np.where(standard_deviation > 1e-15, standard_deviation, 1.0),
    )
    normalized = (raw - center) / scale
    normalized[:, np.all(np.abs(raw - raw[0]) <= 1e-15, axis=0)] = 0.0
    return normalized


def select_representative_pilot_subjects(
    recommendation: ReferenceParameterRecommendation,
    *,
    requested_count: int = 8,
) -> tuple[RepresentativePilotSubject, ...]:
    """Select a deterministic medoid plus farthest-first descriptor extremes.

    The first recommendation observation is the template.  Selection is made
    only among subjects and uses inexpensive geometry/sampling descriptors.
    This is a reproducible diversity heuristic, not proof of biological group
    representativeness.
    """

    if isinstance(requested_count, bool) or not isinstance(requested_count, int):
        raise TypeError("requested_count must be an integer")
    if requested_count < 2:
        raise ValueError("requested_count must be at least 2")
    observations = recommendation.observations[1:]
    if len(observations) != recommendation.subject_count:
        raise ConfigurationError(
            "Recommendation observations do not match the declared subject count"
        )
    selected_count = min(requested_count, len(observations))
    descriptors = _descriptor_matrix(observations)
    deltas = descriptors[:, None, :] - descriptors[None, :, :]
    distances = np.sqrt(np.sum(deltas * deltas, axis=2))
    filenames = tuple(observation.filename.casefold() for observation in observations)

    distance_sums = np.sum(distances, axis=1)
    medoid_value = float(np.min(distance_sums))
    medoid_candidates = [
        index
        for index, value in enumerate(distance_sums)
        if math.isclose(float(value), medoid_value, rel_tol=1e-12, abs_tol=1e-15)
    ]
    medoid_index = min(medoid_candidates, key=lambda index: filenames[index])
    selected = [medoid_index]
    selected_distances = [0.0]
    while len(selected) < selected_count:
        remaining = [index for index in range(len(observations)) if index not in selected]
        minimum_to_selected = {
            index: float(np.min(distances[index, selected])) for index in remaining
        }
        farthest_value = max(minimum_to_selected.values())
        tied = [
            index
            for index, value in minimum_to_selected.items()
            if math.isclose(value, farthest_value, rel_tol=1e-12, abs_tol=1e-15)
        ]
        chosen = min(tied, key=lambda index: filenames[index])
        selected.append(chosen)
        selected_distances.append(minimum_to_selected[chosen])

    result: list[RepresentativePilotSubject] = []
    for selection_order, (subject_index, distance) in enumerate(
        zip(selected, selected_distances, strict=True),
        start=1,
    ):
        observation = observations[subject_index]
        result.append(
            RepresentativePilotSubject(
                filename=observation.filename,
                sha256=observation.sha256,
                source_subject_index=subject_index,
                selection_order=selection_order,
                selection_role=(
                    "geometry-descriptor medoid"
                    if selection_order == 1
                    else "farthest-first geometry-descriptor extreme"
                ),
                descriptor_distance=distance,
            )
        )
    return tuple(result)


def _candidate(
    stage_id: str,
    index: int,
    label: str,
    values: dict[str, float],
    rationale: str,
) -> CalibrationCandidate:
    return CalibrationCandidate(
        candidate_id=f"{stage_id}-{index:02d}",
        label=label,
        parameter_values=tuple(values.items()),
        rationale=rationale,
    )


def _plan_payload(
    *,
    recommendation: ReferenceParameterRecommendation,
    coordinate_unit: str,
    requested_pilot_subject_count: int,
    selected: tuple[RepresentativePilotSubject, ...],
    smallest_relevant_feature: float | None,
    attachment_center_source: str,
    baseline_ratios: dict[str, float],
    baseline_effective: dict[str, float],
    stages: tuple[CalibrationStage, ...],
    final_confirmation_required: tuple[str, ...],
    limitations: tuple[str, ...],
) -> dict[str, object]:
    return {
        "version": CALIBRATION_PLAN_VERSION,
        "recommendation_fingerprint": recommendation.fingerprint,
        "template_filename": recommendation.template_filename,
        "template_sha256": recommendation.template_sha256,
        "coordinate_unit": coordinate_unit,
        "subject_count": recommendation.subject_count,
        "requested_pilot_subject_count": requested_pilot_subject_count,
        "selected_pilot_subjects": [item.as_manifest() for item in selected],
        "smallest_relevant_feature": smallest_relevant_feature,
        "attachment_center_source": attachment_center_source,
        "baseline_parameter_ratios": baseline_ratios,
        "baseline_effective_values": baseline_effective,
        "stages": [stage.as_manifest() for stage in stages],
        "final_confirmation_required": list(final_confirmation_required),
        "limitations": list(limitations),
    }


def build_reference_calibration_plan(
    recommendation: ReferenceParameterRecommendation,
    *,
    coordinate_unit: str,
    requested_pilot_subject_count: int = 8,
    smallest_relevant_feature: float | None = None,
) -> ReferenceCalibrationPlan:
    """Build a deterministic staged pilot plan from aligned-mesh evidence."""

    normalized_unit = str(coordinate_unit).strip().lower()
    if not normalized_unit:
        raise ValueError("coordinate_unit must be non-empty")
    if smallest_relevant_feature is not None:
        smallest_relevant_feature = _positive_finite(
            "smallest_relevant_feature", smallest_relevant_feature
        )
    selected = select_representative_pilot_subjects(
        recommendation,
        requested_count=requested_pilot_subject_count,
    )
    diagonal = recommendation.template_diagonal
    sampling_floor = recommendation.sampling_floor_ratio * diagonal
    if smallest_relevant_feature is None:
        attachment_center = recommendation.effective_values["attachment_kernel_width"]
        attachment_center_source = "declared_surface_detail_intent"
    else:
        attachment_center = max(smallest_relevant_feature, sampling_floor)
        attachment_center_source = (
            "researcher_measured_feature_with_mesh_sampling_floor"
        )
    attachment_values = _unique_positive(
        (
            max(sampling_floor, 0.75 * attachment_center),
            attachment_center,
            1.5 * attachment_center,
        )
    )
    deformation_center = recommendation.effective_values[
        "deformation_kernel_width"
    ]
    deformation_values = _unique_positive(
        (
            0.75 * deformation_center,
            deformation_center,
            1.5 * deformation_center,
        )
    )
    noise_center = 0.25 * attachment_center
    noise_values = _unique_positive(
        (0.5 * noise_center, noise_center, 2.0 * noise_center)
    )
    baseline_effective = {
        "attachment_kernel_width": attachment_center,
        "deformation_kernel_width": deformation_center,
        "initial_control_point_spacing": deformation_center,
        "noise_std": noise_center,
    }
    baseline_ratios = {
        name: value / diagonal for name, value in baseline_effective.items()
    }

    attachment_candidates_list: list[CalibrationCandidate] = []
    for index, value in enumerate(attachment_values, start=1):
        if math.isclose(value, attachment_center, rel_tol=1e-12, abs_tol=1e-15):
            label = "center"
            rationale = (
                "Tests the researcher-declared or measured anatomical detail scale."
            )
        elif value < attachment_center:
            label = "detail-first"
            rationale = (
                "Tests finer surface matching without crossing the measured "
                "mesh-sampling floor."
            )
        else:
            label = "smoother comparison"
            rationale = (
                "Tests whether a smoother surface metric is more stable to mesh texture."
            )
        attachment_candidates_list.append(
            _candidate(
                "attachment",
                index,
                label,
                {"attachment_kernel_width": value},
                rationale,
            )
        )
    attachment_candidates = tuple(attachment_candidates_list)
    deformation_candidates = tuple(
        _candidate(
            "deformation",
            index,
            label,
            {
                "deformation_kernel_width": value,
                "initial_control_point_spacing": value,
            },
            rationale,
        )
        for index, (label, value, rationale) in enumerate(
            zip(
                ("more local", "center", "more global"),
                deformation_values,
                (
                    "Tests more localized correlated motion with a denser control grid.",
                    "Tests the declared biological deformation scale.",
                    "Tests smoother, more global motion with fewer initial control points.",
                ),
                strict=True,
            ),
            start=1,
        )
    )
    noise_candidates = tuple(
        _candidate(
            "noise",
            index,
            label,
            {"noise_std": value},
            rationale,
        )
        for index, (label, value, rationale) in enumerate(
            zip(
                ("fit-first", "center", "regularity-first"),
                noise_values,
                (
                    "Gives the attachment term more weight and tests for over-fitting "
                    "or distortion.",
                    "Tests the provisional center only; it is not geometry-derived evidence.",
                    "Gives deformation regularity more relative weight and tests under-fitting.",
                ),
                strict=True,
            ),
            start=1,
        )
    )
    integration_candidates = tuple(
        _candidate(
            "timepoints",
            index,
            f"{timepoints} time points",
            {"timepoints": float(timepoints)},
            "Tests numerical trajectory discretization; scientific parameters remain locked.",
        )
        for index, timepoints in enumerate((10, 20, 30), start=1)
    )
    common_rejections = (
        "the optimizer fails or produces non-finite values",
        "the atlas or any reconstruction contains invalid or flipped faces",
        "registration residuals contain unexplained extreme failures",
        "the visual registration overlay shows anatomically implausible correspondence",
    )
    stages = (
        CalibrationStage(
            stage_id="attachment",
            order=1,
            kind="attachment_width",
            title="Surface-matching detail",
            candidates=attachment_candidates,
            locked_from_previous_stages=(),
            evidence_required=(
                "raw per-subject registration residual median and 95th percentile",
                "registration overlay and residual-location inspection",
                "sensitivity to deterministic mesh resampling",
                "runtime and peak-memory observation",
            ),
            reject_when=common_rejections,
            decision_rule=(
                "Retain the largest width that preserves the predeclared anatomical "
                "feature without systematic residual structure; do not select a width "
                "below the sampling floor."
            ),
        ),
        CalibrationStage(
            stage_id="deformation",
            order=2,
            kind="deformation_width",
            title="Deformation locality and control density",
            candidates=deformation_candidates,
            locked_from_previous_stages=("attachment_kernel_width",),
            evidence_required=(
                "raw residual distribution at the selected attachment width",
                "positive deformation energy and its objective history",
                "local edge stretch, area change, and face-orientation checks",
                "initial/final control-point count, runtime, and peak memory",
            ),
            reject_when=common_rejections,
            decision_rule=(
                "Choose the smoothest deformation whose residual map does not retain "
                "biologically relevant structure; report any move toward a smaller, "
                "more local width as a researcher decision."
            ),
        ),
        CalibrationStage(
            stage_id="noise",
            order=3,
            kind="noise_weight",
            title="Data-fit versus regularity weight",
            candidates=noise_candidates,
            locked_from_previous_stages=(
                "attachment_kernel_width",
                "deformation_kernel_width",
                "initial_control_point_spacing",
            ),
            evidence_required=(
                "raw residual median, 95th percentile, and subject-level distribution",
                "positive deformation energy",
                "fit-versus-regularity Pareto/L-curve view",
                "registration overlay and deformation plausibility review",
            ),
            reject_when=common_rejections,
            decision_rule=(
                "Retain Pareto candidates, then choose the knee that improves residuals "
                "without a disproportionate rise in deformation energy or distortion. "
                "The chosen trade-off remains an explicit scientific decision."
            ),
        ),
        CalibrationStage(
            stage_id="timepoints",
            order=4,
            kind="integration_accuracy",
            title="Numerical integration accuracy",
            candidates=integration_candidates,
            locked_from_previous_stages=(
                "attachment_kernel_width",
                "deformation_kernel_width",
                "initial_control_point_spacing",
                "noise_std",
            ),
            evidence_required=(
                "atlas vertex RMS difference between neighboring time-point counts",
                "objective and residual difference between neighboring counts",
                "runtime scaling",
            ),
            reject_when=(
                "the optimizer fails or produces non-finite values",
                "a lower time-point count changes the atlas beyond the declared "
                "numerical tolerance",
            ),
            decision_rule=(
                "Choose the smallest time-point count whose atlas, objective, and "
                "residuals agree with the next finer discretization within predeclared "
                "numerical tolerances."
            ),
        ),
    )
    final_confirmation_required = (
        "Repeat the selected settings on the complete full-resolution cohort.",
        "Inspect the complete atlas and every registration-quality outlier.",
        "Confirm optimizer convergence or document the iteration cap.",
        "Compare atlas geometry and PCA subspaces with neighboring retained settings.",
        "Record the final researcher approval separately from this pilot plan.",
    )
    limitations = (
        "Geometry descriptors do not establish biological group representativeness.",
        "A measured feature scale records researcher intent; it is not an automatically "
        "discovered anatomical truth.",
        "The plan contains candidate values and decision rules but no execution results.",
        "Residual improvement alone cannot distinguish meaningful fit from over-fitting.",
        "Pilot simplification can change the attachment metric and must be followed by a "
        "full-resolution confirmation.",
    )
    payload = _plan_payload(
        recommendation=recommendation,
        coordinate_unit=normalized_unit,
        requested_pilot_subject_count=requested_pilot_subject_count,
        selected=selected,
        smallest_relevant_feature=smallest_relevant_feature,
        attachment_center_source=attachment_center_source,
        baseline_ratios=baseline_ratios,
        baseline_effective=baseline_effective,
        stages=stages,
        final_confirmation_required=final_confirmation_required,
        limitations=limitations,
    )
    return ReferenceCalibrationPlan(
        version=CALIBRATION_PLAN_VERSION,
        fingerprint=_canonical_hash(payload),
        recommendation_fingerprint=recommendation.fingerprint,
        template_filename=recommendation.template_filename,
        template_sha256=recommendation.template_sha256,
        coordinate_unit=normalized_unit,
        subject_count=recommendation.subject_count,
        requested_pilot_subject_count=requested_pilot_subject_count,
        selected_pilot_subjects=selected,
        smallest_relevant_feature=smallest_relevant_feature,
        attachment_center_source=attachment_center_source,
        baseline_parameter_ratios=tuple(baseline_ratios.items()),
        baseline_effective_values=tuple(baseline_effective.items()),
        stages=stages,
        final_confirmation_required=final_confirmation_required,
        limitations=limitations,
    )


def calibration_plan_json(plan: ReferenceCalibrationPlan) -> str:
    """Return deterministic publication-ready JSON with a trailing newline."""

    return (
        json.dumps(
            plan.as_manifest(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def verify_reference_calibration_plan_provenance(
    provenance: Mapping[str, object],
) -> str:
    """Verify the internal hash and basic structure of stored plan provenance.

    The plan fingerprint binds every scientific input and decision recorded by
    :func:`build_reference_calibration_plan`.  Derived convenience fields are
    checked separately and are excluded from the canonical fingerprint payload.
    """

    manifest = dict(provenance)
    fingerprint = manifest.pop("fingerprint", None)
    status = manifest.pop("status", None)
    pilot_subject_count = manifest.pop("pilot_subject_count", None)
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ConfigurationError(
            "Calibration-plan provenance requires a SHA-256 fingerprint"
        )
    if status != "planned_not_executed":
        raise ConfigurationError(
            "Calibration-plan provenance must be explicitly marked planned_not_executed"
        )
    selected = manifest.get("selected_pilot_subjects")
    if not isinstance(selected, list) or not selected:
        raise ConfigurationError(
            "Calibration-plan provenance requires selected pilot subjects"
        )
    if pilot_subject_count != len(selected):
        raise ConfigurationError(
            "Calibration-plan pilot-subject count does not match its selection"
        )
    stages = manifest.get("stages")
    if not isinstance(stages, list) or [
        stage.get("stage_id") if isinstance(stage, dict) else None for stage in stages
    ] != ["attachment", "deformation", "noise", "timepoints"]:
        raise ConfigurationError(
            "Calibration-plan provenance requires the four ordered calibration stages"
        )
    try:
        recomputed = _canonical_hash(manifest)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(
            "Calibration-plan provenance is not canonical JSON"
        ) from error
    if recomputed != fingerprint:
        raise ConfigurationError(
            "Calibration-plan provenance fingerprint does not match its contents"
        )
    return fingerprint


def reference_calibration_plan_from_provenance(
    provenance: Mapping[str, object],
) -> ReferenceCalibrationPlan:
    """Reconstruct and verify a calibration plan stored in project provenance."""

    verify_reference_calibration_plan_provenance(provenance)
    try:
        selected = tuple(
            RepresentativePilotSubject(
                filename=str(item["filename"]),
                sha256=str(item["sha256"]),
                source_subject_index=int(item["source_subject_index"]),
                selection_order=int(item["selection_order"]),
                selection_role=str(item["selection_role"]),
                descriptor_distance=float(item["descriptor_distance"]),
            )
            for item in provenance["selected_pilot_subjects"]  # type: ignore[index]
        )
        stages = tuple(
            CalibrationStage(
                stage_id=str(stage["stage_id"]),
                order=int(stage["order"]),
                kind=str(stage["kind"]),  # type: ignore[arg-type]
                title=str(stage["title"]),
                candidates=tuple(
                    CalibrationCandidate(
                        candidate_id=str(candidate["candidate_id"]),
                        label=str(candidate["label"]),
                        parameter_values=tuple(
                            (str(name), float(value))
                            for name, value in candidate[
                                "parameter_values"
                            ].items()
                        ),
                        rationale=str(candidate["rationale"]),
                    )
                    for candidate in stage["candidates"]
                ),
                locked_from_previous_stages=tuple(
                    str(value) for value in stage["locked_from_previous_stages"]
                ),
                evidence_required=tuple(
                    str(value) for value in stage["evidence_required"]
                ),
                reject_when=tuple(str(value) for value in stage["reject_when"]),
                decision_rule=str(stage["decision_rule"]),
            )
            for stage in provenance["stages"]  # type: ignore[index]
        )
        feature = provenance["smallest_relevant_feature"]
        return ReferenceCalibrationPlan(
            version=str(provenance["version"]),
            fingerprint=str(provenance["fingerprint"]),
            recommendation_fingerprint=str(
                provenance["recommendation_fingerprint"]
            ),
            template_filename=str(provenance["template_filename"]),
            template_sha256=str(provenance["template_sha256"]),
            coordinate_unit=str(provenance["coordinate_unit"]),
            subject_count=int(provenance["subject_count"]),
            requested_pilot_subject_count=int(
                provenance["requested_pilot_subject_count"]
            ),
            selected_pilot_subjects=selected,
            smallest_relevant_feature=(
                None if feature is None else float(feature)
            ),
            attachment_center_source=str(provenance["attachment_center_source"]),
            baseline_parameter_ratios=tuple(
                (str(name), float(value))
                for name, value in provenance[
                    "baseline_parameter_ratios"
                ].items()  # type: ignore[union-attr]
            ),
            baseline_effective_values=tuple(
                (str(name), float(value))
                for name, value in provenance[
                    "baseline_effective_values"
                ].items()  # type: ignore[union-attr]
            ),
            stages=stages,
            final_confirmation_required=tuple(
                str(value) for value in provenance["final_confirmation_required"]
            ),
            limitations=tuple(str(value) for value in provenance["limitations"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationError(
            "Calibration-plan provenance could not be reconstructed"
        ) from error


@dataclass(frozen=True)
class CalibrationCandidateEvidence:
    """Normalized run evidence supplied after one declared candidate finishes.

    All scientific metrics are raw non-negative quantities for which smaller is
    better.  The evaluator never substitutes missing measurements.
    """

    candidate_id: str
    completed: bool
    converged: bool
    invalid_face_count: int
    residual_p95: float | None
    deformation_energy: float | None
    distortion_p95: float | None
    runtime_seconds: float | None
    resampling_sensitivity: float | None = None
    numerical_atlas_rms: float | None = None
    objective_relative_difference: float | None = None
    residual_relative_difference: float | None = None
    review_approved: bool = False
    notes: tuple[str, ...] = ()

    def as_manifest(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "completed": self.completed,
            "converged": self.converged,
            "invalid_face_count": self.invalid_face_count,
            "residual_p95": self.residual_p95,
            "deformation_energy": self.deformation_energy,
            "distortion_p95": self.distortion_p95,
            "runtime_seconds": self.runtime_seconds,
            "resampling_sensitivity": self.resampling_sensitivity,
            "numerical_atlas_rms": self.numerical_atlas_rms,
            "objective_relative_difference": self.objective_relative_difference,
            "residual_relative_difference": self.residual_relative_difference,
            "review_approved": self.review_approved,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CalibrationCandidateAssessment:
    candidate_id: str
    eligible: bool
    pareto_optimal: bool
    balanced_score: float | None
    rejection_reasons: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "eligible": self.eligible,
            "pareto_optimal": self.pareto_optimal,
            "balanced_score": self.balanced_score,
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True)
class CalibrationStageAssessment:
    """Explainable multi-criterion assessment for one completed stage."""

    version: str
    fingerprint: str
    plan_fingerprint: str
    stage_id: str
    status: str
    balanced_candidate_id: str | None
    pareto_candidate_ids: tuple[str, ...]
    metric_weights: tuple[tuple[str, float], ...]
    candidates: tuple[CalibrationCandidateAssessment, ...]
    cautions: tuple[str, ...]

    @property
    def weights(self) -> dict[str, float]:
        return dict(self.metric_weights)

    def as_manifest(self) -> dict[str, object]:
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "plan_fingerprint": self.plan_fingerprint,
            "stage_id": self.stage_id,
            "status": self.status,
            "balanced_candidate_id": self.balanced_candidate_id,
            "pareto_candidate_ids": list(self.pareto_candidate_ids),
            "metric_weights": self.weights,
            "candidates": [candidate.as_manifest() for candidate in self.candidates],
            "cautions": list(self.cautions),
        }


_ASSESSMENT_VERSION = "0.1"
_STAGE_METRICS: dict[
    CalibrationStageKind,
    tuple[tuple[str, float], ...],
] = {
    "attachment_width": (
        ("residual_p95", 0.45),
        ("resampling_sensitivity", 0.30),
        ("distortion_p95", 0.20),
        ("runtime_seconds", 0.05),
    ),
    "deformation_width": (
        ("residual_p95", 0.35),
        ("deformation_energy", 0.25),
        ("distortion_p95", 0.30),
        ("runtime_seconds", 0.10),
    ),
    "noise_weight": (
        ("residual_p95", 0.35),
        ("deformation_energy", 0.30),
        ("distortion_p95", 0.30),
        ("runtime_seconds", 0.05),
    ),
    "integration_accuracy": (
        ("numerical_atlas_rms", 0.40),
        ("objective_relative_difference", 0.25),
        ("residual_relative_difference", 0.25),
        ("runtime_seconds", 0.10),
    ),
}


def _evidence_metric(
    evidence: CalibrationCandidateEvidence,
    metric: str,
) -> float | None:
    value = getattr(evidence, metric)
    if value is None:
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


def _is_dominated(
    candidate: np.ndarray,
    others: np.ndarray,
) -> bool:
    for other in others:
        if np.all(other <= candidate) and np.any(other < candidate):
            return True
    return False


def assess_calibration_stage(
    plan: ReferenceCalibrationPlan,
    *,
    stage_id: str,
    evidence: tuple[CalibrationCandidateEvidence, ...],
) -> CalibrationStageAssessment:
    """Assess one executed stage without hiding missing data or hard failures.

    The balanced score is an explicitly weighted min-max summary for navigation,
    not an automatic scientific approval.  Only visually approved candidates
    can be eligible, and every Pareto candidate remains visible.
    """

    matching_stages = [stage for stage in plan.stages if stage.stage_id == stage_id]
    if len(matching_stages) != 1:
        raise ValueError(f"Unknown calibration stage: {stage_id!r}")
    stage = matching_stages[0]
    candidate_ids = tuple(candidate.candidate_id for candidate in stage.candidates)
    by_id: dict[str, CalibrationCandidateEvidence] = {}
    for item in evidence:
        if item.candidate_id in by_id:
            raise ValueError(f"Duplicate evidence for candidate {item.candidate_id!r}")
        by_id[item.candidate_id] = item
    if set(by_id) != set(candidate_ids):
        missing = sorted(set(candidate_ids) - set(by_id))
        unexpected = sorted(set(by_id) - set(candidate_ids))
        raise ValueError(
            "Calibration evidence must match the declared stage candidates exactly; "
            f"missing={missing}, unexpected={unexpected}"
        )

    metric_weights = _STAGE_METRICS[stage.kind]
    eligible_ids: list[str] = []
    rejection_reasons: dict[str, tuple[str, ...]] = {}
    metric_rows: list[list[float]] = []
    for candidate_id in candidate_ids:
        item = by_id[candidate_id]
        reasons: list[str] = []
        if not item.completed:
            reasons.append("run did not complete")
        if not item.converged:
            reasons.append("optimizer convergence was not established")
        if (
            isinstance(item.invalid_face_count, bool)
            or not isinstance(item.invalid_face_count, int)
            or item.invalid_face_count < 0
        ):
            reasons.append("invalid-face count is not a non-negative integer")
        elif item.invalid_face_count:
            reasons.append(f"atlas contains {item.invalid_face_count} invalid faces")
        if not item.review_approved:
            reasons.append("visual registration review was not approved")
        row: list[float] = []
        for metric, _weight in metric_weights:
            value = _evidence_metric(item, metric)
            if value is None:
                reasons.append(f"{metric} is missing, negative, or non-finite")
            else:
                row.append(value)
        rejection_reasons[candidate_id] = tuple(reasons)
        if not reasons:
            eligible_ids.append(candidate_id)
            metric_rows.append(row)

    scores: dict[str, float] = {}
    pareto_ids: tuple[str, ...] = ()
    balanced_id: str | None = None
    if eligible_ids:
        values = np.asarray(metric_rows, dtype=np.float64)
        pareto_ids = tuple(
            candidate_id
            for index, candidate_id in enumerate(eligible_ids)
            if not _is_dominated(values[index], np.delete(values, index, axis=0))
        )
        minimum = np.min(values, axis=0)
        span = np.max(values, axis=0) - minimum
        normalized = np.divide(
            values - minimum,
            span,
            out=np.zeros_like(values),
            where=span > 0,
        )
        weights = np.asarray([weight for _metric, weight in metric_weights])
        weighted = normalized @ weights
        scores = {
            candidate_id: float(weighted[index])
            for index, candidate_id in enumerate(eligible_ids)
        }
        balanced_id = min(
            pareto_ids,
            key=lambda candidate_id: (scores[candidate_id], candidate_id),
        )

    assessments = tuple(
        CalibrationCandidateAssessment(
            candidate_id=candidate_id,
            eligible=candidate_id in eligible_ids,
            pareto_optimal=candidate_id in pareto_ids,
            balanced_score=scores.get(candidate_id),
            rejection_reasons=rejection_reasons[candidate_id],
        )
        for candidate_id in candidate_ids
    )
    status = (
        "review_required"
        if eligible_ids
        else "no_eligible_candidate"
    )
    cautions = (
        "The balanced candidate is a transparent navigation aid, not an automatic approval.",
        "All Pareto-optimal candidates and raw evidence must remain available to the researcher.",
        "A stage decision becomes valid only after explicit researcher approval and "
        "full-resolution confirmation.",
    )
    payload = {
        "version": _ASSESSMENT_VERSION,
        "plan_fingerprint": plan.fingerprint,
        "stage_id": stage_id,
        "status": status,
        "balanced_candidate_id": balanced_id,
        "pareto_candidate_ids": list(pareto_ids),
        "metric_weights": dict(metric_weights),
        "evidence": [by_id[candidate_id].as_manifest() for candidate_id in candidate_ids],
        "candidates": [candidate.as_manifest() for candidate in assessments],
        "cautions": list(cautions),
    }
    return CalibrationStageAssessment(
        version=_ASSESSMENT_VERSION,
        fingerprint=_canonical_hash(payload),
        plan_fingerprint=plan.fingerprint,
        stage_id=stage_id,
        status=status,
        balanced_candidate_id=balanced_id,
        pareto_candidate_ids=pareto_ids,
        metric_weights=metric_weights,
        candidates=assessments,
        cautions=cautions,
    )

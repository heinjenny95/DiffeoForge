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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_recommendation import (
    MeshGeometryObservation,
    ReferenceParameterRecommendation,
)

CALIBRATION_PLAN_VERSION = "0.3"
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


def _geometric_candidates(
    lower: float,
    upper: float,
    *,
    count: int,
    include: tuple[float, ...] = (),
) -> tuple[float, ...]:
    """Return a deterministic, scale-balanced positive candidate sequence."""

    low = _positive_finite("candidate lower bound", lower)
    high = _positive_finite("candidate upper bound", upper)
    if high < low:
        low, high = high, low
    if count < 2:
        raise ValueError("geometric candidate count must be at least two")
    if math.isclose(low, high, rel_tol=1e-12, abs_tol=1e-15):
        values = [low]
    else:
        ratio = (high / low) ** (1.0 / (count - 1))
        values = [low * ratio**index for index in range(count)]
    for requested in include:
        requested = _positive_finite("included candidate", requested)
        if requested < low or requested > high:
            continue
        if any(
            math.isclose(requested, existing, rel_tol=1e-12, abs_tol=1e-15)
            for existing in values
        ):
            continue
        closest = min(
            range(len(values)),
            key=lambda index: abs(math.log(values[index] / requested)),
        )
        values[closest] = requested
    return tuple(sorted(_unique_positive(tuple(values))))


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
    expected_shape_disparity: str = "moderate"
    search_extension_lineage: tuple[tuple[str, str], ...] = ()

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

        provenance: dict[str, object] = {
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
            "expected_shape_disparity": self.expected_shape_disparity,
            "baseline_parameter_ratios": self.parameter_ratios,
            "baseline_effective_values": self.effective_values,
            "stages": [stage.as_manifest() for stage in self.stages],
            "final_confirmation_required": list(self.final_confirmation_required),
            "limitations": list(self.limitations),
        }
        if self.search_extension_lineage:
            provenance["search_extension_lineage"] = dict(
                self.search_extension_lineage
            )
        return provenance

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
            (
                "Expected biological shape disparity: "
                f"{self.expected_shape_disparity}. This controls the tested amplitude "
                "range, independently of local/global deformation reach."
            ),
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
            if stage.stage_id == "attachment":
                attachment_values = sorted(
                    {
                        candidate.values["attachment_kernel_width"]
                        for candidate in stage.candidates
                    }
                )
                deformation_values = sorted(
                    {
                        candidate.values["deformation_kernel_width"]
                        for candidate in stage.candidates
                    }
                )
                lines.append(
                    f"{stage.order}. {stage.title}: {len(stage.candidates)} joint "
                    f"candidates; attachment {attachment_values[0]:.6g}–"
                    f"{attachment_values[-1]:.6g}{unit_suffix}; deformation "
                    f"{deformation_values[0]:.6g}–{deformation_values[-1]:.6g}"
                    f"{unit_suffix}."
                )
                continue
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
                "Total planned pilot atlases: "
                f"{sum(len(stage.candidates) for stage in self.stages)}.",
                "Status: planned, not executed. No candidate is scientifically approved.",
                f"Plan fingerprint: {self.fingerprint}",
            )
        )
        if self.search_extension_lineage:
            lineage = dict(self.search_extension_lineage)
            lines.append(
                "Search extension: hash-bound successor of plan "
                f"{lineage['parent_plan_fingerprint'][:12]}… from assessment "
                f"{lineage['source_assessment_fingerprint'][:12]}…."
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
        "expected_shape_disparity": recommendation.expected_shape_disparity,
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
    sampling_diagnostic = recommendation.sampling_floor_ratio * diagonal
    median_edge = recommendation.median_edge_to_diagonal_ratio * diagonal
    if smallest_relevant_feature is None:
        attachment_center = recommendation.effective_values["attachment_kernel_width"]
        attachment_center_source = "declared_surface_detail_intent"
    else:
        attachment_center = smallest_relevant_feature
        attachment_center_source = "researcher_measured_feature"
    # Search on a logarithmic scale and deliberately cross the conservative
    # four-edge sampling diagnostic.  Mesh sampling constrains interpretation,
    # but it is not a proven hard lower bound for the varifold/current kernel.
    attachment_lower = max(0.005 * diagonal, min(0.5 * attachment_center, median_edge))
    attachment_upper = min(
        0.5 * diagonal,
        max(2.0 * attachment_center, sampling_diagnostic),
    )
    attachment_values = _geometric_candidates(
        attachment_lower,
        attachment_upper,
        count=6,
        include=(attachment_center,),
    )
    deformation_center = recommendation.effective_values[
        "deformation_kernel_width"
    ]
    disparity_lower, disparity_upper = {
        "low": (0.75, 1.5),
        "moderate": (0.5, 2.0),
        "high": (0.35, 3.0),
        "extreme": (0.25, 4.0),
    }[recommendation.expected_shape_disparity]
    deformation_values = _geometric_candidates(
        disparity_lower * deformation_center,
        disparity_upper * deformation_center,
        count=5,
        include=(deformation_center,),
    )
    deformation_screen_values = (
        disparity_lower * deformation_center,
        deformation_center,
        disparity_upper * deformation_center,
    )
    noise_center = 0.25 * attachment_center
    noise_values = _geometric_candidates(
        0.25 * noise_center,
        4.0 * noise_center,
        count=5,
        include=(noise_center,),
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
    candidate_index = 0
    for attachment_value in attachment_values:
        for deformation_value in deformation_screen_values:
            candidate_index += 1
            attachment_relation = (
                "finer"
                if attachment_value < attachment_center
                else (
                    "declared center"
                    if math.isclose(
                        attachment_value,
                        attachment_center,
                        rel_tol=1e-12,
                        abs_tol=1e-15,
                    )
                    else "smoother"
                )
            )
            deformation_relation = (
                "more local"
                if deformation_value < deformation_center
                else (
                    "declared center"
                    if math.isclose(
                        deformation_value,
                        deformation_center,
                        rel_tol=1e-12,
                        abs_tol=1e-15,
                    )
                    else "more global"
                )
            )
            attachment_candidates_list.append(
                _candidate(
                    "attachment",
                    candidate_index,
                    f"{attachment_relation} surface / {deformation_relation} deformation",
                    {
                        "attachment_kernel_width": attachment_value,
                        "deformation_kernel_width": deformation_value,
                        "initial_control_point_spacing": deformation_value,
                    },
                    (
                        "Jointly screens surface-matching resolution and deformation "
                        "reach so their interaction is observed before either is locked."
                    ),
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
        for index, value in enumerate(deformation_values, start=1)
        for label, rationale in (
            (
                (
                    "more local"
                    if value < deformation_center
                    else (
                        "declared center"
                        if math.isclose(
                            value,
                            deformation_center,
                            rel_tol=1e-12,
                            abs_tol=1e-15,
                        )
                        else "more global"
                    )
                ),
                "Refines deformation reach after the joint kernel interaction screen.",
            ),
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
        for index, value in enumerate(noise_values, start=1)
        for label, rationale in (
            (
                (
                    "fit-first"
                    if value < noise_center
                    else (
                        "provisional center"
                        if math.isclose(
                            value,
                            noise_center,
                            rel_tol=1e-12,
                            abs_tol=1e-15,
                        )
                        else "regularity-first"
                    )
                ),
                "Tests a logarithmically spaced fit-versus-regularity trade-off; the "
                "center is only a computational seed, not geometry-derived evidence.",
            ),
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
        "the atlas or any reconstruction contains invalid faces or changed connectivity",
        "registration residuals contain unexplained extreme failures",
        "an optional visual registration review explicitly records implausible "
        "correspondence",
    )
    stages = (
        CalibrationStage(
            stage_id="attachment",
            order=1,
            kind="attachment_width",
            title="Joint surface-detail and deformation-scale screening",
            candidates=attachment_candidates,
            locked_from_previous_stages=(),
            evidence_required=(
                "raw per-subject registration residual median and 95th percentile",
                "bound original and reconstructed surfaces retained for optional "
                "visual inspection",
                "sensitivity to deterministic mesh resampling",
                "deformation regularity and reconstructed-surface distortion",
                "runtime and peak-memory observation",
            ),
            reject_when=common_rejections,
            decision_rule=(
                "Screen attachment and deformation widths jointly. Retain a Pareto "
                "candidate only when its advantage remains stable across subjects and "
                "reasonable metric weightings. The four-edge sampling value is a "
                "diagnostic, not an exclusion boundary."
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
                "Choose deformation reach from residual structure and plausibility. "
                "Do not treat the amplitude of required, biologically expected change "
                "as a defect by itself; report any local/global reach choice separately."
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
        "The conservative four-edge sampling diagnostic is not a universal scientific "
        "lower bound and therefore expands, but does not truncate, the search.",
        "The plan contains candidate values and decision rules but no execution results.",
        "Residual improvement alone cannot distinguish meaningful fit from over-fitting.",
        "Large deformation energy or area change can be biologically necessary for the "
        "declared disparity; topology failures and implausible correspondence remain "
        "rejection evidence, while amplitude alone is not.",
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
        expected_shape_disparity=recommendation.expected_shape_disparity,
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


def bind_reference_calibration_plan_to_inputs(
    plan: ReferenceCalibrationPlan,
    *,
    template: Path | str,
    subjects: Sequence[Path | str],
) -> ReferenceCalibrationPlan:
    """Bind a scientific pilot design to its effective execution files.

    DiffeoForge can analyze raw meshes through approved in-memory GPA transforms
    before it publishes canonical aligned VTK inputs.  The scientific candidate
    design stays unchanged, but the execution plan must bind the bytes that the
    calibration worker will actually read.  This function performs that final,
    hash-bound transition without rerunning or changing the pilot selection.
    """

    template_path = Path(template).expanduser().resolve()
    subject_paths = tuple(Path(path).expanduser().resolve() for path in subjects)
    if template_path.name != plan.template_filename:
        raise ConfigurationError(
            "Effective calibration template filename differs from the planned template"
        )
    if len(subject_paths) != plan.subject_count:
        raise ConfigurationError(
            "Effective calibration subject count differs from the planned cohort"
        )
    names = tuple(path.name for path in subject_paths)
    if len(set(names)) != len(names):
        raise ConfigurationError(
            "Effective calibration subject filenames must be unique"
        )
    by_name = dict(zip(names, subject_paths, strict=True))
    for selected in plan.selected_pilot_subjects:
        path = by_name.get(selected.filename)
        if path is None:
            raise ConfigurationError(
                "Effective calibration inputs do not contain selected subject "
                f"{selected.filename!r}"
            )
        if (
            selected.source_subject_index < 0
            or selected.source_subject_index >= len(subject_paths)
            or subject_paths[selected.source_subject_index].name != selected.filename
        ):
            raise ConfigurationError(
                "Effective calibration subject order differs from the planned cohort"
            )

    paths = (template_path, *subject_paths)
    hashes = tuple(sha256_file(path) for path in paths)
    if tuple(sha256_file(path) for path in paths) != hashes:
        raise ConfigurationError(
            "An effective calibration input changed while its plan was being bound"
        )
    subject_hashes = dict(zip(names, hashes[1:], strict=True))
    selected = tuple(
        replace(item, sha256=subject_hashes[item.filename])
        for item in plan.selected_pilot_subjects
    )
    rebound = replace(
        plan,
        fingerprint="",
        template_sha256=hashes[0],
        selected_pilot_subjects=selected,
    )
    payload = rebound.provenance
    payload.pop("fingerprint")
    payload.pop("status")
    payload.pop("pilot_subject_count")
    return replace(rebound, fingerprint=_canonical_hash(payload))


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
    lineage_value = provenance.get("search_extension_lineage", {})
    if not isinstance(lineage_value, Mapping):
        raise ConfigurationError(
            "Calibration search-extension lineage must be a mapping"
        )
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
            expected_shape_disparity=str(
                provenance.get("expected_shape_disparity", "moderate")
            ),
            search_extension_lineage=tuple(
                (str(name), str(value))
                for name, value in lineage_value.items()
            ),
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
    review_approved: bool | None = None
    notes: tuple[str, ...] = ()
    subject_residual_p95: tuple[tuple[str, float], ...] = ()

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
            "subject_residual_p95": dict(self.subject_residual_p95),
        }


@dataclass(frozen=True)
class CalibrationCandidateAssessment:
    candidate_id: str
    eligible: bool
    pareto_optimal: bool
    balanced_score: float | None
    weight_win_fraction: float | None
    subject_bootstrap_win_fraction: float | None
    score_range: tuple[float, float] | None
    rejection_reasons: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "eligible": self.eligible,
            "pareto_optimal": self.pareto_optimal,
            "balanced_score": self.balanced_score,
            "weight_win_fraction": self.weight_win_fraction,
            "subject_bootstrap_win_fraction": self.subject_bootstrap_win_fraction,
            "score_range": (
                None if self.score_range is None else list(self.score_range)
            ),
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
    recommendation_confidence: str
    automatic_selection_allowed: bool
    weight_stability: float | None
    subject_bootstrap_stability: float | None
    score_margin: float | None
    independent_rank_candidate_id: str | None
    weight_scenario_count: int
    subject_bootstrap_iterations: int
    search_range_status: str
    search_boundary_parameters: tuple[str, ...]
    sensitivity_flags: tuple[str, ...]
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
            "recommendation_confidence": self.recommendation_confidence,
            "automatic_selection_allowed": self.automatic_selection_allowed,
            "weight_stability": self.weight_stability,
            "subject_bootstrap_stability": self.subject_bootstrap_stability,
            "score_margin": self.score_margin,
            "independent_rank_candidate_id": self.independent_rank_candidate_id,
            "weight_scenario_count": self.weight_scenario_count,
            "subject_bootstrap_iterations": self.subject_bootstrap_iterations,
            "search_range_status": self.search_range_status,
            "search_boundary_parameters": list(self.search_boundary_parameters),
            "sensitivity_flags": list(self.sensitivity_flags),
            "pareto_candidate_ids": list(self.pareto_candidate_ids),
            "metric_weights": self.weights,
            "candidates": [candidate.as_manifest() for candidate in self.candidates],
            "cautions": list(self.cautions),
        }


_ASSESSMENT_VERSION = "0.4"
_SEARCH_PARAMETERS: dict[CalibrationStageKind, tuple[str, ...]] = {
    "attachment_width": (
        "attachment_kernel_width",
        "deformation_kernel_width",
        "initial_control_point_spacing",
    ),
    "deformation_width": (
        "deformation_kernel_width",
        "initial_control_point_spacing",
    ),
    "noise_weight": ("noise_std",),
    "integration_accuracy": (),
}
_SEARCH_PARAMETER_LABELS = {
    "attachment_kernel_width": "attachment surface-matching width",
    "deformation_kernel_width": "deformation kernel width",
    "initial_control_point_spacing": "control-point spacing",
    "noise_std": "noise standard deviation",
}
_SEARCH_EXTENSION_GROUPS = (
    ("attachment", ("attachment_kernel_width",)),
    (
        "deformation/control spacing",
        ("deformation_kernel_width", "initial_control_point_spacing"),
    ),
    ("noise", ("noise_std",)),
)


@dataclass(frozen=True)
class CalibrationSearchExtensionProposal:
    """Hash-bound outward neighbors proposed from one unbounded assessment."""

    version: str
    fingerprint: str
    plan_fingerprint: str
    assessment_fingerprint: str
    stage_id: str
    source_candidate_id: str
    outward_steps: int
    boundary_parameters: tuple[str, ...]
    candidates: tuple[CalibrationCandidate, ...]
    limitations: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "plan_fingerprint": self.plan_fingerprint,
            "assessment_fingerprint": self.assessment_fingerprint,
            "stage_id": self.stage_id,
            "source_candidate_id": self.source_candidate_id,
            "outward_steps": self.outward_steps,
            "boundary_parameters": list(self.boundary_parameters),
            "candidates": [candidate.as_manifest() for candidate in self.candidates],
            "limitations": list(self.limitations),
        }


def _search_boundary_parameters(
    stage: CalibrationStage,
    selected_candidate_id: str | None,
) -> tuple[str, tuple[str, ...]]:
    """Describe whether a provisional winner lies inside every searched range."""

    parameters = _SEARCH_PARAMETERS[stage.kind]
    if not parameters:
        return "not_applicable", ()
    if selected_candidate_id is None:
        return "not_evaluated", ()
    selected = next(
        candidate
        for candidate in stage.candidates
        if candidate.candidate_id == selected_candidate_id
    )
    boundaries: list[str] = []
    for parameter in parameters:
        values = sorted(
            _unique_positive(
                tuple(
                    candidate.values[parameter]
                    for candidate in stage.candidates
                    if parameter in candidate.values
                )
            )
        )
        if not values or parameter not in selected.values:
            continue
        value = selected.values[parameter]
        at_minimum = math.isclose(value, values[0], rel_tol=1e-12, abs_tol=1e-15)
        at_maximum = math.isclose(value, values[-1], rel_tol=1e-12, abs_tol=1e-15)
        if at_minimum and at_maximum:
            boundaries.append(f"{parameter}:only_tested_value")
        elif at_minimum:
            boundaries.append(f"{parameter}:minimum")
        elif at_maximum:
            boundaries.append(f"{parameter}:maximum")
    return ("not_bounded" if boundaries else "bounded"), tuple(boundaries)


def propose_calibration_search_extension(
    plan: ReferenceCalibrationPlan,
    assessment: CalibrationStageAssessment,
    *,
    outward_steps: int = 2,
) -> CalibrationSearchExtensionProposal:
    """Propose one or two logarithmic neighbors beyond every winning boundary.

    This function only creates a hash-bound proposal. It does not mutate the
    immutable pilot, execute Deformetrica, or represent the new values as safe.
    A future successor study must bind and run the proposal before the search
    can be reassessed.
    """

    if isinstance(outward_steps, bool) or not isinstance(outward_steps, int):
        raise TypeError("outward_steps must be an integer")
    if outward_steps not in {1, 2}:
        raise ValueError("outward_steps must be one or two")
    if assessment.plan_fingerprint != plan.fingerprint:
        raise ValueError("assessment is bound to a different calibration plan")
    if assessment.search_range_status != "not_bounded":
        raise ValueError("search extension requires a not_bounded assessment")
    if assessment.balanced_candidate_id is None:
        raise ValueError("search extension requires a provisional candidate")
    stage = next(
        (stage for stage in plan.stages if stage.stage_id == assessment.stage_id),
        None,
    )
    if stage is None:
        raise ValueError("assessment stage is absent from the calibration plan")
    source = next(
        candidate
        for candidate in stage.candidates
        if candidate.candidate_id == assessment.balanced_candidate_id
    )
    boundary_by_parameter = dict(
        boundary.split(":", maxsplit=1)
        for boundary in assessment.search_boundary_parameters
    )
    additions: list[CalibrationCandidate] = []
    for group_label, parameters in _SEARCH_EXTENSION_GROUPS:
        active = [parameter for parameter in parameters if parameter in boundary_by_parameter]
        if not active:
            continue
        directions = {boundary_by_parameter[parameter] for parameter in active}
        if len(directions) != 1 or "only_tested_value" in directions:
            raise ValueError(
                f"cannot geometrically extend {group_label} without two ordered values"
            )
        direction = directions.pop()
        primary = active[0]
        values = sorted(
            _unique_positive(
                tuple(
                    candidate.values[primary]
                    for candidate in stage.candidates
                    if primary in candidate.values
                )
            )
        )
        if len(values) < 2:
            raise ValueError(
                f"cannot geometrically extend {group_label} without two ordered values"
            )
        ratio = values[1] / values[0] if direction == "minimum" else values[-1] / values[-2]
        if not math.isfinite(ratio) or ratio <= 1.0:
            raise ValueError(f"cannot derive an outward logarithmic ratio for {group_label}")
        for step in range(1, outward_steps + 1):
            outward_value = (
                source.values[primary] / ratio**step
                if direction == "minimum"
                else source.values[primary] * ratio**step
            )
            outward_value = _positive_finite("outward candidate value", outward_value)
            proposed_values = source.values
            for parameter in parameters:
                if parameter in proposed_values:
                    proposed_values[parameter] = outward_value
            additions.append(
                _candidate(
                    f"{stage.stage_id}-outward",
                    len(additions) + 1,
                    f"{group_label} beyond tested {direction} · step {step}",
                    proposed_values,
                    (
                        f"Extends the {group_label} logarithmic search one observed grid "
                        f"ratio beyond the prior {direction}; all other selected stage "
                        "values remain fixed."
                    ),
                )
            )
    limitations = (
        "This is an unexecuted outward-neighbor proposal, not a safe parameter claim.",
        "The immutable source pilot and its evidence remain unchanged.",
        "A separately bound successor study must execute these candidates and reassess "
        "the combined evidence before the search can be described as bounded.",
        "Feasibility and safety limits must be declared by that successor before execution.",
    )
    payload = {
        "version": "0.1",
        "plan_fingerprint": plan.fingerprint,
        "assessment_fingerprint": assessment.fingerprint,
        "stage_id": stage.stage_id,
        "source_candidate_id": source.candidate_id,
        "outward_steps": outward_steps,
        "boundary_parameters": list(assessment.search_boundary_parameters),
        "candidates": [candidate.as_manifest() for candidate in additions],
        "limitations": list(limitations),
    }
    return CalibrationSearchExtensionProposal(
        version="0.1",
        fingerprint=_canonical_hash(payload),
        plan_fingerprint=plan.fingerprint,
        assessment_fingerprint=assessment.fingerprint,
        stage_id=stage.stage_id,
        source_candidate_id=source.candidate_id,
        outward_steps=outward_steps,
        boundary_parameters=assessment.search_boundary_parameters,
        candidates=tuple(additions),
        limitations=limitations,
    )


def bind_calibration_search_extension_plan(
    plan: ReferenceCalibrationPlan,
    assessment: CalibrationStageAssessment,
    proposal: CalibrationSearchExtensionProposal,
) -> ReferenceCalibrationPlan:
    """Return a new immutable plan containing the bound outward candidates."""

    if assessment.plan_fingerprint != plan.fingerprint:
        raise ValueError("assessment is bound to a different calibration plan")
    if proposal.plan_fingerprint != plan.fingerprint:
        raise ValueError("extension proposal is bound to a different calibration plan")
    if proposal.assessment_fingerprint != assessment.fingerprint:
        raise ValueError("extension proposal is bound to a different assessment")
    if proposal.stage_id != assessment.stage_id:
        raise ValueError("extension proposal stage differs from its assessment")
    expected_proposal = propose_calibration_search_extension(
        plan,
        assessment,
        outward_steps=proposal.outward_steps,
    )
    if proposal != expected_proposal:
        raise ValueError("extension proposal differs from its deterministic derivation")
    stages = []
    found = False
    for stage in plan.stages:
        if stage.stage_id != proposal.stage_id:
            stages.append(stage)
            continue
        found = True
        stages.append(
            replace(
                stage,
                candidates=stage.candidates + proposal.candidates,
                decision_rule=(
                    stage.decision_rule
                    + " Outward successor candidates were added because the prior "
                    "provisional winner lay on a tested search boundary; reassess all "
                    "preserved and successor evidence together."
                ),
            )
        )
    if not found:
        raise ValueError("extension stage is absent from the calibration plan")
    lineage = (
        ("parent_plan_fingerprint", plan.fingerprint),
        ("source_assessment_fingerprint", assessment.fingerprint),
        ("proposal_fingerprint", proposal.fingerprint),
        ("stage_id", proposal.stage_id),
    )
    successor = replace(
        plan,
        version="0.4",
        fingerprint="",
        stages=tuple(stages),
        search_extension_lineage=lineage,
        limitations=(
            *plan.limitations,
            "This successor adds hash-bound outward candidates; their values are not "
            "scientifically usable until executed and assessed with the preserved "
            "source evidence.",
        ),
    )
    payload = successor.provenance
    payload.pop("fingerprint")
    payload.pop("status")
    payload.pop("pilot_subject_count")
    return replace(successor, fingerprint=_canonical_hash(payload))
_STAGE_METRICS: dict[
    CalibrationStageKind,
    tuple[tuple[str, float], ...],
] = {
    "attachment_width": (
        ("residual_p95", 0.35),
        ("resampling_sensitivity", 0.20),
        ("deformation_energy", 0.15),
        ("distortion_p95", 0.25),
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


def _stage_metrics_for_disparity(
    kind: CalibrationStageKind,
    expected_shape_disparity: str,
) -> tuple[tuple[str, float], ...]:
    """Return transparent priorities without equating amplitude with pathology."""

    if expected_shape_disparity in {"low", "moderate"}:
        return _STAGE_METRICS[kind]
    if kind == "integration_accuracy":
        return _STAGE_METRICS[kind]
    if expected_shape_disparity == "high":
        return {
            "attachment_width": (
                ("residual_p95", 0.55),
                ("resampling_sensitivity", 0.25),
                ("distortion_p95", 0.10),
                ("runtime_seconds", 0.10),
            ),
            "deformation_width": (
                ("residual_p95", 0.65),
                ("distortion_p95", 0.20),
                ("runtime_seconds", 0.15),
            ),
            "noise_weight": (
                ("residual_p95", 0.65),
                ("distortion_p95", 0.20),
                ("runtime_seconds", 0.15),
            ),
        }[kind]
    if expected_shape_disparity == "extreme":
        return {
            "attachment_width": (
                ("residual_p95", 0.60),
                ("resampling_sensitivity", 0.25),
                ("runtime_seconds", 0.15),
            ),
            "deformation_width": (
                ("residual_p95", 0.80),
                ("runtime_seconds", 0.20),
            ),
            "noise_weight": (
                ("residual_p95", 0.80),
                ("runtime_seconds", 0.20),
            ),
        }[kind]
    raise ValueError(
        f"Unsupported expected shape disparity: {expected_shape_disparity!r}"
    )


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


def _normalize_metric_rows(values: np.ndarray) -> np.ndarray:
    minimum = np.min(values, axis=0)
    span = np.max(values, axis=0) - minimum
    return np.divide(
        values - minimum,
        span,
        out=np.zeros_like(values),
        where=span > 0,
    )


def _weight_scenarios(base: np.ndarray) -> tuple[np.ndarray, ...]:
    """Exercise reasonable priorities instead of trusting one hand-set weighting."""

    raw: list[np.ndarray] = [base.copy(), np.ones_like(base)]
    for index in range(len(base)):
        for multiplier in (0.5, 2.0):
            changed = base.copy()
            changed[index] *= multiplier
            raw.append(changed)
        if len(base) > 1:
            omitted = base.copy()
            omitted[index] = 0.0
            raw.append(omitted)
    unique: list[np.ndarray] = []
    signatures: set[tuple[float, ...]] = set()
    for values in raw:
        normalized = values / np.sum(values)
        signature = tuple(round(float(value), 12) for value in normalized)
        if signature not in signatures:
            signatures.add(signature)
            unique.append(normalized)
    return tuple(unique)


def _weighted_rank_winner(
    values: np.ndarray,
    weights: np.ndarray,
    candidate_ids: list[str],
    allowed_ids: tuple[str, ...],
) -> str:
    ranks = np.zeros_like(values)
    for metric_index in range(values.shape[1]):
        column = values[:, metric_index]
        for candidate_index, value in enumerate(column):
            lower = float(np.sum(column < value))
            equal = float(np.sum(column == value))
            ranks[candidate_index, metric_index] = lower + 0.5 * (equal - 1.0)
    aggregate = ranks @ weights
    index_by_id = {candidate_id: index for index, candidate_id in enumerate(candidate_ids)}
    return min(
        allowed_ids,
        key=lambda candidate_id: (
            float(aggregate[index_by_id[candidate_id]]),
            candidate_id,
        ),
    )


def _subject_bootstrap_wins(
    *,
    plan_fingerprint: str,
    stage_id: str,
    eligible_ids: list[str],
    by_id: Mapping[str, CalibrationCandidateEvidence],
    values: np.ndarray,
    metric_names: tuple[str, ...],
    weights: np.ndarray,
    iterations: int = 256,
) -> tuple[dict[str, float], int]:
    if "residual_p95" not in metric_names or len(eligible_ids) < 2:
        return {}, 0
    subject_maps = {
        candidate_id: dict(by_id[candidate_id].subject_residual_p95)
        for candidate_id in eligible_ids
    }
    names = tuple(sorted(next(iter(subject_maps.values()), {})))
    mismatched_subjects = any(
        tuple(sorted(values_by_subject)) != names
        for values_by_subject in subject_maps.values()
    )
    if len(names) < 3 or mismatched_subjects:
        return {}, 0
    if any(
        not math.isfinite(float(subject_maps[candidate_id][name]))
        or float(subject_maps[candidate_id][name]) < 0
        for candidate_id in eligible_ids
        for name in names
    ):
        return {}, 0
    residual_index = metric_names.index("residual_p95")
    residuals = np.asarray(
        [
            [float(subject_maps[candidate_id][name]) for name in names]
            for candidate_id in eligible_ids
        ],
        dtype=np.float64,
    )
    seed_material = f"{plan_fingerprint}:{stage_id}:subject-bootstrap-v0.1"
    seed = int(hashlib.sha256(seed_material.encode("ascii")).hexdigest()[:16], 16)
    rng = np.random.default_rng(seed)
    wins = {candidate_id: 0 for candidate_id in eligible_ids}
    for _ in range(iterations):
        sample = rng.integers(0, len(names), size=len(names))
        bootstrap_values = values.copy()
        bootstrap_values[:, residual_index] = np.median(residuals[:, sample], axis=1)
        pareto = tuple(
            candidate_id
            for index, candidate_id in enumerate(eligible_ids)
            if not _is_dominated(
                bootstrap_values[index],
                np.delete(bootstrap_values, index, axis=0),
            )
        )
        scores = _normalize_metric_rows(bootstrap_values) @ weights
        index_by_id = {
            candidate_id: index for index, candidate_id in enumerate(eligible_ids)
        }
        winner = min(
            pareto,
            key=lambda candidate_id: (
                float(scores[index_by_id[candidate_id]]),
                candidate_id,
            ),
        )
        wins[winner] += 1
    return (
        {
            candidate_id: count / iterations
            for candidate_id, count in wins.items()
        },
        iterations,
    )


def assess_calibration_stage(
    plan: ReferenceCalibrationPlan,
    *,
    stage_id: str,
    evidence: tuple[CalibrationCandidateEvidence, ...],
) -> CalibrationStageAssessment:
    """Assess one executed stage without hiding missing data or hard failures.

    The balanced score is an explicitly weighted min-max summary.  It may drive
    a provisional automatic recommendation among the predeclared candidates,
    but never constitutes automatic anatomical approval or final scientific
    validation.  Visual QC is optional; an explicit visual failure makes a
    candidate ineligible, while an unreviewed candidate remains eligible when
    its automatic evidence is valid.
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

    metric_weights = _stage_metrics_for_disparity(
        stage.kind,
        getattr(plan, "expected_shape_disparity", "moderate"),
    )
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
            reasons.append(
                "atlas or reconstructions contain "
                f"{item.invalid_face_count} invalid faces"
            )
        if item.review_approved is False:
            reasons.append("optional visual registration review explicitly failed")
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
    score_ranges: dict[str, tuple[float, float]] = {}
    weight_win_fractions: dict[str, float] = {}
    bootstrap_win_fractions: dict[str, float] = {}
    pareto_ids: tuple[str, ...] = ()
    balanced_id: str | None = None
    rank_id: str | None = None
    weight_stability: float | None = None
    bootstrap_stability: float | None = None
    score_margin: float | None = None
    weight_scenario_count = 0
    bootstrap_iterations = 0
    search_range_status = "not_evaluated"
    search_boundary_parameters: tuple[str, ...] = ()
    confidence = "none"
    automatic_selection_allowed = False
    sensitivity_flags: list[str] = []
    if eligible_ids:
        values = np.asarray(metric_rows, dtype=np.float64)
        pareto_ids = tuple(
            candidate_id
            for index, candidate_id in enumerate(eligible_ids)
            if not _is_dominated(values[index], np.delete(values, index, axis=0))
        )
        normalized = _normalize_metric_rows(values)
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

        scenarios = _weight_scenarios(weights)
        weight_scenario_count = len(scenarios)
        index_by_id = {
            candidate_id: index for index, candidate_id in enumerate(eligible_ids)
        }
        scenario_scores = np.stack(
            [normalized @ scenario for scenario in scenarios],
            axis=1,
        )
        scenario_wins = {candidate_id: 0 for candidate_id in eligible_ids}
        for scenario_index in range(len(scenarios)):
            winner = min(
                pareto_ids,
                key=lambda candidate_id: (
                    float(scenario_scores[index_by_id[candidate_id], scenario_index]),
                    candidate_id,
                ),
            )
            scenario_wins[winner] += 1
        weight_win_fractions = {
            candidate_id: count / len(scenarios)
            for candidate_id, count in scenario_wins.items()
        }
        score_ranges = {
            candidate_id: (
                float(np.min(scenario_scores[index_by_id[candidate_id]])),
                float(np.max(scenario_scores[index_by_id[candidate_id]])),
            )
            for candidate_id in eligible_ids
        }
        weight_stability = weight_win_fractions[balanced_id]
        ranked = sorted(
            pareto_ids,
            key=lambda candidate_id: (scores[candidate_id], candidate_id),
        )
        score_margin = (
            1.0
            if len(ranked) == 1
            else max(0.0, scores[ranked[1]] - scores[ranked[0]])
        )
        rank_id = _weighted_rank_winner(
            values,
            np.ones_like(weights) / len(weights),
            eligible_ids,
            pareto_ids,
        )
        metric_names = tuple(metric for metric, _weight in metric_weights)
        bootstrap_win_fractions, bootstrap_iterations = _subject_bootstrap_wins(
            plan_fingerprint=plan.fingerprint,
            stage_id=stage_id,
            eligible_ids=eligible_ids,
            by_id=by_id,
            values=values,
            metric_names=metric_names,
            weights=weights,
        )
        if bootstrap_iterations:
            bootstrap_stability = bootstrap_win_fractions.get(balanced_id, 0.0)

        rank_agrees = rank_id == balanced_id
        subject_stable = bootstrap_stability is None or bootstrap_stability >= 0.70
        if (
            len(eligible_ids) >= 3
            and weight_stability >= 0.75
            and subject_stable
            and rank_agrees
            and score_margin >= 0.05
        ):
            confidence = "robust"
            automatic_selection_allowed = True
        elif (
            len(eligible_ids) >= 2
            and weight_stability >= 0.55
            and (bootstrap_stability is None or bootstrap_stability >= 0.55)
            and rank_agrees
            and score_margin >= 0.02
        ):
            confidence = "sensitive"
        else:
            confidence = "ambiguous"

        if not rank_agrees:
            sensitivity_flags.append(
                "The weighted-value winner differs from the independent weighted-rank winner."
            )
        if weight_stability < 0.75:
            sensitivity_flags.append(
                "The preferred candidate changes under reasonable metric-weight variations."
            )
        if bootstrap_stability is None and stage.kind != "integration_accuracy":
            sensitivity_flags.append(
                "Subject-level residual evidence is absent; cohort-resampling stability "
                "could not be estimated."
            )
        elif bootstrap_stability is not None and bootstrap_stability < 0.70:
            sensitivity_flags.append(
                "The preferred candidate changes when pilot subjects are resampled."
            )
        if score_margin < 0.05:
            sensitivity_flags.append(
                "The two leading candidates have little separation on the base score."
            )
        if len(pareto_ids) > max(2, len(eligible_ids) // 2):
            sensitivity_flags.append(
                "Many candidates remain Pareto-optimal; the evidence contains a broad trade-off."
            )

    search_range_status, search_boundary_parameters = _search_boundary_parameters(
        stage,
        balanced_id,
    )
    if search_range_status == "not_bounded":
        automatic_selection_allowed = False
        rendered_boundaries = []
        for boundary in search_boundary_parameters:
            parameter, direction = boundary.split(":", maxsplit=1)
            direction_text = {
                "minimum": "minimum tested value",
                "maximum": "maximum tested value",
                "only_tested_value": "only tested value",
            }[direction]
            rendered_boundaries.append(
                f"{_SEARCH_PARAMETER_LABELS[parameter]} is the {direction_text}"
            )
        sensitivity_flags.append(
            "Search range not bounded: "
            + "; ".join(rendered_boundaries)
            + ". Test outward logarithmic neighbors before treating this as an "
            "enclosed optimum."
        )

    assessments = tuple(
        CalibrationCandidateAssessment(
            candidate_id=candidate_id,
            eligible=candidate_id in eligible_ids,
            pareto_optimal=candidate_id in pareto_ids,
            balanced_score=scores.get(candidate_id),
            weight_win_fraction=weight_win_fractions.get(candidate_id),
            subject_bootstrap_win_fraction=bootstrap_win_fractions.get(candidate_id),
            score_range=score_ranges.get(candidate_id),
            rejection_reasons=rejection_reasons[candidate_id],
        )
        for candidate_id in candidate_ids
    )
    status = "selection_required" if eligible_ids else "no_eligible_candidate"
    cautions = (
        "Automatic selection is allowed only for a robust recommendation that remains "
        "stable across reasonable weight changes, subject resampling when available, "
        "and an independent rank aggregation.",
        "All Pareto-optimal candidates and raw evidence must remain available to the researcher.",
        "Visual reconstruction review is optional and its performed, passed, failed, or "
        "not-performed status must remain explicit.",
        "A provisional stage recommendation becomes scientifically usable only after "
        "later full-cohort confirmation and researcher review.",
        "A candidate on the minimum or maximum tested attachment, deformation, "
        "control-spacing, or noise value leaves the search range not bounded and "
        "cannot be selected automatically as an enclosed optimum.",
        (
            "Expected biological shape disparity was declared as "
            f"{getattr(plan, 'expected_shape_disparity', 'moderate')}. "
            "Deformation amplitude is therefore "
            "interpreted separately from topology failures, residual underfit, and "
            "anatomical plausibility."
        ),
    )
    payload = {
        "version": _ASSESSMENT_VERSION,
        "plan_fingerprint": plan.fingerprint,
        "stage_id": stage_id,
        "status": status,
        "balanced_candidate_id": balanced_id,
        "recommendation_confidence": confidence,
        "automatic_selection_allowed": automatic_selection_allowed,
        "weight_stability": weight_stability,
        "subject_bootstrap_stability": bootstrap_stability,
        "score_margin": score_margin,
        "independent_rank_candidate_id": rank_id,
        "weight_scenario_count": weight_scenario_count,
        "subject_bootstrap_iterations": bootstrap_iterations,
        "search_range_status": search_range_status,
        "search_boundary_parameters": list(search_boundary_parameters),
        "sensitivity_flags": sensitivity_flags,
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
        recommendation_confidence=confidence,
        automatic_selection_allowed=automatic_selection_allowed,
        weight_stability=weight_stability,
        subject_bootstrap_stability=bootstrap_stability,
        score_margin=score_margin,
        independent_rank_candidate_id=rank_id,
        weight_scenario_count=weight_scenario_count,
        subject_bootstrap_iterations=bootstrap_iterations,
        search_range_status=search_range_status,
        search_boundary_parameters=search_boundary_parameters,
        sensitivity_flags=tuple(sensitivity_flags),
        pareto_candidate_ids=pareto_ids,
        metric_weights=metric_weights,
        candidates=assessments,
        cautions=cautions,
    )

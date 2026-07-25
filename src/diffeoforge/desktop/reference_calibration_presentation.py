"""Beginner-facing presentation helpers for Deformetrica pilot calibration."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from diffeoforge.reference_calibration import CalibrationStage
from diffeoforge.reference_calibration_study import CalibrationStudyCandidateState


@dataclass(frozen=True)
class CalibrationStageGuidance:
    """Plain-language explanation of one staged calibration decision."""

    question: str
    explanation: str
    action: str
    caution: str


_GUIDANCE: dict[str, CalibrationStageGuidance] = {
    "attachment_width": CalibrationStageGuidance(
        question="How much surface detail should matching follow?",
        explanation=(
            "This stage changes the surface-matching kernel width only. A smaller "
            "width follows finer detail, but can also follow mesh texture or noise. "
            "A larger width emphasizes broader shape and is usually smoother."
        ),
        action=(
            "Open every option, select the same pilot specimen, and compare its blue "
            "original outline with the orange reconstruction. Choose the largest "
            "width that still preserves the smallest anatomical feature relevant to "
            "your study."
        ),
        caution=(
            "The closest numerical fit is not automatically the best biological fit. "
            "A very close fit can be overfitting."
        ),
    ),
    "deformation_width": CalibrationStageGuidance(
        question="How local or smooth may the deformation be?",
        explanation=(
            "This stage changes deformation width and initial control-point spacing "
            "together. Smaller values allow more local, flexible changes. Larger "
            "values favor broader, smoother changes."
        ),
        action=(
            "Compare the same anatomical regions in every option. Prefer the smoothest "
            "deformation that still reconstructs the biological differences you need."
        ),
        caution=(
            "A more flexible model can reduce mismatch by creating implausible local "
            "warping. Visual anatomy remains the deciding evidence."
        ),
    ),
    "noise_weight": CalibrationStageGuidance(
        question="How strongly should close fit compete with smooth deformation?",
        explanation=(
            "This stage changes the noise standard deviation. Smaller values push "
            "harder toward the observed surfaces. Larger values allow more mismatch "
            "in exchange for smoother, less costly deformation."
        ),
        action=(
            "Look for the point where a closer reconstruction stops providing a useful "
            "anatomical improvement and starts adding distortion or irregular warping."
        ),
        caution=(
            "This is a fit-versus-regularity trade-off, not a measurement of specimen "
            "noise and not a parameter DiffeoForge can choose biologically for you."
        ),
    ),
    "integration_accuracy": CalibrationStageGuidance(
        question="How finely must the deformation path be calculated?",
        explanation=(
            "This stage changes only the number of numerical time points. More time "
            "points can improve numerical accuracy but require more computation."
        ),
        action=(
            "Choose the smallest time-point count whose atlas and reconstructions are "
            "visually indistinguishable from the next finer option."
        ),
        caution=(
            "This stage checks numerical stability. It should not be used to improve "
            "anatomical registration by changing scientific model flexibility."
        ),
    ),
}


def stage_guidance(stage: CalibrationStage) -> CalibrationStageGuidance:
    """Return the stable beginner-facing guidance for ``stage``."""

    try:
        return _GUIDANCE[stage.kind]
    except KeyError as error:
        raise ValueError(f"Unsupported calibration stage kind: {stage.kind!r}") from error


def candidate_parameter_summary(
    stage: CalibrationStage,
    values: Mapping[str, float],
    *,
    coordinate_unit: str,
) -> tuple[str, str]:
    """Return a prominent parameter value and its direction-of-change meaning."""

    unit = coordinate_unit.strip() or "coordinate units"
    if stage.kind == "attachment_width":
        value = float(values["attachment_kernel_width"])
        return (
            f"Surface-detail width: {value:.6g} {unit}",
            "Smaller follows finer detail; larger emphasizes broader shape.",
        )
    if stage.kind == "deformation_width":
        width = float(values["deformation_kernel_width"])
        spacing = float(values["initial_control_point_spacing"])
        return (
            f"Deformation width and control spacing: {width:.6g} / {spacing:.6g} {unit}",
            "Smaller is more local and flexible; larger is smoother and more global.",
        )
    if stage.kind == "noise_weight":
        value = float(values["noise_std"])
        return (
            f"Fit-versus-smoothness setting: {value:.6g} {unit}",
            "Smaller pushes for closer fit; larger favors smoother deformation.",
        )
    if stage.kind == "integration_accuracy":
        value = int(round(float(values["timepoints"])))
        return (
            f"Numerical time points: {value}",
            "More points increase numerical resolution and usually runtime.",
        )
    raise ValueError(f"Unsupported calibration stage kind: {stage.kind!r}")


def candidate_tradeoff_labels(
    candidates: Sequence[CalibrationStudyCandidateState],
) -> dict[str, tuple[str, ...]]:
    """Describe relative automatic observations without choosing a candidate."""

    complete = tuple(candidate for candidate in candidates if candidate.metrics is not None)
    labels: dict[str, list[str]] = {candidate.candidate_id: [] for candidate in candidates}
    if not complete:
        return {candidate_id: tuple(items) for candidate_id, items in labels.items()}

    comparisons = (
        ("residual_p95", "Closest automatic surface match", "Largest measured mismatch"),
        ("distortion_p95", "Least atlas area change", "Most atlas area change"),
        ("deformation_energy", "Lowest deformation cost", "Highest deformation cost"),
        ("runtime_seconds", "Fastest pilot run", "Slowest pilot run"),
    )
    for key, minimum_label, maximum_label in comparisons:
        values = {
            candidate.candidate_id: float(candidate.metrics[key])
            for candidate in complete
            if key in candidate.metrics
            and math.isfinite(float(candidate.metrics[key]))
        }
        if len(values) < 2:
            continue
        minimum = min(values.values())
        maximum = max(values.values())
        for candidate_id, value in values.items():
            if math.isclose(value, minimum, rel_tol=1e-12, abs_tol=1e-15):
                labels[candidate_id].append(minimum_label)
            if (
                not math.isclose(maximum, minimum, rel_tol=1e-12, abs_tol=1e-15)
                and math.isclose(value, maximum, rel_tol=1e-12, abs_tol=1e-15)
            ):
                labels[candidate_id].append(maximum_label)
    return {candidate_id: tuple(items) for candidate_id, items in labels.items()}


def automatic_check_summary(metrics: Mapping[str, object]) -> tuple[bool, str]:
    """Summarize machine-checkable failure evidence in one readable sentence."""

    converged = bool(metrics.get("converged", False))
    invalid_faces = int(metrics.get("invalid_face_count", 0))
    if converged and invalid_faces == 0:
        return (
            True,
            "Automatic checks passed: the optimizer stopped normally and no invalid "
            "faces were detected.",
        )
    problems: list[str] = []
    if not converged:
        problems.append("the optimizer did not report its normal tolerance stop")
    if invalid_faces:
        problems.append(f"{invalid_faces} invalid faces were detected")
    return False, "Automatic warning: " + "; ".join(problems) + "."


def technical_metric_text(metrics: Mapping[str, object]) -> str:
    """Render verified technical measurements behind progressive disclosure."""

    return (
        "Surface-distance QC, 95th percentile: "
        f"{float(metrics['residual_p95']):.6g}\n"
        "Surface-distance QC, median: "
        f"{float(metrics['residual_median']):.6g}\n"
        "Atlas area-change QC, 95th percentile: "
        f"{float(metrics['distortion_p95']):.6g}\n"
        "Final regularity-term magnitude: "
        f"{float(metrics['deformation_energy']):.6g}\n"
        "Resampling sensitivity: "
        f"{float(metrics['resampling_sensitivity']):.6g}\n"
        f"Runtime: {float(metrics['runtime_seconds']):.1f} seconds\n"
        f"Final logged iteration: {metrics.get('final_iteration', 'not reported')} "
        f"of {metrics.get('maximum_iterations', 'not reported')}\n"
        f"Invalid faces: {int(metrics.get('invalid_face_count', 0))}\n\n"
        "Interpretation limits\n"
        "• Surface distance is a geometric QC proxy, not Deformetrica's configured "
        "attachment objective.\n"
        "• The regularity value is an optimizer comparison proxy, not physical energy.\n"
        "• Lower values do not prove anatomically correct registration."
    )

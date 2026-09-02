"""Beginner-facing presentation helpers for Deformetrica pilot calibration."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from diffeoforge.reference_calibration import CalibrationStage
from diffeoforge.reference_calibration_study import CalibrationStudyCandidateState


@dataclass(frozen=True)
class CalibrationStageGuidance:
    """Plain-language explanation of one staged calibration decision."""

    question: str
    explanation: str
    action: str
    caution: str


@dataclass(frozen=True)
class CalibrationTradeoffAssessment:
    """One relative pilot observation with cautious beginner-facing meaning."""

    label: str
    tone: Literal["favorable", "caution", "unfavorable"]
    interpretation: str


_GUIDANCE: dict[str, CalibrationStageGuidance] = {
    "attachment_width": CalibrationStageGuidance(
        question="Which matching-detail and deformation-scale combination is defensible?",
        explanation=(
            "This first screen changes surface-matching width and deformation width "
            "together. That exposes interactions which a one-parameter-at-a-time "
            "screen can miss. Finer matching can follow anatomy or mesh texture; more "
            "local deformation can represent real variation or implausible warping."
        ),
        action=(
            "Let DiffeoForge complete the combined grid. An automatic choice is allowed "
            "only when one Pareto candidate remains stable across metric priorities, "
            "subject resampling, and an independent rank analysis. Otherwise review "
            "the alternatives or collect more evidence."
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
            "Use the explained trade-offs to prefer the smoothest deformation that "
            "still represents the biological differences you need. Optional visual QC "
            "can compare the same anatomical regions when the evidence is ambiguous."
        ),
        caution=(
            "A more flexible model can reduce mismatch by creating implausible local "
            "warping. A visual reconstruction check can add evidence but is not required "
            "to continue."
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
            "Compare closer fit against deformation cost and distortion. Choose the "
            "balance appropriate to your study; optionally inspect reconstructions if "
            "the automatic signals do not make the trade-off clear."
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
            "numerically stable relative to the next finer option. Optional visual QC "
            "can be used when the numerical differences need anatomical context."
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
        attachment = float(values["attachment_kernel_width"])
        if "deformation_kernel_width" not in values:
            return (
                f"Surface-detail width: {attachment:.6g} {unit}",
                "Smaller follows finer detail; larger emphasizes broader shape.",
            )
        deformation = float(values["deformation_kernel_width"])
        return (
            "Surface-detail / deformation width: "
            f"{attachment:.6g} / {deformation:.6g} {unit}",
            "The first value controls matching detail; the second controls how far "
            "correlated deformation spreads.",
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


def candidate_tradeoff_assessments(
    candidates: Sequence[CalibrationStudyCandidateState],
) -> dict[str, tuple[CalibrationTradeoffAssessment, ...]]:
    """Explain relative automatic observations without choosing a candidate."""

    complete = tuple(candidate for candidate in candidates if candidate.metrics is not None)
    assessments: dict[str, list[CalibrationTradeoffAssessment]] = {
        candidate.candidate_id: [] for candidate in candidates
    }
    if not complete:
        return {
            candidate_id: tuple(items)
            for candidate_id, items in assessments.items()
        }

    comparisons = (
        (
            "residual_p95",
            CalibrationTradeoffAssessment(
                label="Closest automatic surface match",
                tone="favorable",
                interpretation=(
                    "This option has the lowest measured surface mismatch. That is "
                    "promising for fit, but an extremely close match can still follow "
                    "mesh noise or overfit anatomy."
                ),
            ),
            CalibrationTradeoffAssessment(
                label="Largest measured mismatch",
                tone="unfavorable",
                interpretation=(
                    "This option leaves the most measured surface mismatch. It may "
                    "underfit relevant anatomy unless the remaining differences are "
                    "biologically unimportant."
                ),
            ),
        ),
        (
            "distortion_p95",
            CalibrationTradeoffAssessment(
                label="Least atlas/reconstruction area change",
                tone="favorable",
                interpretation=(
                    "This option changes local surface area the least, which is a "
                    "favorable stability signal and reduces concern about stretching "
                    "or collapse."
                ),
            ),
            CalibrationTradeoffAssessment(
                label="Most atlas/reconstruction area change",
                tone="unfavorable",
                interpretation=(
                    "This option changes local surface area the most, which raises concern "
                    "about stretching, compression, or collapse. The optional viewer can "
                    "show where those changes occur."
                ),
            ),
        ),
        (
            "deformation_energy",
            CalibrationTradeoffAssessment(
                label="Lowest deformation cost",
                tone="favorable",
                interpretation=(
                    "This option reaches its result with the least deformation cost, "
                    "suggesting a smoother or easier transformation. It can still "
                    "underfit local anatomy."
                ),
            ),
            CalibrationTradeoffAssessment(
                label="Highest deformation cost",
                tone="caution",
                interpretation=(
                    "This option needs the strongest deformation. That may capture real "
                    "local variation or indicate excessive flexibility. Your biological "
                    "question determines whether that trade-off is acceptable; visual QC "
                    "is available if needed."
                ),
            ),
        ),
        (
            "runtime_seconds",
            CalibrationTradeoffAssessment(
                label="Fastest pilot run",
                tone="favorable",
                interpretation=(
                    "This option used the least computation time. That is favorable for "
                    "efficiency, but speed does not establish registration quality."
                ),
            ),
            CalibrationTradeoffAssessment(
                label="Slowest pilot run",
                tone="unfavorable",
                interpretation=(
                    "This option used the most computation time. That is unfavorable "
                    "for efficiency only and does not make its anatomy worse."
                ),
            ),
        ),
    )
    for key, minimum_assessment, maximum_assessment in comparisons:
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
                assessments[candidate_id].append(minimum_assessment)
            if (
                not math.isclose(maximum, minimum, rel_tol=1e-12, abs_tol=1e-15)
                and math.isclose(value, maximum, rel_tol=1e-12, abs_tol=1e-15)
            ):
                assessments[candidate_id].append(maximum_assessment)
    return {
        candidate_id: tuple(items)
        for candidate_id, items in assessments.items()
    }


def candidate_tradeoff_labels(
    candidates: Sequence[CalibrationStudyCandidateState],
) -> dict[str, tuple[str, ...]]:
    """Retain the stable plain-label projection for reports and callers."""

    return {
        candidate_id: tuple(assessment.label for assessment in assessments)
        for candidate_id, assessments in candidate_tradeoff_assessments(
            candidates
        ).items()
    }


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
        "Atlas/reconstruction area-change QC, 95th percentile: "
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

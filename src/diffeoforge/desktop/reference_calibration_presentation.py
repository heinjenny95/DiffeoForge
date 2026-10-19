"""Beginner-facing presentation helpers for Deformetrica pilot calibration."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from diffeoforge.reference_calibration import CalibrationStage
from diffeoforge.reference_calibration_study import (
    CalibrationStudyCandidateState,
    ReferenceCalibrationStudySnapshot,
)


def candidate_option_label(index: int) -> str:
    """Keep option labels stable when a refinement grows beyond 26 candidates."""
    if type(index) is not int or index < 1:
        raise ValueError("Option indices start at one")
    label = ""
    while index:
        index, digit = divmod(index - 1, 26)
        label = chr(ord("A") + digit) + label
    return label


def afk_return_summary(report: Mapping[str, object]) -> str | None:
    """Expose recorded overnight limitations without re-ranking or approving anything."""
    stages = report.get("stage_decisions", [])
    automatic = [
        stage for stage in stages if stage.get("selection_mode") == "automatic_provisional_afk_v1"
    ]
    if not automatic:
        return None
    lines = [f"AFK return summary: {len(automatic)} stages selected provisionally."]
    for stage in stages:
        concerns = []
        confidence = stage.get("recommendation_confidence", "not_assessed")
        if confidence != "robust":
            concerns.append(f"confidence: {confidence}")
        search = stage.get("search_range_status", "not_evaluated")
        if search == "not_bounded":
            concerns.append("best tested value at search boundary")
        elif search == "not_evaluated":
            concerns.append("search boundary not assessed")
        if stage.get("sensitivity_flags"):
            concerns.append("sensitivity warnings")
        if concerns:
            lines.append(
                f"{stage.get('title', stage.get('stage_id', 'Stage'))}: "
                + "; ".join(concerns)
                + "."
            )
    lines.append(
        "Next: review these choices and their evidence. No visual approval was created; "
        "the atlas has not been started."
    )
    return "\n".join(lines)


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
    tone: Literal["favorable", "caution", "unfavorable", "neutral"]
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
            "Compare every specimen's fit. The largest size-normalized mismatch leads "
            "the shortlist; speed cannot compensate for poor fit. Inspect and approve "
            "every specimen, or refine an option within this stage."
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
            "Inspect every specimen and preserve the anatomy needed for this study. "
            "Deformation cost is context, not an anatomical quality score."
        ),
        caution=(
            "A more flexible model can reduce mismatch by creating implausible local "
            "warping. Every specimen must pass visual reconstruction review to continue."
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
            "Prioritize surface fit, then inspect for missing anatomy and implausible "
            "deformation. One failed or uncertain specimen blocks approval."
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
            "numerically stable relative to the next finer option. The selected option "
            "also requires visual acceptance of every specimen."
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


def stage_options_rejected(snapshot: ReferenceCalibrationStudySnapshot) -> bool:
    """Recognize explicit rejection of every new option, excluding the saved baseline.

    Technical failures, unfinished fits and unreviewed results are not anatomical
    decisions. A kept early screen still requires its own joint-fit review.
    """
    stage = snapshot.current_stage
    if stage is None or stage.order not in (2, 3):
        return False
    options = [c for c in snapshot.candidates if c.candidate_id != stage.stage_id + "-retained"]
    return bool(options) and all(
        c.status == "screened_out"
        or (c.status == "completed" and snapshot.visual_reviews.get(c.candidate_id) is False)
        for c in options
    )


@dataclass(frozen=True)
class PilotNextStep:
    action: str
    label: str
    message: str
    warning: bool = False


def final_stage_next_step(
    *, selected: bool, approved: bool, reasons: Sequence[str], provisional: bool = False,
    pending: bool = False, eligible: bool = False, timepoints: int | None = None,
    finer_evaluation: int | None = None,
    fixed_state: bool = False,
) -> PilotNextStep:
    """Explain verified assessment results; this never changes an eligibility gate."""
    if pending:
        return PilotNextStep("check", "Resume saved check", "An earlier check is unfinished. "
                             "Resume it with its original settings.", True)
    if not selected:
        return PilotNextStep("choose", "Choose a saved fit", "Choose the saved fit to check.")
    if any(r.startswith(("Geometry", "A complete, valid", "roundtrip check")) for r in reasons):
        return PilotNextStep("details", "Inspect check details…", "The saved fit could not be "
                             "verified. Inspect the check details before continuing.", True)
    if not approved:
        return PilotNextStep("review", "Review saved fit…", "Inspect the saved joint fit and "
                             "record your decision before finishing.")
    if any(r.startswith("integration check differs") for r in reasons):
        if finer_evaluation is not None:
            return PilotNextStep(
                "adopt", f"Use {finer_evaluation} time steps (no refit)",
                "The finer evaluation already passed its first comparison. Check only the "
                "missing grid, then review these reconstructions. No optimizer is started.", True,
            )
        finer = 2 * timepoints - 1 if type(timepoints) is int and timepoints >= 2 else None
        return PilotNextStep(
            "finer",
            f"Recalculate with {finer} time steps…" if finer
            else "Recalculate fit with more time steps…",
            "A good-looking reconstruction can still change with finer time steps. "
            "Recalculate, then review and check again.", True,
        )
    if any(r.startswith("Check time resolution") for r in reasons):
        return PilotNextStep("check", "Check time resolution", "Shape approved. Check its "
                             "time resolution next; the saved fit is not re-optimized.")
    if provisional:
        if fixed_state:
            return PilotNextStep(
                "finish", "Finish pilot provisionally → atlas setup", "Shape approved. Time "
                "resolution passed. Provisional means optimizer convergence is unconfirmed: "
                "this saved field was evaluated at finer time steps without a new fit. "
                "You can continue to the full atlas with that warning recorded.", True,
            )
        return PilotNextStep("finish", "Finish pilot provisionally → atlas setup", "Shape "
                             "approved. Time resolution passed. Provisional means the optimizer "
                             "reached its iteration limit before confirmed convergence. You can "
                             "continue to the full atlas with that warning recorded.", True)
    if eligible:
        return PilotNextStep("finish", "Finish pilot → atlas setup", "Shape and time "
                             "resolution checked. Finish the pilot to prepare the full atlas.")
    return PilotNextStep("details", "Inspect check details…", "This fit is not ready to finish. "
                         "Inspect the remaining check details.", True)


def final_stage_check_summary(
    *, approved: bool | None, reasons: Sequence[str], metrics: Mapping[str, object],
    timepoints: int | None = None, eligible: bool = False, provisional: bool = False,
) -> str:
    """Keep the three independent checks visible, using the existing assessment only."""
    anatomy = (
        "approved" if approved is True else "rejected" if approved is False else "review needed"
    )
    if any(r.startswith(("Geometry", "A complete, valid", "roundtrip check")) for r in reasons):
        resolution = "could not verify the saved fit"
    elif any(r.startswith("integration check differs") for r in reasons):
        resolution = "needs more time steps"
        if type(timepoints) is int and timepoints >= 2:
            resolution += f" ({timepoints} → {2 * timepoints - 1})"
    elif any(r.startswith("Check time resolution") for r in reasons):
        resolution = "not checked yet"
    elif eligible or provisional or (reasons and all(r.startswith((
        "Optimizer convergence is not established", "Iteration limit reached:",
        "Finer evaluation without refit:",
        "Anatomical review", "Review the saved joint fit",
    )) for r in reasons)):
        resolution = "passed"
    else:
        resolution = "check needed"
    if metrics.get("metric_version") == "fixed-state-resolution-adoption-v1":
        source = metrics.get("source_optimizer") or {}
        count = source.get("maximum_iterations")
        limit = f" ({count} iterations)" if type(count) is int and count > 0 else ""
        optimization = (
            f"source fit reached its limit{limit}; convergence unconfirmed; no new fit at this grid"
            if source.get("optimizer_stop_signal") == "maximum_iterations"
            else "convergence at this grid unconfirmed; saved field evaluated without a new fit"
        )
    elif metrics.get("converged") is True:
        optimization = "convergence confirmed"
    elif metrics.get("optimizer_stop_signal") == "maximum_iterations":
        count = metrics.get("maximum_iterations")
        budget = f" ({count} iterations)" if type(count) is int and count > 0 else ""
        optimization = f"limit reached{budget}; convergence unconfirmed"
    else:
        optimization = "convergence unconfirmed"
    return f"Shape review: {anatomy}\nTime resolution: {resolution}\nOptimization: {optimization}"


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
            f"Surface-detail / deformation width: {attachment:.6g} / {deformation:.6g} {unit}",
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

    complete = tuple(candidate for candidate in candidates if candidate.metrics is not None
                     and candidate.metrics.get("metric_version")
                     != "fixed-state-resolution-adoption-v1")
    assessments: dict[str, list[CalibrationTradeoffAssessment]] = {
        candidate.candidate_id: [] for candidate in candidates
    }
    if not complete:
        return {candidate_id: tuple(items) for candidate_id, items in assessments.items()}

    comparisons = (
        (
            "residual_p95",
            CalibrationTradeoffAssessment(
                label="Lowest measured distance",
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
                tone="neutral",
                interpretation=(
                    "Least measured area change is not anatomical approval. Similar shapes "
                    "may need little change; disparate shapes may require substantial "
                    "change. Check preserved features and local mesh validity."
                ),
            ),
            CalibrationTradeoffAssessment(
                label="Most atlas/reconstruction area change",
                tone="neutral",
                interpretation=(
                    "More area change may represent real shape differences or implausible "
                    "warping. Its magnitude alone cannot distinguish them. Inspect the "
                    "originals and reconstructions in the same regions."
                ),
            ),
        ),
        (
            "deformation_energy",
            CalibrationTradeoffAssessment(
                label="Lowest deformation cost",
                tone="neutral",
                interpretation=(
                    "Lower cost is not automatically better. It may suit similar shapes, "
                    "but low cost with missing tips or branches can indicate underfitting. "
                    "Compare economy only after the needed anatomy is represented."
                ),
            ),
            CalibrationTradeoffAssessment(
                label="Highest deformation cost",
                tone="neutral",
                interpretation=(
                    "Higher cost is not automatically worse. Complex, disparate shapes may "
                    "need substantial deformation to preserve their anatomy. High cost "
                    "alone proves neither a good fit nor an invalid deformation."
                ),
            ),
        ),
        (
            "runtime_seconds",
            CalibrationTradeoffAssessment(
                label="Fastest pilot run",
                tone="neutral",
                interpretation=(
                    "This option used the least computation time. That is favorable for "
                    "efficiency, but speed does not establish registration quality."
                ),
            ),
            CalibrationTradeoffAssessment(
                label="Slowest pilot run",
                tone="neutral",
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
            if key in candidate.metrics and math.isfinite(float(candidate.metrics[key]))
        }
        if len(values) < 2:
            continue
        minimum = min(values.values())
        maximum = max(values.values())
        for candidate_id, value in values.items():
            if math.isclose(value, minimum, rel_tol=1e-12, abs_tol=1e-15):
                assessments[candidate_id].append(minimum_assessment)
            if not math.isclose(maximum, minimum, rel_tol=1e-12, abs_tol=1e-15) and math.isclose(
                value, maximum, rel_tol=1e-12, abs_tol=1e-15
            ):
                assessments[candidate_id].append(maximum_assessment)
    return {candidate_id: tuple(items) for candidate_id, items in assessments.items()}


def candidate_tradeoff_labels(
    candidates: Sequence[CalibrationStudyCandidateState],
) -> dict[str, tuple[str, ...]]:
    """Retain the stable plain-label projection for reports and callers."""

    return {
        candidate_id: tuple(assessment.label for assessment in assessments)
        for candidate_id, assessments in candidate_tradeoff_assessments(candidates).items()
    }


def automatic_check_summary(metrics: Mapping[str, object]) -> tuple[bool, str]:
    """Summarize machine-checkable failure evidence in one readable sentence."""

    converged = bool(metrics.get("converged", False))
    invalid_faces = int(metrics.get("invalid_face_count", 0))
    if metrics.get("metric_version") == "fixed-state-resolution-adoption-v1":
        return False, ("Saved field evaluated without re-optimization. Fresh shape review "
                       "and an explicit provisional decision are required.")
    if converged and invalid_faces == 0:
        return (
            True,
            "Objective-change tolerance reached; no invalid faces detected. "
            "Fit needs visual review.",
        )
    if metrics.get("optimizer_stop_signal") == "maximum_iterations" and not invalid_faces:
        return False, (
            f"Iteration limit reached ({metrics.get('maximum_iterations', '?')}). "
            "Fit can be reviewed; continue this option to check convergence."
        )
    problems: list[str] = []
    if not converged:
        problems.append("the optimizer did not report its normal tolerance stop")
    if invalid_faces:
        problems.append(f"{invalid_faces} invalid faces were detected")
    return False, "Automatic warning: " + "; ".join(problems) + "."


def technical_metric_text(metrics: Mapping[str, object]) -> str:
    """Render verified technical measurements behind progressive disclosure."""

    if metrics.get("metric_version") == "fixed-state-resolution-adoption-v1":
        source = metrics["source_optimizer"]
        return (
            "Fixed-state evaluation; no optimizer ran at the selected time grid.\n"
            f"Source optimizer stop: {source['optimizer_stop_signal']}\n"
            f"Source optimizer iteration: {source['final_iteration']} "
            f"of {source['maximum_iterations']}\n"
            "Invalid faces in evaluated template/reconstructions: "
            f"{metrics['invalid_face_count']}\n"
            "Original likelihood and surface-distance metrics are not claimed at the new grid.\n"
            "This remains a provisional pilot; a new full-cohort atlas must confirm its fit."
        )
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
        + subject_metric_text(metrics)
        + "\n\n"
        "Interpretation limits\n"
        "• Surface distance is a geometric QC proxy, not Deformetrica's configured "
        "attachment objective.\n"
        "• The regularity value is an optimizer comparison proxy, not physical energy.\n"
        "• Lower values do not prove anatomically correct registration."
    )


def subject_metric_text(metrics: Mapping[str, object]) -> str:
    """Expose the subject tails hidden by the pooled proxy, without grading anatomy."""
    if metrics.get("original_surface_fit"):
        scope = (
            "Full target detail" if metrics.get("fit_scope") == "full_targets" else "Screen only"
        )
        return (
            scope
            + " — area-sampled distance to original triangles (coordinate units)\n"
            + "\n".join(
                f"{name}: p95 {value['p95']:.6g}; p99 {value['p99']:.6g}"
                for name, value in sorted(metrics["original_surface_fit"].items())
            )
            + "\nSampled geometry cannot approve anatomy."
        )
    values = metrics.get("subject_residual_p95", {})
    if not isinstance(values, Mapping) or not values:
        return "Per-specimen surface-distance evidence is unavailable in this result."
    ordered = sorted(
        ((str(name), float(value)) for name, value in values.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return (
        "Per-specimen nearest-vertex p95 (largest first; coordinate units)\n"
        + "\n".join(f"{name}: {value:.6g}" for name, value in ordered)
        + "\nPooled p95 can hide a poor specimen or a small missing feature. "
        "These distances do not test homology, tips or branches; inspect those "
        "regions against original-detail geometry."
    )

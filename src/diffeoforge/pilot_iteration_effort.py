"""New pilot trial headroom; numerical stopping and visual approval stay separate."""

import math

VERSION = "regional-trial-headroom-v1"

_CHECKPOINT = dict(version="regional-review-checkpoint-v1", first_iterations=120,
                   total_iterations=600)
_MIN_SCREEN_FORECAST_SECONDS = 20 * 60
_MIN_LOCAL_GAIN = .02


def legacy_checkpoint(recipe, allowance, candidate):
    """Stage the first expensive correction from an existing ordinary fit."""
    if (candidate is None or recipe.get("phase") != "initial_warm"
            or recipe.get("residual") is not False or recipe.get("guide_noise") is not None
            or allowance != _CHECKPOINT["total_iterations"]):
        return None
    metrics = candidate.metrics or {}
    seconds = metrics.get("runtime_seconds")
    updates = metrics.get("final_iteration")
    if (type(updates) is not int or updates < 1
            or type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0
            or seconds / updates * allowance < _MIN_SCREEN_FORECAST_SECONDS):
        return None
    from diffeoforge.config import load_config

    if load_config(candidate.config_path)["optimization"]["method"] != "gradient_ascent":
        return None
    return dict(_CHECKPOINT)


def review_checkpoint(recipe):
    checkpoint = (recipe or {}).get("review_checkpoint")
    if checkpoint is not None and checkpoint != _CHECKPOINT:
        raise ValueError("Invalid protected-fit review allowance")
    return checkpoint


def checkpoint_remainder(info, metrics, subject):
    """Bound the one exact-objective successor using complete saved regional checks."""
    strategy = info.get("strategy") or {}
    checkpoint = review_checkpoint(strategy.get("regional_recipe"))
    if (checkpoint is None or strategy.get("optimization")
            or metrics.get("maximum_iterations") != checkpoint["first_iterations"]
            or metrics.get("final_iteration") != checkpoint["first_iterations"]):
        return 0
    from diffeoforge.pilot_adaptive_fit import HARD_QUALITY_FLAGS
    from diffeoforge.pilot_adaptive_native import _red_errors

    feedback = info.get("feedback") or {}
    marks = feedback.get("regions") or []
    quality = subject.get("regional_quality") or {}
    marked = subject.get("marked_regions") or {}
    if (quality.get("marked_regions") != marks
            or any(quality.get(key) is not True for key in HARD_QUALITY_FLAGS)
            or marked.get("outcome") == "regression"
            or (subject.get("refinement_guard") or {}).get("severe") is True):
        return 0
    red = {str(i): row for i, row in enumerate(marks)
           if row.get("purpose", "problem") == "problem"}
    if not red:
        return 0
    try:
        before = _red_errors(feedback.get("baseline") or [], red)
        after = _red_errors(marked.get("measurements") or [], red)
    except (KeyError, TypeError, ValueError):
        return 0
    if any(after[key] >= before[key] * (1 - _MIN_LOCAL_GAIN) for key in red):
        return 0
    return checkpoint["total_iterations"] - checkpoint["first_iterations"]


def regional_allowance(recipe, regions, inherited=120):
    """Leave screening cheap; a serious local trial is not limited by its screen.

    This is an initial allowance, not a claim that a certain number suffices.
    Native tolerance/line-search/numerical guards still stop earlier. More local
    areas or a measured miss requiring broad capture receive extra headroom.
    Face count and anatomical feature names are deliberately not used.
    """
    if type(inherited) is not int or inherited < 1:
        raise ValueError("A positive existing iteration allowance is required")
    if not isinstance(recipe, dict):
        raise ValueError("A verified regional recipe is required")
    problem = [r for r in regions if r.get("purpose", "problem") == "problem"]
    if not problem:
        problem = [r for r in regions if r.get("purpose") == "preserve"]
    width = recipe.get("focus_width")
    if type(width) not in {int, float} or not math.isfinite(width) or width <= 0:
        raise ValueError("A finite positive local detail scale is required")
    capture = recipe.get("capture_evidence") or {}
    tail = capture.get("original_to_fit_p95")
    if tail is not None and (
        type(tail) not in {int, float} or not math.isfinite(tail) or tail < 0
    ):
        raise ValueError("Measured capture distance must be finite and nonnegative")
    reasons = ["serious_local_trial"]
    if len(problem) > 1:
        reasons.append("several_marked_areas")
    if tail is not None and tail >= 1.5 * width:
        reasons.append("measured_broad_capture")
    if recipe.get("residual") is True:
        reasons.append("new_residual_field")
    allowance = max(inherited, 600 if len(reasons) > 1 else 400)
    checkpoint = review_checkpoint(recipe)
    if checkpoint:
        if allowance != checkpoint["total_iterations"]:
            raise ValueError("The checked correction's original allowance changed")
        allowance = checkpoint["first_iterations"]
        reasons.append("review_large_legacy_trials_early")
    return dict(version=VERSION, maximum_iterations=allowance, inherited_iterations=inherited,
                reasons=reasons, anatomical_approval=False, convergence_claim=False,
                cumulative_iteration_limit=checkpoint["total_iterations"] if checkpoint else None)

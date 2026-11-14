"""New pilot trial headroom; numerical stopping and visual approval stay separate."""

import math

VERSION = "regional-trial-headroom-v1"


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
    return dict(version=VERSION, maximum_iterations=allowance, inherited_iterations=inherited,
                reasons=reasons, anatomical_approval=False, convergence_claim=False,
                cumulative_iteration_limit=None)

"""A reviewed long local pass can need finer movement rather than more steps."""

import math


def _region_key(region):
    return tuple(
        (key, repr(region.get(key, "problem" if key == "purpose" else None)))
        for key in (
            "version",
            "source_sha256",
            "shape",
            "bounds",
            "center",
            "radius",
            "purpose",
            "symptom",
        )
    )


def response(data, info, numerical, symptom):
    """Select a new hypothesis only after the existing continuation trust gate.

    This is a test recommendation, never acceptance or proof of insufficient
    capacity. Explicit longer optimization remains available separately.
    Per-area tails prevent an improved large patch from hiding a smaller miss.
    """
    if not numerical or not numerical.get("regional_continuation"):
        return None
    if symptom is None:
        symptom = next(
            (r["symptom"] for r in data["regions"] if r.get("symptom") in {"detail", "missing"}),
            "unsure",
        )
    if symptom not in {"detail", "missing"}:
        return None
    if any(
        r.get("purpose", "problem") == "problem"
        and r.get("symptom") not in {"detail", "missing", "shape", "unsure"}
        for r in data["regions"]
    ):
        return None
    current = data["current"]
    cap = (current.metrics or {}).get("maximum_iterations")
    if type(cap) is not int or cap < 400:
        return None
    feedback = (data["context"].get("feedback", {}).get(current.candidate_id) or {}).get(
        "feedback"
    ) or {}
    if feedback.get("outcome") not in {"better", "same"}:
        return None
    recipe = (info.get("strategy") or {}).get("regional_recipe") or {}
    width = recipe.get("focus_width")
    reference = data.get("current_reference")
    if not reference or type(width) not in {int, float} or not math.isfinite(width) or width <= 0:
        return None
    row = (
        (current.metrics or {})
        .get("attachment_comparison", {})
        .get("subjects", {})
        .get(reference["target"], {})
    )
    quality = row.get("regional_quality") or {}
    safe = (
        "numerical_selection_suitable",
        "local_improved",
        "outside_preserved",
        "shape_preserved",
        "transition_preserved",
        "no_new_intersection_flags",
        "spatial_resolution_sufficient",
        "temporal_grid_stable",
    )
    if quality.get("marked_regions") != data["regions"] or any(
        quality.get(key) is not True for key in safe
    ):
        return None
    measurements = (row.get("marked_regions") or {}).get("measurements", [])
    tails = []
    for index, region in enumerate(data["regions"]):
        if region.get("purpose", "problem") != "problem":
            continue
        matching = [
            r for r in measurements if _region_key(r.get("region", {})) == _region_key(region)
        ]
        if (
            len(matching) != 1
            or type(matching[0].get("selected_faces")) is not int
            or matching[0]["selected_faces"] < 1
        ):
            return None
        repeats = matching[0].get("repeats") or []
        values = [r.get("original_to_fit_p95") for r in repeats]
        if len(values) < 2 or any(
            type(v) not in {int, float} or not math.isfinite(v) or v < 0 for v in values
        ):
            return None
        tails.append(dict(region_index=index, original_to_fit_p95=max(values)))
    if not tails or not any(r["original_to_fit_p95"] > 0 for r in tails):
        return None
    worst = max(r["original_to_fit_p95"] for r in tails)
    # Keep capture broad while an original patch remains out of reach. Once it
    # is reached, a smaller surface scale can test the remaining detail.
    next_width = max(width, worst * 0.5) if worst >= width else max(width * 0.7, worst * 0.5)
    movement = reference["values"]["deformation_kernel_width"]
    next_movement = max(movement * 0.5, next_width * 2)
    if not math.isfinite(next_movement) or next_movement >= movement * 0.9:
        return None
    return dict(
        version="reviewed-local-resolution-v1",
        tested_iterations=cap,
        per_region_remaining=tails,
        worst_original_to_fit_p95=worst,
        before_focus_width=width,
        next_focus_width=next_width,
        before_movement_width=movement,
        next_movement_width=next_movement,
        current_broad_field_retained=True,
        anatomical_approval=False,
    )

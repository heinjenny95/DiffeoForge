"""Prospective, bounded control grids for high-disparity ordinary pilot trials.

The spacing follows the declared deformation kernel, as in the native engine's
default initialization. It is a model-capacity candidate, never a fit guarantee.
Historical records without this explicit version retain their original grids.
"""

import math

import numpy as np

VERSION = "kernel-spaced-pilot-controls-v1"
MAX_CONTROLS = 2000


def describe(bounds, width):
    bounds = np.asarray(bounds, dtype=float)
    if (bounds.shape != (6,) or not np.isfinite(bounds).all()
            or not np.isfinite(width) or width <= 0):
        raise ValueError("A control-capacity candidate needs finite bounds and positive width")
    span = bounds[1::2] - bounds[::2]
    if np.any(span < 0) or not span.max() > 0:
        raise ValueError("A control-capacity candidate needs nonempty ordered bounds")
    ratios = span / width
    if not np.isfinite(ratios).all():
        raise ValueError("The requested control spacing is outside finite geometry limits")
    shape = [max(3, math.ceil(float(ratio)) + 1) for ratio in ratios]
    count = math.prod(shape)
    return dict(version=VERSION, bounds=bounds.tolist(), kernel_width=float(width),
                spacing=float(width), shape=shape, count=count,
                maximum_controls=MAX_CONTROLS, available=count <= MAX_CONTROLS)


def grid(description):
    expected = describe(description["bounds"], description["kernel_width"])
    if expected != description or not expected["available"]:
        raise ValueError("Requested kernel-spaced grid exceeds the bounded pilot resource limit")
    bounds, spacing = expected["bounds"], expected["spacing"]
    axes = [np.linspace(a, b, n) if b > a else np.linspace(a-spacing, a+spacing, n)
            for a, b, n in zip(bounds[::2], bounds[1::2], expected["shape"], strict=True)]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def bounded_movement(bounds, requested_width, starting_width):
    """Select a feasible movement candidate, retaining spacing equal to its width.

    This may widen an automatic proposed kernel within its declared direction;
    it never undersamples that kernel or changes a user's explicit configuration.
    The selected width and actual point count remain visible candidate values.
    """
    requested = describe(bounds, requested_width)
    if requested["available"] or requested_width >= starting_width:
        return requested
    feasible = describe(bounds, starting_width)
    if not feasible["available"]:
        return requested
    lower, upper = requested_width, starting_width
    for _ in range(50):
        midpoint = (lower + upper) / 2
        if describe(bounds, midpoint)["available"]:
            upper = midpoint
        else:
            lower = midpoint
    return describe(bounds, upper)


def prepare(root, manifest, record):
    from diffeoforge.mesh import sha256_file

    request = record["control_capacity"]
    points = grid(request)
    path = root / "method-controls.txt"
    np.savetxt(path, points, fmt="%.17g")
    return dict(copy=path.name, sha256=sha256_file(path), count=len(points),
                spacing=request["spacing"])


def verify(root, manifest, record):
    request = record.get("control_capacity")
    if not request:
        return
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.config import load_config
    from diffeoforge.surface_io import load_surface_mesh

    config = load_config(study._safe_study_path(root, manifest["source_config"]["copy"]))
    recommendation = config["project"]["parameter_provenance"]["recommendation"]
    template = load_surface_mesh(study._safe_study_path(
        root, manifest["inputs"]["template"]["copy"]))
    values = manifest["plan"]["baseline_effective_values"]
    expected = describe(template.metadata.bounds, values["deformation_kernel_width"])
    controls = record["controls"]
    points = np.loadtxt(study._safe_study_path(root, controls["copy"]), ndmin=2)
    if (recommendation.get("expected_shape_disparity") not in {"high", "extreme"}
            or request != expected or not request["available"]
            or record.get("regional_objective")
            or record.get("refinement", {}).get("initialization") not in {None, "fresh"}
            or controls["count"] != request["count"]
            or controls["spacing"] != values["initial_control_point_spacing"]
            or controls["spacing"] != request["spacing"]
            or not np.array_equal(points, grid(request))):
        raise ValueError("Pilot control capacity differs from its declared ordinary model")

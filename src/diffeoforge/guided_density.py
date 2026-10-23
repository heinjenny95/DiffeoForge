"""A bounded nested basis test, retaining the saved singleton's initial field."""

import math
from pathlib import Path

import numpy as np


def extend(points, spacing):
    from diffeoforge.reference_fit_search import control_grid

    count = math.ceil(len(points) * 1.5)
    if count > 2000:
        raise ValueError("This basis is already too large for the bounded pilot density test")
    bounds = tuple(v for pair in zip(points.min(0), points.max(0), strict=True) for v in pair)
    grid, _ = control_grid(bounds, target=2000)
    from diffeoforge.reference_control_density import _augment

    return _augment(points, grid, spacing, target_count=count)


def copy_basis(root, record):
    """Coverage and joint checks keep the chosen common grid, not screening defaults."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.guided_feedback import verify_reference

    reference = record.get("guided", {}).get("strategy", {}).get("control_basis")
    if not reference:
        return None
    parent = verify_reference(reference)
    controls = parent.attachment_comparison["controls"]
    source = study._safe_study_path(parent.study_directory, controls["copy"])
    destination = root / "method-controls.txt"
    study._copy_bound(source, destination, controls["sha256"])
    return dict(controls, copy=destination.name)


def write(root, request, controls, points, momenta, source, momenta_source):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_pca_deformations import _write_momenta

    spacing = controls["spacing"] * .8
    extended = extend(points, spacing)
    initial = np.zeros((1, len(extended), 3))
    initial[:, :len(points)] = momenta
    cp, mp = root / "density-controls.txt", root / "density-momenta.txt"
    np.savetxt(cp, extended, fmt="%.17g")
    _write_momenta(mp, initial)
    old_cp, old_mp = root / "density-source-controls.txt", root / "density-source-momenta.txt"
    study._copy_bound(source, old_cp, controls["sha256"])
    study._copy_bound(momenta_source, old_mp, sha256_file(momenta_source))
    def row(p):
        return dict(copy=p.name, sha256=sha256_file(p))

    return dict(controls=dict(row(cp), count=len(extended), spacing=spacing),
                refinement=dict(request, initialization="nested",
                    reason="Retain every saved control point and momentum; add zero-momentum "
                    "points. New optimizer history and fresh visual review are required.",
                    momenta=row(mp), source_controls=row(old_cp), source_momenta=row(old_mp),
                    source_momenta_relative=study._relative_path(
                        Path(request["reference"]["directory"]),
                        momenta_source)))


def verify(root, manifest, record):
    """Validate the exact field embedding, not merely a density label."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_pca import read_deformetrica_momenta

    request = record["refinement"]
    arrays = {}
    for key in ("source_controls", "source_momenta", "momenta"):
        row = request[key]
        path = study._safe_study_path(root, row["copy"])
        if sha256_file(path) != row["sha256"]:
            raise ValueError("Nested refinement field bytes changed")
        arrays[key] = (np.loadtxt(path, ndmin=2) if key == "source_controls" else
                       read_deformetrica_momenta(path, allow_singleton=True))
    old = arrays["source_controls"]
    points = np.loadtxt(study._safe_study_path(root, record["controls"]["copy"]), ndmin=2)
    values, previous = manifest["plan"]["baseline_effective_values"], request["reference"]["values"]
    if (record["guided"].get("goal") != "density"
            or set(record["methods"].values()) != {request["reference"]["method"]}
            or any(values[k] != previous[k] for k in previous
                   if k != "initial_control_point_spacing")
            or values["initial_control_point_spacing"]
            != previous["initial_control_point_spacing"] * .8
            or record["controls"]["spacing"] != values["initial_control_point_spacing"]
            or not np.array_equal(points, extend(old, record["controls"]["spacing"]))
            or arrays["momenta"].shape != (1, len(points), 3)
            or not np.array_equal(arrays["momenta"][:, :len(old)], arrays["source_momenta"])
            or np.any(arrays["momenta"][:, len(old):] != 0)):
        raise ValueError("Nested refinement must preserve its source field exactly")
    from diffeoforge.guided_feedback import verify_reference
    parent = verify_reference(request["reference"])
    candidate = next(c for c in parent.candidates
                     if c.candidate_id == request["reference"]["candidate_id"])
    run = study.calibration_candidate_run_directory(candidate)
    original = study._safe_study_path(parent.study_directory, request["source_momenta_relative"])
    if (request["source_controls"]["sha256"] != parent.attachment_comparison["controls"]["sha256"]
            or not original.resolve().is_relative_to(run.resolve())
            or sha256_file(original) != request["source_momenta"]["sha256"]):
        raise ValueError("Nested refinement source differs from the retained fitted field")

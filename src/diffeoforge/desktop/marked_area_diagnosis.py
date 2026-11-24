"""Offer a tentative geometric interpretation of one marked fit area."""

from __future__ import annotations

import numpy as np

from diffeoforge.pilot_regions import validate

_MAX_SAMPLES = 128
_MIN_SAMPLES = 16


def _measure(origin, target, area, *, reconstruction=False):
    if reconstruction and area.get("reconstruction"):
        m = origin.model
        selected = origin.material_faces(area)
        centres = np.asarray(m.vertices)[np.asarray(m.triangles)[selected]].mean(1)
    else:
        centres = origin.centres_in(area)
    count = len(centres)
    if count == 0:
        return 0, 0, None
    if count > _MAX_SAMPLES:
        rows = np.linspace(0, count - 1, _MAX_SAMPLES, dtype=np.int64)
        centres = centres[rows]
    distances = target.closest_distances(centres)
    if not np.isfinite(distances).all():
        raise ValueError("The surface distances in this area are unavailable.")
    return count, len(centres), float(np.percentile(distances, 90))


def _explain(forward, reverse, extent):
    # A suggestion requires one direction to dominate while the other remains
    # close on the scale of the mark. Two large directions can indicate a shift.
    gap = 0.1 * extent
    if forward >= gap and reverse < gap and forward >= 3 * reverse:
        return "missing", "Some original surface may be missing from the fit."
    if reverse >= gap and forward < gap and reverse >= 3 * forward:
        return "distortion", "The fit may include extra surface here."
    if max(forward, reverse) < gap:
        return None, "Most sampled distances are small at this area size."
    return None, "The sampled distances do not clearly distinguish missing or extra surface."


def diagnose(original_marking, reconstruction_marking, row) -> dict:
    """Sample both directions on the exact surfaces and describe the observed gap."""
    area = validate({"original": [row]}, {"original": original_marking.model.sha256})["original"][0]
    original_faces, original_samples, forward = _measure(
        original_marking, reconstruction_marking, area,
    )
    fit_faces, fit_samples, reverse = _measure(reconstruction_marking, original_marking, area,
                                               reconstruction=True)
    if area.get("reconstruction") and original_faces == 0 and fit_samples >= _MIN_SAMPLES:
        symptom = "distortion" if reverse >= 0.1 * area["radius"] else None
        evidence = ("The marked reconstruction material has no original surface in this brush. "
                    "Check this extra surface against the original. A true extra connection "
                    "requires template/input review; a diffeomorphic fit cannot remove it.")
    elif min(original_samples, fit_samples) < _MIN_SAMPLES:
        symptom = None
        evidence = "This area has too few face centres for a reliable two-way suggestion."
    else:
        extent = area["radius"]
        if area.get("shape") == "box":
            extent = float(np.ptp(np.asarray(area["bounds"]).reshape(3, 2), axis=1).min()) / 2
        symptom, evidence = _explain(forward, reverse, extent)

    a = f"{forward:.3g}" if forward is not None else "unavailable"
    b = f"{reverse:.3g}" if reverse is not None else "unavailable"
    return dict(
        message=f"{evidence} Original to fit {a} · Fit to original {b} (P90, mesh units).",
        symptom=symptom,
        original_to_fit_p90=forward,
        fit_to_original_p90=reverse,
        original_face_count=original_faces,
        fit_face_count=fit_faces,
        original_samples=original_samples,
        fit_samples=fit_samples,
    )

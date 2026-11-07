"""Cheap, auditable starting-shape and pilot-coverage suggestions; never fits."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np

from diffeoforge.measurement_cache import measurement_key, read_measurement, write_measurement
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_recommendation import MeshGeometryObservation, _measure_surface
from diffeoforge.shape_descriptor import SHAPE_DESCRIPTOR_VERSION
from diffeoforge.surface_io import load_surface_mesh
from diffeoforge.template_shape import VERSION as LOCAL_VERSION
from diffeoforge.template_shape import distance_matrix, local_shape_descriptor

VERSION = "adaptive-pilot-design-v1"
# Coverage heuristics, not anatomical accuracy or validated sample-size limits.
REDUNDANCY_FRACTION = 0.20
DEFAULT_BUDGET = 6


def coverage_suggestion(recommendation, *, required=(), declarations=(), budget=DEFAULT_BUDGET):
    from diffeoforge.reference_calibration import (
        _descriptor_matrix,
        select_representative_pilot_subjects,
    )

    observations = recommendation.observations[1:]
    n = len(observations)
    if n < 2:
        raise ValueError("Pilot coverage needs at least two available subjects")
    # Obtain the complete deterministic ordering, retaining manual/stratum constraints.
    order = select_representative_pilot_subjects(
        recommendation,
        requested_count=n,
        required_subject_filenames=required,
        pilot_subject_declarations=declarations,
    )
    matrix = _descriptor_matrix(observations)
    distances = np.linalg.norm(matrix[:, None] - matrix[None, :], axis=2)
    diameter = float(distances.max())
    threshold = diameter * REDUNDANCY_FRACTION
    mandatory = sum(s.selection_role.startswith("researcher-") for s in order)
    maximum = min(n, max(budget, mandatory, 2))
    chosen = []
    for subject in order:
        if len(chosen) >= maximum:
            break
        if len(chosen) >= max(2, mandatory) and subject.descriptor_distance <= max(
            threshold, 1e-10
        ):
            break
        chosen.append(subject)
    selected = [s.source_subject_index for s in chosen]
    omitted = []
    for subject in order[len(chosen) :]:
        index = subject.source_subject_index
        nearest = min(selected, key=lambda j: (distances[index, j], observations[j].filename))
        omitted.append(
            dict(
                filename=subject.filename,
                represented_by=observations[nearest].filename,
                distance=float(distances[index, nearest]),
                reason="similar to selected form"
                if distances[index, nearest] <= max(threshold, 1e-10)
                else "additional diversity remains beyond the suggested budget",
            )
        )
    return dict(
        version=VERSION,
        recommended_count=len(chosen),
        available_subjects=n,
        selected=[s.as_manifest() for s in chosen],
        omitted=omitted,
        maximum_uncovered_distance=float(distances[:, selected].min(axis=1).max()),
        redundancy_threshold=threshold,
        budget=maximum,
        budget_limited=any(r["distance"] > max(threshold, 1e-10) for r in omitted),
        limitation="Descriptor coverage is provisional; local details and all later fits need QC. "
        "At least two pilot targets retain a separate cross-check even for very similar forms.",
    )


def suggest_templates(
    paths, *, cache_directory=None, progress_callback=None, cancel_requested=None,
    review_evidence=(),
):
    """Stream originals once; retain cached scalars/descriptors, never a mesh cohort.

    Global and local intrinsic summaries contribute equally before alignment.
    Reviews remain contextual evidence, never a universal template blacklist.
    """
    paths = tuple(sorted({Path(p).resolve() for p in paths}, key=lambda p: str(p).casefold()))
    if len(paths) < 3:
        raise ValueError("Select at least three surface meshes")
    observations, local, failures = [], [], []
    for index, path in enumerate(paths):
        if cancel_requested and cancel_requested():
            raise InterruptedError("Template suggestion cancelled")
        digest = None
        try:
            digest = sha256_file(path)
            key = measurement_key(path, digest, None, 20_000,
                                  SHAPE_DESCRIPTOR_VERSION + "/" + LOCAL_VERSION)
            cached = read_measurement(cache_directory, key)
            if cached is not None:
                detail = cached.get("local_descriptor")
                if (not isinstance(detail, (list, tuple)) or len(detail) != 32
                        or not all(isinstance(v, (float, int)) and np.isfinite(v) for v in detail)):
                    cached = None
            if cached is None:
                loaded = load_surface_mesh(path)
                observation, centroid = _measure_surface(path, None, 20_000, loaded=loaded)
                detail = local_shape_descriptor(loaded.geometry.vertices, loaded.geometry.triangles)
                del loaded
                if sha256_file(path) != digest:
                    raise ValueError("Mesh changed during template suggestion")
                write_measurement(
                    cache_directory,
                    key,
                    {
                        "observation": asdict(observation),
                        "centroid": centroid.tolist(),
                        "local_descriptor": detail,
                    },
                )
            else:
                observation = MeshGeometryObservation(**cached["observation"])
                detail = tuple(cached["local_descriptor"])
                if len(detail) != 32 or not np.isfinite(detail).all():
                    raise ValueError("Invalid local shape measurement; request a fresh suggestion")
                if observation.sha256 != digest or sha256_file(path) != digest:
                    raise ValueError("Cached mesh identity changed")
            observations.append((path, observation))
            local.append(detail)
        except (OSError, ValueError, RuntimeError) as error:
            failures.append(dict(path=str(path), reason=str(error), sha256=digest))
        if progress_callback:
            progress_callback(index + 1, len(paths), path.name)
    if len(observations) < 3:
        raise ValueError("Fewer than three meshes have usable finite surface measurements")
    if cancel_requested and cancel_requested():
        raise InterruptedError("Template suggestion cancelled")
    # Eigenvalues plus radial quantiles: no unapproved PCA alignment/reflection or
    # size normalization is applied to scientific input files.
    raw = np.asarray(
        [(*o.shape_descriptor[:3], *o.shape_descriptor[29:38]) for _, o in observations]
    )
    global_distances = distance_matrix(raw)
    local_distances = distance_matrix(local)
    distances = (global_distances + local_distances) / 2
    ranking = sorted(
        range(len(observations)),
        key=lambda i: (
            float(distances[i].mean()),
            observations[i][0].name.casefold(),
        ),
    )
    records = [
        dict(
            path=str(observations[i][0]),
            filename=observations[i][0].name,
            sha256=observations[i][1].sha256,
            mean_descriptor_distance=float(distances[i].mean()),
            global_distance=float(global_distances[i].mean()),
            local_distance=float(local_distances[i].mean()),
            previous_reviews=[r for r in review_evidence
                              if r.get("source_sha256") == observations[i][1].sha256],
            reason="Central across overall shape and local surface differences. "
            "Starting candidate; suitability still needs visual pilot review.",
        )
        for i in ranking
    ]
    # Put a contrasting option near the top instead of a list of near-identical medoids.
    alternative = max(ranking[1:], key=lambda i: (distances[ranking[0], i], -i))
    for row in records:
        row["contrasting_alternative"] = row["path"] == str(observations[alternative][0])
    gap = (records[1]["mean_descriptor_distance"] - records[0]["mean_descriptor_distance"])
    uncertain = gap <= max(0.05, records[0]["mean_descriptor_distance"] * 0.1)
    return dict(
        version=VERSION + "/" + LOCAL_VERSION,
        candidates=records,
        unreadable_meshes=failures,
        input_binding=[dict(path=str(p), sha256=o.sha256) for p, o in observations],
        uncertain=uncertain,
        limitation="Global/local surface summaries cannot prove deformation suitability or "
        "anatomical correspondence. Previous reviews apply only to their target/settings. "
        "No confident winner is implied by close scores. Aligned coverage is checked separately. "
        "No mesh repaired, transformed, excluded from the atlas or fitted.",
    )

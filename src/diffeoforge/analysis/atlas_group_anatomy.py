"""Paired group mean displacements on a verified common atlas template."""

from __future__ import annotations

import hashlib
import json
import math
import stat
from pathlib import PurePosixPath

import numpy as np

from diffeoforge.desktop.result_review import (
    ModernResultReview,
    ModernResultReviewError,
    verify_result_artifact,
)
from diffeoforge.mesh import read_vtk_polydata_with_metadata, sha256_file

_TOP_FRACTION = 0.05
_MAX_REPORTED_VERTICES = 96
_MAX_OUTLINE_POINTS = 1200
_FACE_BATCH = 32_768
_MAX_MESH_BYTES = 256 * 1024**2
_MIN_EFFECT = 64 * np.finfo(np.float64).eps
_BOUNDARY = (
    "Defines comparison-group minus reference-group reconstruction means on the same "
    "ordered material vertices, scaled by the original template bounding-box diagonal. "
    "RMS and direction cosine weight each vertex by its share of original triangle area. "
    "Top overlap compares a matched number of nonzero-effect vertices. Anatomical "
    "homology and biological significance require independent evidence."
)


def _template_record(review):
    if review.engine_route != "deformetrica_reference":
        raise ValueError("Shared staged material template verification requires Deformetrica.")
    manifest = review.workflow_manifest_path
    if manifest.resolve() != (review.run_directory / "manifest.json").resolve():
        raise ValueError("The reviewed manifest differs from the Deformetrica run manifest.")
    with manifest.open("rb") as stream:
        raw = stream.read(16_777_217)
    if len(raw) > 16_777_216 or hashlib.sha256(raw).hexdigest() != review.workflow_manifest_sha256:
        raise ValueError("The verified Deformetrica run manifest changed.")
    templates = [item for item in json.loads(raw)["inputs"] if item["role"] == "template"]
    if len(templates) != 1:
        raise ValueError("A unique staged template is required in each run manifest.")

    item = templates[0]
    relative = PurePosixPath(item["staged_path"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:2] != ("input", "template")
        or "\\" in item["staged_path"]
        or ":" in item["staged_path"]
    ):
        raise ValueError("The staged template path is outside the atlas inputs.")
    path = review.run_directory
    for part in relative.parts:
        path = path / part
        if path.is_symlink() or (
            getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("The staged template path contains a link.")
    geometry = item["geometry"]
    return path, geometry["bytes"], geometry["sha256"]


def _mesh(path, expected_bytes, expected_digest):
    if not 0 < expected_bytes <= _MAX_MESH_BYTES:
        raise ValueError("The bound surface exceeds the comparison's mesh-size limit.")
    if path.stat().st_size != expected_bytes:
        raise ValueError("A bound surface has changed size.")
    metadata, geometry = read_vtk_polydata_with_metadata(path)
    if metadata.sha256 != expected_digest:
        raise ValueError("A bound surface no longer has the reviewed bytes.")
    return geometry


def _area_weights(vertices, triangles):
    weights = np.zeros(len(vertices), dtype=np.float64)
    for start in range(0, len(triangles), _FACE_BATCH):
        face_ids = triangles[start : start + _FACE_BATCH]
        a, b, c = vertices[face_ids].transpose(1, 0, 2)
        shares = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 6
        np.add.at(weights, face_ids.ravel(), np.repeat(shares, 3))
    total = weights.sum()
    if not np.isfinite(total) or total <= 0:
        raise ValueError("The common template has no finite positive surface area.")
    return weights / total


def _group_difference(review, groups, vertices, triangles, diagonal):
    items = {item.subject_name: item for item in review.registration_qc}
    if len(items) != len(review.registration_qc):
        raise ValueError("Reconstruction subject identities are ambiguous.")
    if any(name not in items for group in groups for name in group):
        raise ValueError("A selected group member has no bound final reconstruction.")

    difference = np.zeros_like(vertices)
    for group, sign in zip(groups, (-1, 1), strict=True):
        total = np.zeros_like(vertices)
        for name in group:
            key = items[name].reconstruction_artifact_key
            artifact = review.artifact(key)
            if artifact.kind != "vtk":
                raise ValueError("A selected final reconstruction is not a surface mesh.")
            if not 0 < artifact.bytes <= _MAX_MESH_BYTES:
                raise ValueError("A final reconstruction exceeds the comparison's mesh-size limit.")
            path = verify_result_artifact(review, key)
            geometry = _mesh(path, artifact.bytes, artifact.sha256)
            points = np.asarray(geometry.vertices, dtype=np.float64)
            if points.shape != vertices.shape or not np.array_equal(geometry.triangles, triangles):
                raise ValueError(
                    "A selected final reconstruction differs from the common template's "
                    "ordered vertex and triangle connectivity."
                )
            total += points - vertices
            del geometry, points
        difference += sign * (total / len(group))
    return difference / diagonal


def _top_order(magnitude, weights):
    active = np.flatnonzero((weights > 0) & (magnitude > _MIN_EFFECT))
    return active[np.lexsort((active, -magnitude[active]))]


def _point_records(indices, vertices, effects, magnitude):
    return [
        {
            "index": int(index),
            "coordinate": vertices[index].tolist(),
            "effect_fraction": effects[index].tolist(),
            "magnitude_fraction": float(magnitude[index]),
        }
        for index in indices[:_MAX_REPORTED_VERTICES]
    ]


def _outline(vertices, weights):
    active = np.flatnonzero(weights > 0)
    if len(active) > _MAX_OUTLINE_POINTS:
        cumulative_area = np.cumsum(weights[active])
        samples = (np.arange(_MAX_OUTLINE_POINTS) + 0.5) * (
            cumulative_area[-1] / _MAX_OUTLINE_POINTS
        )
        active = active[np.unique(np.searchsorted(cumulative_area, samples))]
    return vertices[active].tolist()


def compare_group_anatomy(
    first: ModernResultReview,
    second: ModernResultReview,
    reference_ids: tuple[str, ...],
    comparison_ids: tuple[str, ...],
) -> dict:
    """Compare group means in identical material coordinates without fitting either atlas."""
    try:
        identities = (*reference_ids, *comparison_ids)
        if (
            not reference_ids
            or not comparison_ids
            or any(not isinstance(name, str) or not name for name in identities)
            or len(set(identities)) != len(identities)
        ):
            raise ValueError("Both groups need nonempty, unique and disjoint specimen identities.")
        first_template = _template_record(first)
        second_template = _template_record(second)
        if first_template[1:] != second_template[1:]:
            raise ValueError("The runs have different verified staged template bytes.")
        geometry = _mesh(*first_template)
        if second_template[0] != first_template[0]:
            # Verify the second physical copy without keeping two meshes in memory.
            path, expected_bytes, expected_digest = second_template
            if path.stat().st_size != expected_bytes or sha256_file(path) != expected_digest:
                raise ValueError("The second staged template no longer has the verified bytes.")

        vertices = np.asarray(geometry.vertices, dtype=np.float64)
        triangles = np.asarray(geometry.triangles, dtype=np.int64)
        del geometry
        diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0)))
        if not math.isfinite(diagonal) or diagonal <= 0:
            raise ValueError("The shared template has no finite positive bounding-box diagonal.")
        weights = _area_weights(vertices, triangles)
        groups = (reference_ids, comparison_ids)
        left = _group_difference(first, groups, vertices, triangles, diagonal)
        right = _group_difference(second, groups, vertices, triangles, diagonal)
        left_size = np.linalg.norm(left, axis=1)
        right_size = np.linalg.norm(right, axis=1)
        left_rms = float(np.sqrt(np.dot(weights, left_size**2)))
        right_rms = float(np.sqrt(np.dot(weights, right_size**2)))
        if not all(math.isfinite(value) for value in (left_rms, right_rms)):
            raise ValueError("Group displacement magnitude is not finite.")
        both_have_effect = min(left_rms, right_rms) > _MIN_EFFECT
        cosine = None
        if both_have_effect:
            cosine = float(np.dot(weights, np.einsum("ij,ij->i", left, right)))
            cosine /= left_rms * right_rms
            if not math.isfinite(cosine):
                raise ValueError("The group displacement directions are unavailable.")
            cosine = max(-1.0, min(1.0, cosine))
        count = math.ceil(_TOP_FRACTION * int(np.count_nonzero(weights)))
        left_order, right_order = _top_order(left_size, weights), _top_order(right_size, weights)
        paired_count = min(count, len(left_order), len(right_order))
        left_top = left_order[: paired_count or count]
        right_top = right_order[: paired_count or count]
        shared = int(np.intersect1d(left_top, right_top, assume_unique=True).size)
        return {
            "available": True,
            "basis": {
                "template_sha256": first_template[2],
                "vertex_count": len(vertices),
                "triangle_count": len(triangles),
                "template_diagonal": diagonal,
            },
            "group_counts": {"reference": len(reference_ids), "comparison": len(comparison_ids)},
            "effect_rms_fraction": {"first": left_rms, "second": right_rms},
            "effect_direction_cosine": cosine,
            "top_effect_overlap": {
                "fraction": _TOP_FRACTION,
                "count_per_variant": paired_count,
                "shared_count": shared,
                "jaccard": shared / (2 * paired_count - shared) if paired_count else None,
            },
            "top_vertices": {
                "first": _point_records(left_top, vertices, left, left_size),
                "second": _point_records(right_top, vertices, right, right_size),
            },
            "template_outline": _outline(vertices, weights),
            "boundary": _BOUNDARY,
        }
    except (ModernResultReviewError, KeyError, OSError, TypeError, ValueError) as error:
        return {"available": False, "unavailable_reason": str(error) or type(error).__name__}

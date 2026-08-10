"""Independent analytic ground-truth meshes for registration validation."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import (
    TriangleMesh,
    read_vtk_polydata,
    sha256_file,
    write_vtk_polydata,
)
from diffeoforge.mesh_quality import assess_triangle_mesh

SYNTHETIC_BENCHMARK_VERSION = "0.1"
SYNTHETIC_MANIFEST = "synthetic-ground-truth.json"


@dataclass(frozen=True)
class SyntheticCorrespondenceError:
    vertex_rmse: float
    vertex_p95: float
    vertex_maximum: float
    vertex_count: int


def _vertex_normals(mesh: TriangleMesh) -> np.ndarray:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    triangles = np.asarray(mesh.triangles, dtype=np.int64)
    normals = np.zeros_like(vertices)
    face_normals = np.cross(
        vertices[triangles[:, 1]] - vertices[triangles[:, 0]],
        vertices[triangles[:, 2]] - vertices[triangles[:, 0]],
    )
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths <= np.finfo(float).eps):
        raise ConfigurationError(
            "Synthetic validation requires finite vertex normals on the template"
        )
    return normals / lengths[:, None]


def _deform(
    mesh: TriangleMesh,
    *,
    family: str,
    signed_strength: float,
) -> TriangleMesh:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    center = np.mean(vertices, axis=0)
    extents = np.max(vertices, axis=0) - np.min(vertices, axis=0)
    diagonal = float(np.linalg.norm(extents))
    if diagonal <= 0:
        raise ConfigurationError("Synthetic validation template is degenerate")
    centered = vertices - center
    transformed = centered.copy()
    if family in {"global", "mixed"}:
        z_scale = max(float(extents[2]), diagonal * 0.1)
        angle = signed_strength * 0.42 * centered[:, 2] / z_scale
        cosine = np.cos(angle)
        sine = np.sin(angle)
        x = transformed[:, 0].copy()
        y = transformed[:, 1].copy()
        transformed[:, 0] = cosine * x - sine * y
        transformed[:, 1] = sine * x + cosine * y
        transformed[:, 0] *= 1.0 + signed_strength * 0.04
    if family in {"local", "mixed"}:
        normals = _vertex_normals(mesh)
        anchor = centered[int(np.argmax(centered[:, 0] + 0.35 * centered[:, 2]))]
        squared = np.sum((centered - anchor) ** 2, axis=1)
        sigma = diagonal * 0.18
        envelope = np.exp(-squared / (2.0 * sigma * sigma))
        amplitude = signed_strength * diagonal * (0.035 if family == "local" else 0.025)
        transformed += normals * (amplitude * envelope)[:, None]
    result = TriangleMesh(
        vertices=tuple(tuple(float(value) for value in row) for row in transformed + center),
        triangles=mesh.triangles,
    )
    quality = assess_triangle_mesh(result.vertices, result.triangles)
    invalid = (
        quality.zero_area_faces
        + quality.zero_length_edge_faces
        + quality.undefined_angle_faces
    )
    if invalid:
        raise ConfigurationError(
            f"Synthetic {family} deformation produced {invalid} invalid faces"
        )
    return result


def write_synthetic_validation_benchmark(
    template_path: Path | str,
    destination: Path | str,
    *,
    subjects_per_family: int = 6,
) -> Path:
    """Write a deterministic known-correspondence benchmark without Deformetrica."""

    if not 3 <= subjects_per_family <= 30:
        raise ValueError("subjects_per_family must be between 3 and 30")
    source = Path(template_path).expanduser().resolve()
    template = read_vtk_polydata(source)
    root = Path(destination).expanduser().resolve()
    if root.exists():
        raise ConfigurationError(
            f"Synthetic validation destination already exists: {root}"
        )
    root.mkdir(parents=True)
    try:
        template_copy = root / "template.vtk"
        shutil.copy2(source, template_copy)
        records: list[dict[str, object]] = []
        strengths = np.linspace(-1.0, 1.0, subjects_per_family)
        for family in ("local", "global", "mixed"):
            for index, strength in enumerate(strengths, start=1):
                mesh = _deform(
                    template,
                    family=family,
                    signed_strength=float(strength),
                )
                filename = f"truth-{family}-{index:02d}.vtk"
                path = root / filename
                write_vtk_polydata(path, mesh.vertices, mesh.triangles)
                records.append(
                    {
                        "filename": filename,
                        "sha256": sha256_file(path),
                        "family": family,
                        "signed_strength": float(strength),
                        "vertex_correspondence": "ordered template vertex index",
                    }
                )
        payload = {
            "version": SYNTHETIC_BENCHMARK_VERSION,
            "generator": "DiffeoForge independent analytic deformation",
            "template": {
                "filename": template_copy.name,
                "sha256": sha256_file(template_copy),
                "source_sha256": sha256_file(source),
            },
            "subjects_per_family": subjects_per_family,
            "families": {
                "local": "Localized Gaussian normal displacement.",
                "global": "Smooth height-dependent twist plus broad width change.",
                "mixed": "Independent combination of local and global deformation.",
            },
            "subjects": records,
            "ground_truth": (
                "Every output preserves ordered template connectivity, so exact "
                "vertex correspondences and displacement vectors are known."
            ),
            "scientific_boundary": (
                "Analytic deformations test recovery under known correspondences but "
                "cannot establish performance for all biological anatomy or artifacts."
            ),
        }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        payload["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
        manifest = root / SYNTHETIC_MANIFEST
        write_text_safely(
            manifest,
            json.dumps(
                payload,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            overwrite=False,
        )
    except BaseException:
        if root.is_dir():
            shutil.rmtree(root)
        raise
    return manifest


def evaluate_synthetic_correspondence_error(
    recovered_path: Path | str,
    truth_path: Path | str,
) -> SyntheticCorrespondenceError:
    """Compare recovered coordinates with independent ordered ground truth."""

    recovered = read_vtk_polydata(recovered_path)
    truth = read_vtk_polydata(truth_path)
    if recovered.triangles != truth.triangles or len(recovered.vertices) != len(
        truth.vertices
    ):
        raise ConfigurationError(
            "Synthetic correspondence error requires identical ordered topology"
        )
    difference = np.asarray(recovered.vertices) - np.asarray(truth.vertices)
    distances = np.linalg.norm(difference, axis=1)
    return SyntheticCorrespondenceError(
        vertex_rmse=float(math.sqrt(float(np.mean(distances * distances)))),
        vertex_p95=float(np.quantile(distances, 0.95, method="linear")),
        vertex_maximum=float(np.max(distances)),
        vertex_count=len(distances),
    )

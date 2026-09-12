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


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(
            f"Synthetic ground-truth manifest is unreadable: {path}"
        ) from error
    if not isinstance(value, dict):
        raise ConfigurationError("Synthetic ground-truth manifest must be a JSON object")
    return value


def verify_synthetic_validation_benchmark(
    directory: Path | str,
) -> dict[str, object]:
    """Verify one generated benchmark, its hashes, and ordered topology."""

    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ConfigurationError(f"Synthetic validation benchmark does not exist: {root}")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ConfigurationError("Synthetic validation benchmarks must not contain symbolic links")
    manifest_path = root / SYNTHETIC_MANIFEST
    payload = _read_manifest(manifest_path)
    if payload.get("version") != SYNTHETIC_BENCHMARK_VERSION:
        raise ConfigurationError("Unsupported synthetic ground-truth manifest version")
    fingerprint = payload.get("fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ConfigurationError("Synthetic ground-truth fingerprint is invalid")
    unsigned = dict(payload)
    unsigned.pop("fingerprint", None)
    canonical = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if hashlib.sha256(canonical.encode()).hexdigest() != fingerprint:
        raise ConfigurationError("Synthetic ground-truth fingerprint does not match")

    template_record = payload.get("template")
    subject_records = payload.get("subjects")
    count = payload.get("subjects_per_family")
    if (
        not isinstance(template_record, dict)
        or not isinstance(subject_records, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or len(subject_records) != 3 * count
    ):
        raise ConfigurationError("Synthetic ground-truth inventory is inconsistent")

    filenames: list[str] = []
    records = [template_record, *subject_records]
    for record in records:
        if not isinstance(record, dict):
            raise ConfigurationError("Synthetic ground-truth file record is invalid")
        filename = record.get("filename")
        digest = record.get("sha256")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ConfigurationError("Synthetic ground-truth file binding is invalid")
        path = root / filename
        if not path.is_file() or sha256_file(path) != digest:
            raise ConfigurationError(f"Synthetic ground-truth file hash differs: {filename}")
        filenames.append(filename)
    if len(filenames) != len(set(filenames)):
        raise ConfigurationError("Synthetic ground-truth inventory contains duplicate filenames")

    expected = set(filenames) | {SYNTHETIC_MANIFEST}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != expected:
        raise ConfigurationError("Synthetic ground-truth exact file inventory differs")

    template = read_vtk_polydata(root / str(template_record["filename"]))
    family_counts = {"local": 0, "global": 0, "mixed": 0}
    for record in subject_records:
        if not isinstance(record, dict) or record.get("family") not in family_counts:
            raise ConfigurationError("Synthetic ground-truth deformation family is invalid")
        family = str(record["family"])
        family_counts[family] += 1
        subject = read_vtk_polydata(root / str(record["filename"]))
        if subject.triangles != template.triangles or len(subject.vertices) != len(
            template.vertices
        ):
            raise ConfigurationError(
                "Synthetic ground-truth subjects must preserve exact ordered template topology"
            )
    if any(value != count for value in family_counts.values()):
        raise ConfigurationError("Synthetic ground-truth family counts are inconsistent")
    return payload


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

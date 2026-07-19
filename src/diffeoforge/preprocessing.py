"""Engine-independent, provenance-preserving mesh preprocessing."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS, read_landmark_csv
from diffeoforge.analysis.procrustes import generalized_procrustes
from diffeoforge.config import ConfigurationError
from diffeoforge.initialization import detect_template
from diffeoforge.mesh import read_vtk_polydata, sha256_file, write_vtk_polydata

PREPROCESSING_VERSION = "0.1"
DEFAULT_PROCRUSTES_TOLERANCE = 1e-10
DEFAULT_PROCRUSTES_MAX_ITERATIONS = 100


@dataclass(frozen=True)
class AlignedInputCohort:
    """Immutable aligned inputs ready for any atlas engine."""

    directory: Path
    template: Path
    subjects: tuple[Path, ...]
    landmarks: Path
    evidence: Path
    fingerprint: str


def _resolve_template(directory: Path, template: Path | str | None) -> Path:
    if template is None:
        detected = detect_template(directory)
        if detected is None:
            raise ConfigurationError(
                "No file named template.vtk was found. Select the template explicitly."
            )
        return detected
    candidate = Path(template).expanduser()
    if not candidate.is_absolute():
        candidate = directory / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise ConfigurationError(f"Template mesh does not exist: {candidate}")
    return candidate


def _select_inputs(
    mesh_directory: Path,
    template: Path | str | None,
    subject_pattern: str,
) -> tuple[Path, tuple[Path, ...]]:
    template_path = _resolve_template(mesh_directory, template)
    try:
        candidates = tuple(
            sorted(
                path.resolve()
                for path in mesh_directory.glob(subject_pattern)
                if path.is_file()
            )
        )
    except (OSError, ValueError) as error:
        raise ConfigurationError(f"Invalid subject pattern {subject_pattern!r}: {error}") from error
    subjects = tuple(
        path
        for path in candidates
        if path != template_path and path.suffix.casefold() == ".vtk"
    )
    if len(subjects) < 2:
        raise ConfigurationError("Atlas estimation requires at least two subject meshes")
    cohort = (template_path, *subjects)
    if len({path.name.casefold() for path in cohort}) != len(cohort):
        raise ConfigurationError(
            "Template and subject filenames must be unique when compared case-insensitively"
        )
    return template_path, subjects


def _canonical_hash(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _load_existing(
    destination: Path,
    *,
    fingerprint: str,
    template_name: str,
    subject_names: tuple[str, ...],
) -> AlignedInputCohort:
    evidence_path = destination / "procrustes.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(
            f"Existing aligned-input evidence cannot be verified: {evidence_path}: {error}"
        ) from error
    if evidence.get("preprocessing_version") != PREPROCESSING_VERSION:
        raise ConfigurationError("Existing aligned-input evidence uses an unsupported version")
    if evidence.get("fingerprint") != fingerprint:
        raise ConfigurationError("Existing aligned-input directory has a different fingerprint")
    expected_names = (template_name, *subject_names)
    records = evidence.get("meshes")
    if (
        not isinstance(records, list)
        or tuple(item.get("filename") for item in records) != expected_names
    ):
        raise ConfigurationError("Existing aligned-input evidence lists different meshes")
    for record in records:
        path = destination / record["filename"]
        if not path.is_file() or sha256_file(path) != record.get("aligned_sha256"):
            raise ConfigurationError(
                f"Existing aligned mesh no longer matches its evidence: {path}"
            )
    landmark_copy = destination / "landmarks.csv"
    if not landmark_copy.is_file() or sha256_file(landmark_copy) != evidence.get(
        "landmark_copy_sha256"
    ):
        raise ConfigurationError("Existing aligned landmark copy no longer matches its evidence")
    return AlignedInputCohort(
        directory=destination,
        template=destination / template_name,
        subjects=tuple(destination / name for name in subject_names),
        landmarks=landmark_copy,
        evidence=evidence_path,
        fingerprint=fingerprint,
    )


def prepare_landmark_aligned_inputs(
    mesh_directory: Path | str,
    *,
    project_directory: Path | str,
    landmarks_file: Path | str,
    template: Path | str | None = None,
    subject_pattern: str = "*.vtk",
    scale_to_unit_centroid_size: bool = True,
    allow_reflection: bool = False,
    tolerance: float = DEFAULT_PROCRUSTES_TOLERANCE,
    max_iterations: int = DEFAULT_PROCRUSTES_MAX_ITERATIONS,
) -> AlignedInputCohort:
    """Create or verify one content-addressed Procrustes-aligned mesh cohort.

    Raw meshes are never edited. The resulting directory can be consumed by
    Deformetrica or another engine without repeating or hiding the transform.
    """

    directory = Path(mesh_directory).expanduser().resolve()
    if not directory.is_dir():
        raise ConfigurationError(f"Mesh directory does not exist: {directory}")
    project = Path(project_directory).expanduser().resolve()
    landmark_source = Path(landmarks_file).expanduser().resolve()
    if not landmark_source.is_file():
        raise ConfigurationError(f"Landmark CSV does not exist: {landmark_source}")
    template_path, subject_paths = _select_inputs(directory, template, subject_pattern)
    source_paths = (template_path, *subject_paths)
    labels, landmark_values = read_landmark_csv(
        landmark_source,
        tuple(path.name for path in source_paths),
    )
    try:
        alignment = generalized_procrustes(
            landmark_values,
            scale_to_unit_centroid_size=scale_to_unit_centroid_size,
            allow_reflection=allow_reflection,
            tolerance=tolerance,
            max_iterations=max_iterations,
        )
    except (FloatingPointError, TypeError, ValueError) as error:
        raise ConfigurationError(f"Landmark Procrustes failed: {error}") from error
    if not alignment.converged:
        raise ConfigurationError(
            "Landmark Procrustes did not converge; no aligned inputs were published"
        )

    source_records = tuple(
        {
            "filename": path.name,
            "source_sha256": sha256_file(path),
        }
        for path in source_paths
    )
    settings = {
        "scale_to_unit_centroid_size": scale_to_unit_centroid_size,
        "allow_reflection": allow_reflection,
        "tolerance": float(tolerance),
        "max_iterations": int(max_iterations),
    }
    fingerprint = _canonical_hash(
        {
            "preprocessing_version": PREPROCESSING_VERSION,
            "landmark_sha256": sha256_file(landmark_source),
            "landmark_labels": labels,
            "meshes": source_records,
            "settings": settings,
        }
    )
    preprocessing_root = project / "preprocessing"
    if preprocessing_root.is_symlink():
        raise ConfigurationError(
            f"Refusing to publish preprocessing through a symbolic link: {preprocessing_root}"
        )
    preprocessing_root.mkdir(parents=True, exist_ok=True)
    destination = preprocessing_root / f"aligned-{fingerprint[:16]}"
    if destination.exists():
        if not destination.is_dir() or destination.is_symlink():
            raise ConfigurationError(
                f"Aligned-input destination exists but is not a regular directory: {destination}"
            )
        return _load_existing(
            destination,
            fingerprint=fingerprint,
            template_name=template_path.name,
            subject_names=tuple(path.name for path in subject_paths),
        )

    temporary = Path(tempfile.mkdtemp(prefix=".aligning-", dir=preprocessing_root))
    try:
        landmark_copy = temporary / "landmarks.csv"
        shutil.copyfile(landmark_source, landmark_copy)
        geometries = tuple(read_vtk_polydata(path) for path in source_paths)
        mesh_evidence: list[dict[str, object]] = []
        for index, (source, geometry, transform, residual) in enumerate(
            zip(
                source_paths,
                geometries,
                alignment.transforms,
                alignment.residuals,
                strict=True,
            )
        ):
            aligned_vertices = transform.apply(
                np.asarray(geometry.vertices, dtype=np.float64)
            )
            aligned_path = temporary / source.name
            write_vtk_polydata(
                aligned_path,
                aligned_vertices.tolist(),
                geometry.triangles,
                title=f"DiffeoForge Procrustes aligned mesh {index:04d}",
            )
            mesh_evidence.append(
                {
                    "index": index,
                    "filename": source.name,
                    "source_sha256": source_records[index]["source_sha256"],
                    "aligned_sha256": sha256_file(aligned_path),
                    "residual": residual,
                    "transform": {
                        "centroid": transform.centroid.tolist(),
                        "scale": transform.scale,
                        "rotation": transform.rotation.tolist(),
                    },
                }
            )
        evidence = {
            "preprocessing_version": PREPROCESSING_VERSION,
            "fingerprint": fingerprint,
            "method": "generalized_procrustes",
            "coordinate_convention": "aligned = ((raw - centroid) * scale) @ rotation",
            "landmark_columns": list(LANDMARK_COLUMNS),
            "landmark_labels": list(labels),
            "landmark_source_sha256": sha256_file(landmark_source),
            "landmark_copy_sha256": sha256_file(landmark_copy),
            "settings": settings,
            "converged": alignment.converged,
            "termination_reason": alignment.termination_reason,
            "consensus": alignment.mean_shape.tolist(),
            "history": [
                {
                    "iteration": item.iteration,
                    "mean_change": item.mean_change,
                    "total_squared_residual": item.total_squared_residual,
                }
                for item in alignment.history
            ],
            "meshes": mesh_evidence,
        }
        evidence_path = temporary / "procrustes.json"
        with evidence_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(
                evidence,
                handle,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            handle.write("\n")
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return _load_existing(
        destination,
        fingerprint=fingerprint,
        template_name=template_path.name,
        subject_names=tuple(path.name for path in subject_paths),
    )

"""Engine-independent, provenance-preserving mesh preprocessing."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS, read_landmark_csv
from diffeoforge.analysis.procrustes import (
    GeneralizedProcrustesResult,
    generalized_procrustes,
)
from diffeoforge.atomic_io import replace_atomically
from diffeoforge.config import ConfigurationError
from diffeoforge.initialization import detect_template
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.surface_io import (
    SUPPORTED_SURFACE_EXTENSIONS,
    SurfaceMeshMetadata,
    canonical_vtk_filename,
    inspect_surface_mesh,
    is_supported_surface_path,
    read_surface_mesh,
)

PREPROCESSING_VERSION = "0.2"
DEFAULT_PROCRUSTES_TOLERANCE = 1e-10
DEFAULT_PROCRUSTES_MAX_ITERATIONS = 100


@dataclass(frozen=True)
class AlignedInputCohort:
    """Immutable aligned inputs ready for any atlas engine."""

    directory: Path
    raw_directory: Path
    aligned_directory: Path
    template: Path
    subjects: tuple[Path, ...]
    landmarks: Path
    evidence: Path
    fingerprint: str


@dataclass(frozen=True)
class LandmarkAlignmentPreview:
    """Read-only, content-bound generalized-Procrustes observation."""

    mesh_directory: Path
    template: Path
    subjects: tuple[Path, ...]
    subject_pattern: str
    landmarks: Path
    landmark_labels: tuple[str, ...]
    landmark_sha256: str
    mesh_sha256: tuple[str, ...]
    source_metadata: tuple[SurfaceMeshMetadata, ...]
    aligned_filenames: tuple[str, ...]
    scale_to_unit_centroid_size: bool
    allow_reflection: bool
    tolerance: float
    max_iterations: int
    fingerprint: str
    alignment: GeneralizedProcrustesResult

    @property
    def source_paths(self) -> tuple[Path, ...]:
        return (self.template, *self.subjects)


def _resolve_template(directory: Path, template: Path | str | None) -> Path:
    if template is None:
        detected = detect_template(directory)
        if detected is None:
            raise ConfigurationError(
                "No supported file named template.vtk, template.ply, template.obj, or "
                "template.stl was found. Select the template explicitly."
            )
        return detected
    candidate = Path(template).expanduser()
    if not candidate.is_absolute():
        candidate = directory / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise ConfigurationError(f"Template mesh does not exist: {candidate}")
    if not is_supported_surface_path(candidate):
        raise ConfigurationError(
            f"Unsupported template format {candidate.suffix or '<none>'!r}. "
            "Supported inputs are VTK, PLY, OBJ, and STL."
        )
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
        if path != template_path
        and path.suffix.casefold() in SUPPORTED_SURFACE_EXTENSIONS
    )
    if len(subjects) < 2:
        raise ConfigurationError("Atlas estimation requires at least two subject meshes")
    cohort = (template_path, *subjects)
    if len({path.name.casefold() for path in cohort}) != len(cohort):
        raise ConfigurationError(
            "Template and subject filenames must be unique when compared case-insensitively"
        )
    canonical_names = tuple(canonical_vtk_filename(path) for path in cohort)
    if len({name.casefold() for name in canonical_names}) != len(canonical_names):
        raise ConfigurationError(
            "Template and subject stems must be unique when converted to canonical VTK "
            "filenames"
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


def preview_landmark_alignment(
    mesh_directory: Path | str,
    *,
    landmarks_file: Path | str,
    template: Path | str | None = None,
    subject_pattern: str = "*.vtk",
    scale_to_unit_centroid_size: bool = True,
    allow_reflection: bool = False,
    tolerance: float = DEFAULT_PROCRUSTES_TOLERANCE,
    max_iterations: int = DEFAULT_PROCRUSTES_MAX_ITERATIONS,
) -> LandmarkAlignmentPreview:
    """Compute a hash-bound alignment preview without creating or changing files."""

    directory = Path(mesh_directory).expanduser().resolve()
    if not directory.is_dir():
        raise ConfigurationError(f"Mesh directory does not exist: {directory}")
    landmark_source = Path(landmarks_file).expanduser().resolve()
    if not landmark_source.is_file():
        raise ConfigurationError(f"Landmark CSV does not exist: {landmark_source}")
    template_path, subject_paths = _select_inputs(directory, template, subject_pattern)
    source_paths = (template_path, *subject_paths)
    source_metadata = tuple(inspect_surface_mesh(path) for path in source_paths)
    source_hashes = tuple(item.sha256 for item in source_metadata)
    aligned_filenames = tuple(canonical_vtk_filename(path) for path in source_paths)
    landmark_hash = sha256_file(landmark_source)
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
    if sha256_file(landmark_source) != landmark_hash or tuple(
        sha256_file(path) for path in source_paths
    ) != source_hashes:
        raise ConfigurationError(
            "A mesh or landmark file changed while the Procrustes preview was computed"
        )
    source_records = tuple(
        {
            "source_filename": path.name,
            "source_sha256": metadata.sha256,
            "source_format": metadata.source_format,
            "source_encoding": metadata.encoding,
            "aligned_filename": aligned_filename,
        }
        for path, metadata, aligned_filename in zip(
            source_paths,
            source_metadata,
            aligned_filenames,
            strict=True,
        )
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
            "landmark_sha256": landmark_hash,
            "landmark_labels": labels,
            "meshes": source_records,
            "settings": settings,
        }
    )
    return LandmarkAlignmentPreview(
        mesh_directory=directory,
        template=template_path,
        subjects=subject_paths,
        subject_pattern=subject_pattern,
        landmarks=landmark_source,
        landmark_labels=labels,
        landmark_sha256=landmark_hash,
        mesh_sha256=source_hashes,
        source_metadata=source_metadata,
        aligned_filenames=aligned_filenames,
        scale_to_unit_centroid_size=scale_to_unit_centroid_size,
        allow_reflection=allow_reflection,
        tolerance=float(tolerance),
        max_iterations=int(max_iterations),
        fingerprint=fingerprint,
        alignment=alignment,
    )


def _load_existing(
    destination: Path,
    *,
    fingerprint: str,
    source_names: tuple[str, ...],
    aligned_names: tuple[str, ...],
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
    records = evidence.get("meshes")
    if (
        not isinstance(records, list)
        or tuple(item.get("source_filename") for item in records) != source_names
        or tuple(item.get("filename") for item in records) != aligned_names
    ):
        raise ConfigurationError("Existing aligned-input evidence lists different meshes")
    raw_directory = destination / "raw"
    aligned_directory = destination / "aligned-vtk"
    if raw_directory.is_symlink() or aligned_directory.is_symlink():
        raise ConfigurationError(
            "Existing aligned-input raw or aligned directory is a symbolic link"
        )
    for source_name, aligned_name, record in zip(
        source_names,
        aligned_names,
        records,
        strict=True,
    ):
        raw_path = raw_directory / source_name
        aligned_path = aligned_directory / aligned_name
        if (
            record.get("raw_copy_path") != f"raw/{source_name}"
            or not raw_path.is_file()
            or raw_path.is_symlink()
            or sha256_file(raw_path) != record.get("raw_copy_sha256")
            or record.get("raw_copy_sha256") != record.get("source_sha256")
        ):
            raise ConfigurationError(
                f"Existing raw mesh copy no longer matches its evidence: {raw_path}"
            )
        if (
            record.get("aligned_path") != f"aligned-vtk/{aligned_name}"
            or not aligned_path.is_file()
            or aligned_path.is_symlink()
            or sha256_file(aligned_path) != record.get("aligned_sha256")
        ):
            raise ConfigurationError(
                f"Existing aligned mesh no longer matches its evidence: {aligned_path}"
            )
    landmark_copy = destination / "landmarks.csv"
    if (
        not landmark_copy.is_file()
        or landmark_copy.is_symlink()
        or sha256_file(landmark_copy) != evidence.get("landmark_copy_sha256")
    ):
        raise ConfigurationError("Existing aligned landmark copy no longer matches its evidence")
    return AlignedInputCohort(
        directory=destination,
        raw_directory=raw_directory,
        aligned_directory=aligned_directory,
        template=aligned_directory / aligned_names[0],
        subjects=tuple(aligned_directory / name for name in aligned_names[1:]),
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
    expected_fingerprint: str | None = None,
) -> AlignedInputCohort:
    """Create or verify one content-addressed Procrustes-aligned mesh cohort.

    Raw meshes are never edited. The resulting directory can be consumed by
    Deformetrica or another engine without repeating or hiding the transform.
    """

    project = Path(project_directory).expanduser().resolve()
    preview = preview_landmark_alignment(
        mesh_directory,
        landmarks_file=landmarks_file,
        template=template,
        subject_pattern=subject_pattern,
        scale_to_unit_centroid_size=scale_to_unit_centroid_size,
        allow_reflection=allow_reflection,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    if expected_fingerprint is not None and preview.fingerprint != expected_fingerprint:
        raise ConfigurationError(
            "The current Procrustes inputs or settings differ from the approved preview"
        )
    alignment = preview.alignment
    if not alignment.converged:
        raise ConfigurationError(
            "Landmark Procrustes did not converge; no aligned inputs were published"
        )
    landmark_source = preview.landmarks
    source_paths = preview.source_paths
    labels = preview.landmark_labels
    source_records = tuple(
        {
            "source_filename": path.name,
            "source_sha256": metadata.sha256,
            "source_format": metadata.source_format,
            "source_encoding": metadata.encoding,
            "source_points": metadata.points,
            "source_triangles": metadata.triangles,
            "topology_note": metadata.topology_note,
            "filename": aligned_name,
        }
        for path, metadata, aligned_name in zip(
            source_paths,
            preview.source_metadata,
            preview.aligned_filenames,
            strict=True,
        )
    )
    settings = {
        "scale_to_unit_centroid_size": scale_to_unit_centroid_size,
        "allow_reflection": allow_reflection,
        "tolerance": float(tolerance),
        "max_iterations": int(max_iterations),
    }
    fingerprint = preview.fingerprint
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
            source_names=tuple(path.name for path in source_paths),
            aligned_names=preview.aligned_filenames,
        )

    temporary = Path(tempfile.mkdtemp(prefix=".aligning-", dir=preprocessing_root))
    try:
        raw_directory = temporary / "raw"
        aligned_directory = temporary / "aligned-vtk"
        raw_directory.mkdir()
        aligned_directory.mkdir()
        landmark_copy = temporary / "landmarks.csv"
        if sha256_file(landmark_source) != preview.landmark_sha256:
            raise ConfigurationError(
                "The landmark file changed after the approved Procrustes preview"
            )
        shutil.copyfile(landmark_source, landmark_copy)
        if sha256_file(landmark_copy) != preview.landmark_sha256:
            raise ConfigurationError(
                "The copied landmark file differs from the approved Procrustes preview"
            )
        geometries = []
        for path, expected_sha256, expected_metadata in zip(
            source_paths,
            preview.mesh_sha256,
            preview.source_metadata,
            strict=True,
        ):
            if sha256_file(path) != expected_sha256:
                raise ConfigurationError(
                    f"Mesh changed after the approved Procrustes preview: {path}"
                )
            raw_copy = raw_directory / path.name
            shutil.copyfile(path, raw_copy)
            if sha256_file(raw_copy) != expected_sha256:
                raise ConfigurationError(
                    f"Raw mesh copy differs from the approved Procrustes preview: {path}"
                )
            geometry = read_surface_mesh(path)
            if sha256_file(path) != expected_sha256:
                raise ConfigurationError(
                    f"Mesh changed while the aligned copy was prepared: {path}"
                )
            if (
                len(geometry.vertices) != expected_metadata.points
                or len(geometry.triangles) != expected_metadata.triangles
            ):
                raise ConfigurationError(
                    f"Mesh geometry changed after the approved Procrustes preview: {path}"
                )
            geometries.append(geometry)
        mesh_evidence: list[dict[str, object]] = []
        for index, (
            source,
            geometry,
            transform,
            residual,
            aligned_filename,
            source_record,
        ) in enumerate(
            zip(
                source_paths,
                geometries,
                alignment.transforms,
                alignment.residuals,
                preview.aligned_filenames,
                source_records,
                strict=True,
            )
        ):
            aligned_vertices = transform.apply(
                np.asarray(geometry.vertices, dtype=np.float64)
            )
            aligned_path = aligned_directory / aligned_filename
            write_vtk_polydata(
                aligned_path,
                aligned_vertices.tolist(),
                geometry.triangles,
                title=f"DiffeoForge Procrustes aligned mesh {index:04d}",
            )
            mesh_evidence.append(
                {
                    "index": index,
                    **source_record,
                    "raw_copy_path": f"raw/{source.name}",
                    "raw_copy_sha256": sha256_file(raw_directory / source.name),
                    "aligned_path": f"aligned-vtk/{aligned_filename}",
                    "aligned_sha256": sha256_file(aligned_path),
                    "aligned_format": "legacy_vtk",
                    "aligned_points": len(geometry.vertices),
                    "aligned_triangles": len(geometry.triangles),
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
            "directory_layout": {
                "raw": "raw",
                "aligned_vtk": "aligned-vtk",
                "raw_policy": "byte-identical immutable source copies",
                "aligned_policy": "deterministic ASCII legacy VTK triangle surfaces",
            },
            "landmark_columns": list(LANDMARK_COLUMNS),
            "landmark_labels": list(labels),
            "landmark_source_sha256": preview.landmark_sha256,
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
        if sha256_file(landmark_source) != preview.landmark_sha256 or tuple(
            sha256_file(path) for path in source_paths
        ) != preview.mesh_sha256:
            raise ConfigurationError(
                "A mesh or landmark file changed while the aligned copies were prepared"
            )
        replace_atomically(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return _load_existing(
        destination,
        fingerprint=fingerprint,
        source_names=tuple(path.name for path in source_paths),
        aligned_names=preview.aligned_filenames,
    )

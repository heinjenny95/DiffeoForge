"""Fail-closed production-scale readiness for Deformetrica reference runs."""

from __future__ import annotations

import math
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from diffeoforge.config import resolve_output_directory
from diffeoforge.report import PreflightResult

if TYPE_CHECKING:
    from diffeoforge.runs import ResumeSourceEvidence

PRODUCTION_SUBJECT_THRESHOLD = 250
PRODUCTION_FACE_THRESHOLD = 8_000
MAX_PRODUCTION_CHECKPOINT_INTERVAL = 5
OUTPUT_SERIALIZATION_SAFETY_FACTOR = 1.25
RESUME_STORAGE_COPIES = 2
MINIMUM_FREE_DISK_RESERVE_BYTES = 2 * 1024**3


@dataclass(frozen=True)
class ReferenceProductionReadiness:
    """Measured prelaunch storage and recovery contract for one reviewed cohort."""

    production_scale: bool
    ready: bool
    subject_count: int
    maximum_subject_faces: int
    template_faces: int
    timepoints: int
    checkpoint_interval: int
    projected_vtk_file_count: int
    projected_output_bytes: int
    required_free_bytes: int
    observed_free_bytes: int
    output_root: Path
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise OSError(f"No existing parent could be found for output root: {path}")
        candidate = parent
    if not candidate.is_dir():
        candidate = candidate.parent
    return candidate


def _free_bytes(output_root: Path, observed_free_bytes: int | None) -> int:
    if observed_free_bytes is None:
        return int(shutil.disk_usage(_nearest_existing_directory(output_root)).free)
    if isinstance(observed_free_bytes, bool) or observed_free_bytes < 0:
        raise ValueError("observed_free_bytes must be a nonnegative integer")
    return int(observed_free_bytes)


def _production_warnings(
    *,
    device: str,
    output_root: Path,
) -> list[str]:
    warnings: list[str] = []
    if device != "cuda":
        warnings.append(
            "Production-scale execution is configured for CPU only. This is allowed, "
            "but the intended RTX/KeOps route should be benchmarked before the full run."
        )
    if len(str(output_root)) > 120:
        warnings.append(
            "The configured output root is long. A short local project path reduces "
            "Windows/WSL path and generated-filename risk for thousands of artifacts."
        )
    warnings.append(
        "Projected output bytes are a conservative planning estimate, not observed "
        "peak disk use; qualification must measure the final cohort."
    )
    return warnings


def assess_reference_production_readiness(
    preflight: PreflightResult,
    *,
    observed_free_bytes: int | None = None,
) -> ReferenceProductionReadiness:
    """Assess only engineering readiness; do not infer scientific suitability."""

    if not isinstance(preflight, PreflightResult):
        raise TypeError("preflight must be a PreflightResult")
    config = preflight.config
    subject_count = len(preflight.subjects)
    maximum_subject_faces = max(subject.cells for subject in preflight.subjects)
    template_faces = int(preflight.template.cells)
    timepoints = int(config["model"]["deformation"]["timepoints"])
    checkpoint_interval = int(config["optimization"]["save_every_n_iterations"])
    production_scale = bool(
        subject_count >= PRODUCTION_SUBJECT_THRESHOLD
        and max(maximum_subject_faces, template_faces) >= PRODUCTION_FACE_THRESHOLD
    )

    # Deformetrica retains one trajectory mesh per subject and time point, one
    # final reconstruction per subject, and the estimated template. The safety
    # factor covers ASCII formatting and small metadata differences without
    # pretending to be an observed byte-exact forecast.
    projected_vtk_file_count = 1 + subject_count * (timepoints + 1)
    largest_input_bytes = max(
        preflight.template.bytes,
        *(subject.bytes for subject in preflight.subjects),
    )
    projected_output_bytes = math.ceil(
        projected_vtk_file_count
        * largest_input_bytes
        * OUTPUT_SERIALIZATION_SAFETY_FACTOR
    )
    # Reserve enough room for the first immutable run and one immutable resume
    # successor. Source data outside the project are not counted as available
    # working storage.
    required_free_bytes = (
        RESUME_STORAGE_COPIES
        * (preflight.total_input_bytes + projected_output_bytes)
        + MINIMUM_FREE_DISK_RESERVE_BYTES
    )
    output_root = resolve_output_directory(config, preflight.config_path)
    free_bytes = _free_bytes(output_root, observed_free_bytes)

    blockers: list[str] = []
    warnings: list[str] = []
    if production_scale:
        if checkpoint_interval > MAX_PRODUCTION_CHECKPOINT_INTERVAL:
            blockers.append(
                "Production-scale runs must save a checkpoint at least every "
                f"{MAX_PRODUCTION_CHECKPOINT_INTERVAL} iterations; the reviewed value is "
                f"{checkpoint_interval}."
            )
        if free_bytes < required_free_bytes:
            blockers.append(
                "Free disk space is below the fail-safe run-plus-resume reserve: "
                f"{free_bytes} observed bytes versus {required_free_bytes} required bytes."
            )
        warnings.extend(
            _production_warnings(
                device=str(config["runtime"]["device"]),
                output_root=output_root,
            )
        )

    return ReferenceProductionReadiness(
        production_scale=production_scale,
        ready=not blockers,
        subject_count=subject_count,
        maximum_subject_faces=maximum_subject_faces,
        template_faces=template_faces,
        timepoints=timepoints,
        checkpoint_interval=checkpoint_interval,
        projected_vtk_file_count=projected_vtk_file_count,
        projected_output_bytes=projected_output_bytes,
        required_free_bytes=required_free_bytes,
        observed_free_bytes=free_bytes,
        output_root=output_root,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def assess_reference_resume_production_readiness(
    evidence: ResumeSourceEvidence,
    *,
    observed_free_bytes: int | None = None,
) -> ReferenceProductionReadiness:
    """Recheck production cadence and successor storage from protected run evidence."""

    manifest: Mapping[str, Any] = evidence.manifest
    config = manifest["effective_config"]
    inputs = manifest["inputs"]
    subjects = [item for item in inputs if item["role"] == "subject"]
    templates = [item for item in inputs if item["role"] == "template"]
    if len(templates) != 1 or not subjects:
        raise ValueError("Resume source input evidence is incomplete")
    subject_count = int(manifest["input_count"]["subjects"])
    if subject_count != len(subjects):
        raise ValueError("Resume source subject count differs from its input evidence")
    subject_faces = [int(item["geometry"]["cells"]) for item in subjects]
    template_faces = int(templates[0]["geometry"]["cells"])
    input_bytes = sum(int(item["geometry"]["bytes"]) for item in inputs)
    largest_input_bytes = max(int(item["geometry"]["bytes"]) for item in inputs)
    timepoints = int(config["model"]["deformation"]["timepoints"])
    checkpoint_interval = int(config["optimization"]["save_every_n_iterations"])
    maximum_subject_faces = max(subject_faces)
    production_scale = bool(
        subject_count >= PRODUCTION_SUBJECT_THRESHOLD
        and max(maximum_subject_faces, template_faces) >= PRODUCTION_FACE_THRESHOLD
    )
    projected_vtk_file_count = 1 + subject_count * (timepoints + 1)
    geometric_projection = math.ceil(
        projected_vtk_file_count
        * largest_input_bytes
        * OUTPUT_SERIALIZATION_SAFETY_FACTOR
    )
    observed_output_bytes = int(evidence.result["outputs"]["total_bytes"])
    projected_output_bytes = max(geometric_projection, observed_output_bytes)
    # The source already exists. Recheck that one complete immutable successor
    # still fits before any copied input or checkpoint is written.
    required_free_bytes = (
        input_bytes + projected_output_bytes + MINIMUM_FREE_DISK_RESERVE_BYTES
    )
    output_root = evidence.source_run.parent
    free_bytes = _free_bytes(output_root, observed_free_bytes)

    blockers: list[str] = []
    warnings: list[str] = []
    if production_scale:
        if checkpoint_interval > MAX_PRODUCTION_CHECKPOINT_INTERVAL:
            blockers.append(
                "Production-scale resume requires a checkpoint at least every "
                f"{MAX_PRODUCTION_CHECKPOINT_INTERVAL} iterations; the protected value is "
                f"{checkpoint_interval}."
            )
        if free_bytes < required_free_bytes:
            blockers.append(
                "Free disk space is below the immutable-successor reserve: "
                f"{free_bytes} observed bytes versus {required_free_bytes} required bytes."
            )
        warnings.extend(
            _production_warnings(
                device=str(config["runtime"]["device"]),
                output_root=output_root,
            )
        )

    return ReferenceProductionReadiness(
        production_scale=production_scale,
        ready=not blockers,
        subject_count=subject_count,
        maximum_subject_faces=maximum_subject_faces,
        template_faces=template_faces,
        timepoints=timepoints,
        checkpoint_interval=checkpoint_interval,
        projected_vtk_file_count=projected_vtk_file_count,
        projected_output_bytes=projected_output_bytes,
        required_free_bytes=required_free_bytes,
        observed_free_bytes=free_bytes,
        output_root=output_root,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )

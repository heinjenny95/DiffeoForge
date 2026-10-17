"""Save and restore first-screen checks without repeating geometry or GPA work."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diffeoforge.analysis.landmarks import read_landmark_csv
from diffeoforge.input_preflight import (
    MeshInputPreflight,
    assess_mesh_input_metadata,
    inspect_mesh_input_cohort,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.mesh_quality import QUALITY_DEFINITIONS_VERSION
from diffeoforge.preprocessing import PREPROCESSING_VERSION, LandmarkAlignmentPreview
from diffeoforge.project_checkpoint import (
    CheckpointUnavailable,
    load_checkpoint,
    save_checkpoint,
)


@dataclass(frozen=True)
class RestoredSetup:
    preflight: MeshInputPreflight | None
    preview: LandmarkAlignmentPreview | None
    reviewed_fingerprint: str | None
    approved: bool
    message: str


def save_setup_checkpoint(
    project: Path | str,
    form: dict[str, Any],
    preflight: MeshInputPreflight | None,
    preview: LandmarkAlignmentPreview | None,
    reviewed_fingerprint: str | None,
    approved: bool,
) -> None:
    save_checkpoint(project, "setup", {
        "form": form, "preflight": preflight, "preview": preview,
        "reviewed_fingerprint": reviewed_fingerprint,
        "approved": approved is True and preview is not None
        and reviewed_fingerprint == preview.fingerprint and preview.alignment.converged,
        "quality_definitions_version": QUALITY_DEFINITIONS_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
    })


def load_setup_form(project: Path | str) -> dict[str, Any] | None:
    try:
        saved = load_checkpoint(project, "setup")
        if not isinstance(saved, dict) or not isinstance(saved.get("form"), dict):
            return None
        return saved["form"]
    except CheckpointUnavailable:
        return None


def restore_setup_checkpoint(
    project: Path | str, form: dict[str, Any], mesh_paths: tuple[Path, ...],
    landmark_csv: Path | None,
) -> RestoredSetup:
    """Read/hash only. Missing checks never trigger a deep scan or GPA solver."""

    try:
        saved = load_checkpoint(project, "setup")
    except CheckpointUnavailable:
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    exact_form = saved.get("form") == form
    report = saved.get("preflight")
    current_report = False
    if (exact_form and isinstance(report, MeshInputPreflight)
            and saved.get("quality_definitions_version") == QUALITY_DEFINITIONS_VERSION
            and tuple(Path(item.path).resolve() for item in report.metadata) == mesh_paths
            and tuple(Path(item.path).resolve() for item in report.mesh_quality) == mesh_paths
            and len(report.mesh_scale_metrics) == len(mesh_paths)
            and report.landmark_path == landmark_csv):
        current_report = (
            tuple(sha256_file(path) for path in mesh_paths)
            == tuple(item.sha256 for item in report.metadata)
            and (sha256_file(landmark_csv) if landmark_csv else None) == report.landmark_sha256
        )
    if not current_report:
        try:
            report = inspect_mesh_input_cohort(
                mesh_paths, template_path=mesh_paths[0], landmark_csv=landmark_csv,
                procrustes_enabled=bool(form["apply_alignment"] and landmark_csv),
                scale_to_unit_centroid_size=bool(form["remove_size"]),
                scaling_mode=form["scaling_mode"], cache_project=project, cache_only=True,
            )
        except CheckpointUnavailable as error:
            return RestoredSetup(None, None, None, False, str(error))
    else:
        labels, values = (
            read_landmark_csv(landmark_csv, tuple(path.name for path in mesh_paths))
            if landmark_csv else (None, None)
        )
        # Reapply current gates/notices to stored measurements, not stale pass/fail.
        report = assess_mesh_input_metadata(
            report.metadata, mesh_quality=report.mesh_quality,
            mesh_scale_metrics=report.mesh_scale_metrics, template_path=mesh_paths[0],
            landmark_path=landmark_csv, landmark_sha256=report.landmark_sha256,
            landmark_labels=labels, landmark_values=values,
            procrustes_enabled=bool(form["apply_alignment"] and landmark_csv),
            scale_to_unit_centroid_size=bool(form["remove_size"]),
            scaling_mode=form["scaling_mode"],
        )
    preview = saved.get("preview")
    if not (
        exact_form and isinstance(preview, LandmarkAlignmentPreview)
        and saved.get("preprocessing_version") == PREPROCESSING_VERSION
        and preview.source_paths == mesh_paths
        and preview.mesh_sha256 == tuple(item.sha256 for item in report.metadata)
        and preview.landmarks == landmark_csv
        and preview.landmark_sha256 == report.landmark_sha256
        and preview.scaling_mode.value == form["scaling_mode"]
        and preview.target_size == form["target_size"]
        and preview.allow_reflection == form["allow_reflection"]
        and preview.tolerance == form["tolerance"]
        and preview.max_iterations == form["max_iterations"]
    ):
        preview = None
    reviewed = (
        preview.fingerprint if preview is not None and preview.alignment.converged
        and saved.get("reviewed_fingerprint") == preview.fingerprint else None
    )
    approved = bool(reviewed is not None and saved.get("approved") is True)
    return RestoredSetup(
        report, preview, reviewed, approved,
        "Saved checks verified. No deep mesh validation or GPA was repeated.",
    )

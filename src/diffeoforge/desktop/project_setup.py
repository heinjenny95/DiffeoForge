"""Qt-independent application service for the first desktop project slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from diffeoforge.config import ConfigurationError, validate_input_paths
from diffeoforge.initialization import SUPPORTED_UNITS, initialize_project
from diffeoforge.report import default_preflight_report_path, write_preflight_report


class DesktopEngine(StrEnum):
    """Engine choices exposed by the first desktop project-setup screen."""

    MODERN_CPU = "modern_cpu"
    DEFORMETRICA_REFERENCE = "deformetrica_reference"


@dataclass(frozen=True)
class ProjectSetupRequest:
    """Explicit, serializable inputs for creating one desktop project."""

    mesh_directory: Path
    project_directory: Path
    units: str
    engine: DesktopEngine = DesktopEngine.MODERN_CPU
    template: Path | None = None
    project_name: str | None = None
    subject_pattern: str = "*.vtk"
    landmarks_file: Path | None = None


@dataclass(frozen=True)
class ProjectSetupResult:
    """User-facing evidence returned after project creation succeeds."""

    engine: DesktopEngine
    config_path: Path
    template_path: Path
    subject_count: int
    report_path: Path | None
    notices: tuple[str, ...]

    @property
    def engine_label(self) -> str:
        """Return a stable label suitable for the desktop result summary."""

        if self.engine is DesktopEngine.MODERN_CPU:
            return "DiffeoForge Modern CPU (experimental)"
        return "Deformetrica 4.3 reference (external)"


def _normalize_request(request: ProjectSetupRequest) -> ProjectSetupRequest:
    if not isinstance(request, ProjectSetupRequest):
        raise TypeError("request must be a ProjectSetupRequest")
    try:
        engine = DesktopEngine(request.engine)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"Unsupported desktop engine: {request.engine!r}") from error
    if request.units not in SUPPORTED_UNITS:
        raise ConfigurationError(f"Unsupported coordinate unit: {request.units!r}")
    pattern = request.subject_pattern.strip()
    if not pattern:
        raise ConfigurationError("Subject filename pattern must not be empty")
    name = request.project_name.strip() if request.project_name else None
    if request.landmarks_file is not None and engine is DesktopEngine.DEFORMETRICA_REFERENCE:
        raise ConfigurationError(
            "Landmark Procrustes is currently available only for the modern CPU workflow"
        )
    return ProjectSetupRequest(
        mesh_directory=Path(request.mesh_directory).expanduser().resolve(),
        project_directory=Path(request.project_directory).expanduser().resolve(),
        units=request.units,
        engine=engine,
        template=(
            None if request.template is None else Path(request.template).expanduser().resolve()
        ),
        project_name=name,
        subject_pattern=pattern,
        landmarks_file=(
            None
            if request.landmarks_file is None
            else Path(request.landmarks_file).expanduser().resolve()
        ),
    )


def _create_reference_project(request: ProjectSetupRequest) -> ProjectSetupResult:
    config_path = request.project_directory / "atlas.yaml"
    report_path = default_preflight_report_path(config_path)
    if report_path.exists():
        raise ConfigurationError(
            f"Preflight report already exists and will not be overwritten: {report_path}"
        )
    initialized = initialize_project(
        request.mesh_directory,
        units=request.units,
        config_path=config_path,
        template=request.template,
        subject_pattern=request.subject_pattern,
        project_name=request.project_name,
    )
    write_preflight_report(initialized.preflight, report_path)
    notices = list(initialized.preflight.notices)
    if initialized.derived_parameters:
        notices.insert(
            0,
            "Geometry-scaled starter values are exploratory and require scientific review.",
        )
    notices.append(
        "Project creation did not execute Deformetrica; prepare and run are separate "
        "reviewed steps."
    )
    return ProjectSetupResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        config_path=initialized.config_path,
        template_path=initialized.preflight.inputs.template,
        subject_count=len(initialized.preflight.subjects),
        report_path=report_path,
        notices=tuple(notices),
    )


def _create_modern_project(request: ProjectSetupRequest) -> ProjectSetupResult:
    try:
        from diffeoforge.modern_workflow import (
            initialize_modern_workflow,
            load_modern_workflow_config,
        )
    except ImportError as error:
        raise ConfigurationError(
            "Modern engine dependencies are missing; install diffeoforge[modern-engine]."
        ) from error

    config_path = request.project_directory / "modern-atlas.yaml"
    initialize_modern_workflow(
        request.mesh_directory,
        units=request.units,
        config_path=config_path,
        template=request.template,
        subject_pattern=request.subject_pattern,
        project_name=request.project_name,
        landmarks_file=request.landmarks_file,
    )
    config = load_modern_workflow_config(config_path)
    inputs = validate_input_paths(config, config_path)
    notices = [
        "Geometry-scaled starter values are exploratory and require scientific review.",
        "Project creation validated the supported meshes and quality gates but did not "
        "run an atlas.",
    ]
    if request.units == "unitless":
        notices.insert(0, "Units are declared as unitless; confirm this is intentional.")
    if inputs.subject_count > 250:
        notices.append(
            "This is a large cohort; run a representative pilot and measure memory and "
            "runtime first."
        )
    return ProjectSetupResult(
        engine=DesktopEngine.MODERN_CPU,
        config_path=config_path,
        template_path=inputs.template,
        subject_count=inputs.subject_count,
        report_path=None,
        notices=tuple(notices),
    )


def create_project(request: ProjectSetupRequest) -> ProjectSetupResult:
    """Validate inputs and create one non-overwriting starter project."""

    normalized = _normalize_request(request)
    if normalized.project_directory.exists() and not normalized.project_directory.is_dir():
        raise ConfigurationError(
            f"Project directory path is not a directory: {normalized.project_directory}"
        )
    if normalized.engine is DesktopEngine.MODERN_CPU:
        return _create_modern_project(normalized)
    return _create_reference_project(normalized)

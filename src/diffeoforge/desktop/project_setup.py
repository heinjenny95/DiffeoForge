"""Qt-independent application service for the first desktop project slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from diffeoforge.config import ConfigurationError, validate_input_paths
from diffeoforge.initialization import (
    SUPPORTED_UNITS,
    ensure_generated_configuration_replaceable,
    initialize_project,
)
from diffeoforge.reference_runtime import (
    MANAGED_WSL_DISTRIBUTION,
    launcher_label,
    select_preferred_reference_launcher,
)
from diffeoforge.report import (
    default_preflight_report_path,
    ensure_preflight_report_replaceable,
    write_preflight_report,
)


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
    pairwise_mode: str = "dense"
    query_tile_size: int | None = None
    source_tile_size: int | None = None
    max_cycles: int = 3
    overwrite_existing_configuration: bool = False


@dataclass(frozen=True)
class ProjectSetupResult:
    """User-facing evidence returned after project creation succeeds."""

    engine: DesktopEngine
    config_path: Path
    template_path: Path
    subject_count: int
    report_path: Path | None
    notices: tuple[str, ...]
    preprocessing_report_path: Path | None = None

    @property
    def engine_label(self) -> str:
        """Return a stable label suitable for the desktop result summary."""

        if self.engine is DesktopEngine.MODERN_CPU:
            return "DiffeoForge Modern CPU (experimental)"
        return "Deformetrica 4.3 (recommended backend)"


def _normalize_request(request: ProjectSetupRequest) -> ProjectSetupRequest:
    if not isinstance(request, ProjectSetupRequest):
        raise TypeError("request must be a ProjectSetupRequest")
    try:
        engine = DesktopEngine(request.engine)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"Unsupported desktop engine: {request.engine!r}") from error
    if request.units not in SUPPORTED_UNITS:
        raise ConfigurationError(f"Unsupported coordinate unit: {request.units!r}")
    if not isinstance(request.overwrite_existing_configuration, bool):
        raise ConfigurationError("overwrite_existing_configuration must be a boolean")
    pattern = request.subject_pattern.strip()
    if not pattern:
        raise ConfigurationError("Subject filename pattern must not be empty")
    name = request.project_name.strip() if request.project_name else None
    pairwise_mode = str(request.pairwise_mode).strip().lower()
    if pairwise_mode not in {"dense", "blockwise"}:
        raise ConfigurationError("pairwise_mode must be 'dense' or 'blockwise'")
    if pairwise_mode == "dense":
        if request.query_tile_size is not None or request.source_tile_size is not None:
            raise ConfigurationError("Dense pairwise evaluation requires null tile sizes")
        query_tile_size = None
        source_tile_size = None
    else:
        normalized_tiles: list[int] = []
        for label, value in (
            ("query_tile_size", request.query_tile_size),
            ("source_tile_size", request.source_tile_size),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigurationError(
                    f"Blockwise pairwise evaluation requires a positive integer {label}"
                )
            normalized_tiles.append(value)
        query_tile_size, source_tile_size = normalized_tiles
    if engine is DesktopEngine.DEFORMETRICA_REFERENCE and pairwise_mode != "dense":
        raise ConfigurationError(
            "Pairwise execution plans are available only for the modern CPU workflow"
        )
    if (
        isinstance(request.max_cycles, bool)
        or not isinstance(request.max_cycles, int)
        or request.max_cycles < 1
    ):
        raise ConfigurationError("Desktop max_cycles must be a positive integer")
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
        pairwise_mode=pairwise_mode,
        query_tile_size=query_tile_size,
        source_tile_size=source_tile_size,
        max_cycles=request.max_cycles,
        overwrite_existing_configuration=request.overwrite_existing_configuration,
    )


def _create_reference_project(request: ProjectSetupRequest) -> ProjectSetupResult:
    config_path = request.project_directory / "atlas.yaml"
    report_path = default_preflight_report_path(config_path)
    ensure_generated_configuration_replaceable(
        config_path,
        overwrite=request.overwrite_existing_configuration,
    )
    if report_path.exists() and not request.overwrite_existing_configuration:
        raise ConfigurationError(
            f"Preflight report already exists and will not be overwritten: {report_path}"
        )
    if report_path.exists() and request.overwrite_existing_configuration:
        ensure_preflight_report_replaceable(report_path)

    input_directory = request.mesh_directory
    input_template = request.template
    preprocessing_report_path: Path | None = None
    effective_project_name = request.project_name
    if request.landmarks_file is not None:
        try:
            from diffeoforge.preprocessing import prepare_landmark_aligned_inputs
        except ImportError as error:
            raise ConfigurationError(
                "Landmark Procrustes dependencies are missing; install diffeoforge[analysis]."
            ) from error
        aligned = prepare_landmark_aligned_inputs(
            request.mesh_directory,
            project_directory=request.project_directory,
            landmarks_file=request.landmarks_file,
            template=request.template,
            subject_pattern=request.subject_pattern,
        )
        input_directory = aligned.directory
        input_template = aligned.template
        preprocessing_report_path = aligned.evidence
        if effective_project_name is None:
            source = request.mesh_directory
            name_source = (
                source.parent.name
                if source.name.casefold() in {"mesh", "meshes", "data"}
                else source.name
            )
            effective_project_name = f"{name_source}-atlas"
    launcher = select_preferred_reference_launcher()
    initialized = initialize_project(
        input_directory,
        units=request.units,
        config_path=config_path,
        template=input_template,
        subject_pattern=request.subject_pattern,
        project_name=effective_project_name,
        launcher=launcher,
        overwrite=request.overwrite_existing_configuration,
    )
    write_preflight_report(
        initialized.preflight,
        report_path,
        overwrite=request.overwrite_existing_configuration,
    )
    notices = list(initialized.preflight.notices)
    notices.insert(0, f"Reference runtime: {launcher_label(launcher)}.")
    if (
        launcher.get("type") == "wsl"
        and launcher.get("distribution") != MANAGED_WSL_DISTRIBUTION
    ):
        notices.insert(
            1,
            "This same-owner alpha project reuses an existing verified Deformetrica 4.3 "
            "runtime read-only; released installers will use a separate DiffeoForge-managed "
            "runtime.",
        )
    if initialized.derived_parameters:
        notices.insert(
            0,
            "Geometry-scaled starter values are exploratory and require scientific review.",
        )
    if preprocessing_report_path is not None:
        notices.insert(
            0,
            "Homologous landmarks were validated and generalized Procrustes was applied "
            "to immutable aligned mesh copies. Raw meshes were not modified.",
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
        preprocessing_report_path=preprocessing_report_path,
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
        pairwise_mode=request.pairwise_mode,
        query_tile_size=request.query_tile_size,
        source_tile_size=request.source_tile_size,
        max_cycles=request.max_cycles,
        overwrite=request.overwrite_existing_configuration,
    )
    config = load_modern_workflow_config(config_path)
    inputs = validate_input_paths(config, config_path)
    notices = [
        "Geometry-scaled starter values are exploratory and require scientific review.",
        "Project creation validated the supported meshes and quality gates but did not "
        "run an atlas.",
    ]
    if request.max_cycles <= 3:
        notices.insert(
            0,
            "The selected three-cycle optimizer cap is a technical pilot, not a "
            "convergence attempt.",
        )
    else:
        notices.insert(
            0,
            f"The selected {request.max_cycles}-cycle convergence attempt stops earlier if the "
            "gradient tolerance is reached; the longer cap does not guarantee convergence.",
        )
    if request.units == "unitless":
        notices.insert(0, "Units are declared as unitless; confirm this is intentional.")
    if request.overwrite_existing_configuration:
        notices.append(
            "The previous generated configuration was replaced after explicit confirmation. "
            "Any generated workload report will be refreshed during parameter review; source "
            "meshes and completed run directories were not modified."
        )
    if request.pairwise_mode == "blockwise":
        notices.append(
            "Exact blockwise pairwise evaluation is enabled with explicit "
            f"{request.query_tile_size} × {request.source_tile_size} tiles. This bounds one "
            "pairwise XYZ allocation, not total RAM or runtime; benchmark representative "
            "meshes before a production run."
        )
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
        preprocessing_report_path=None,
        notices=tuple(notices),
    )


def create_project(request: ProjectSetupRequest) -> ProjectSetupResult:
    """Validate inputs and create or explicitly replace one generated starter project."""

    normalized = _normalize_request(request)
    if normalized.project_directory.exists() and not normalized.project_directory.is_dir():
        raise ConfigurationError(
            f"Project directory path is not a directory: {normalized.project_directory}"
        )
    if normalized.engine is DesktopEngine.MODERN_CPU:
        return _create_modern_project(normalized)
    return _create_reference_project(normalized)

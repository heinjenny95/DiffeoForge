"""Load and validate the draft atlas configuration contract."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


class ConfigurationError(ValueError):
    """Raised when configuration or referenced inputs fail preflight checks."""


@dataclass(frozen=True)
class InputSummary:
    """Resolved input paths returned by the lightweight preflight check."""

    input_directory: Path
    template: Path
    subject_count: int
    subjects: tuple[Path, ...]
    initial_control_points: Path | None = None
    initial_momenta: Path | None = None
    cohort_template: Path | None = None


def _schema() -> Mapping[str, Any]:
    schema_file = files("diffeoforge.schema").joinpath("atlas-config-v0.1.json")
    return json.loads(schema_file.read_text(encoding="utf-8"))


def _format_schema_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def validate_schema(config: Mapping[str, Any]) -> None:
    """Validate a configuration mapping against the bundled JSON Schema."""

    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(config), key=lambda error: list(error.absolute_path))
    if errors:
        details = "\n  - ".join(_format_schema_error(error) for error in errors)
        raise ConfigurationError(f"Configuration schema validation failed:\n  - {details}")


def load_config(path: Path | str) -> Mapping[str, Any]:
    """Load YAML from *path* and validate its structure."""

    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {config_path}")

    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ConfigurationError(f"Could not read YAML configuration: {error}") from error

    if not isinstance(loaded, dict):
        raise ConfigurationError("Configuration root must be a YAML mapping.")

    validate_schema(loaded)
    return loaded


def _resolve_from_config(value: str, config_path: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.resolve().parent / candidate
    return candidate.resolve()


def resolve_output_directory(config: Mapping[str, Any], config_path: Path | str) -> Path:
    """Resolve the configured run root relative to the configuration file."""

    return _resolve_from_config(config["output"]["directory"], Path(config_path))


def _pilot_cohort_template(
    config: Mapping[str, Any], directory: Path, template: Path, controls: Path | None
) -> Path | None:
    """Identify the original cohort template separately from a learned pilot seed."""

    recommendation = config.get("project", {}).get("parameter_provenance", {}).get(
        "recommendation", {}
    )
    initialization = recommendation.get("calibration_result", {}).get(
        "full_cohort_initialization"
    )
    if not initialization:
        return None
    plan = recommendation.get("calibration_plan", {})
    name = plan.get("template_filename")
    if (
        not isinstance(name, str) or not name or name in {".", ".."}
        or "/" in name or "\\" in name or Path(name).name != name
    ):
        raise ConfigurationError("Calibrated cohort template filename is unsafe or absent.")
    original = directory / name
    # A separately staged probe/holdout does not contain the original full cohort.
    # Its explicit cohort remains authoritative; do not apply full-cohort exclusions.
    if not original.exists():
        return None
    if original.is_symlink() or not original.is_file():
        raise ConfigurationError("Calibrated cohort template is not a regular file.")

    def digest(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    try:
        if digest(original) != plan.get("template_sha256"):
            raise ConfigurationError("Original cohort template no longer matches pilot evidence.")
        if (
            initialization.get("method") not in {
                "learned_pilot_template_and_controls_zero_full_cohort_momenta",
                "preserved_pilot_momenta_fixed_basis_initialization",
            }
            or template.is_symlink()
            or digest(template) != initialization.get("template_sha256")
            or controls is None
            or controls.is_symlink()
            or digest(controls) != initialization.get("control_points_sha256")
        ):
            raise ConfigurationError("Learned full-cohort seed no longer matches pilot evidence.")
    except OSError as error:
        raise ConfigurationError(
            f"Could not verify pilot cohort initialization: {error}"
        ) from error
    return original.resolve()


def validate_input_paths(config: Mapping[str, Any], config_path: Path | str) -> InputSummary:
    """Resolve the template and subject glob without parsing mesh geometry yet."""

    source_path = Path(config_path)
    input_config = config["input"]
    input_directory = _resolve_from_config(input_config["directory"], source_path)
    template = _resolve_from_config(input_config["template"], source_path)
    control_points_value = config["model"]["deformation"].get("initial_control_points")
    initial_control_points = (
        None
        if control_points_value is None
        else _resolve_from_config(str(control_points_value), source_path)
    )
    momenta_value = config["model"]["deformation"].get("initial_momenta")
    initial_momenta = (
        None if momenta_value is None else _resolve_from_config(str(momenta_value), source_path)
    )

    if not input_directory.is_dir():
        raise ConfigurationError(f"Input directory does not exist: {input_directory}")
    if not template.is_file():
        raise ConfigurationError(f"Template mesh does not exist: {template}")
    if template.suffix.lower() != ".vtk":
        raise ConfigurationError(f"Template must be a VTK file: {template}")
    if initial_control_points is not None:
        if not initial_control_points.is_file():
            raise ConfigurationError(
                f"Initial control-points file does not exist: {initial_control_points}"
            )
        if initial_control_points.suffix.lower() != ".txt":
            raise ConfigurationError(
                f"Initial control points must be a Deformetrica TXT file: {initial_control_points}"
            )
        if initial_control_points.stat().st_size < 1:
            raise ConfigurationError(
                f"Initial control-points file is empty: {initial_control_points}"
            )

    pattern = input_config["subject_pattern"]
    try:
        candidates = sorted(
            path.resolve() for path in input_directory.glob(pattern) if path.is_file()
        )
    except (OSError, ValueError) as error:
        raise ConfigurationError(f"Invalid subject pattern {pattern!r}: {error}") from error

    outside = [path for path in candidates if not path.is_relative_to(input_directory)]
    if outside:
        raise ConfigurationError(
            "Subject pattern must not select files outside the input directory."
        )

    cohort_template = _pilot_cohort_template(
        config, input_directory, template, initial_control_points
    )
    subjects = tuple(
        path for path in candidates
        if path not in {template, cohort_template} and path.suffix.lower() == ".vtk"
    )
    if cohort_template is not None:
        plan = config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"]
        if len(subjects) != plan.get("subject_count"):
            raise ConfigurationError("Full-cohort subject count differs from the saved pilot plan.")
    if not subjects:
        raise ConfigurationError(f"No subject VTK files match {pattern!r} in {input_directory}.")
    probe = (
        config.get("project", {})
        .get("parameter_provenance", {})
        .get("recommendation", {})
        .get("calibration_plan", {})
        .get("execution_scope")
        == "single_specimen_probe"
    )
    fixed_probe = (
        probe
        and config["optimization"]["freeze_template"]
        and config["optimization"]["freeze_control_points"]
    )
    if len(subjects) < 2 and not fixed_probe:
        raise ConfigurationError("Atlas estimation requires at least two subject meshes.")
    if len(set(subjects)) != len(subjects):
        raise ConfigurationError("Subject file selection contains duplicate paths.")
    names = [path.name.casefold() for path in subjects]
    if len(set(names)) != len(names):
        raise ConfigurationError(
            "Subject mesh filenames must be unique when compared case-insensitively."
        )

    if initial_momenta is not None:
        deformation = config["model"]["deformation"]
        if initial_control_points is None:
            raise ConfigurationError("Initial momenta require explicit matching control points.")
        if deformation.get("initial_momenta_subjects") != [p.name for p in subjects]:
            raise ConfigurationError("Initial momenta subject order must match the input cohort.")
        try:
            controls = [
                line.split()
                for line in initial_control_points.read_text().splitlines()
                if line.strip()
            ]
            lines = initial_momenta.read_text(encoding="utf-8").splitlines()
            shape = tuple(int(value) for value in lines[0].split())
            values = [float(value) for line in lines[1:] for value in line.split()]
            if (
                not controls
                or any(len(row) != 3 for row in controls)
                or any(not math.isfinite(float(value)) for row in controls for value in row)
                or shape != (len(subjects), len(controls), 3)
                or len(values) != math.prod(shape)
                or not all(math.isfinite(value) for value in values)
            ):
                raise ValueError("dimensions or finite values do not match the cohort and controls")
        except (OSError, UnicodeError, ValueError, IndexError) as error:
            raise ConfigurationError(f"Invalid initial momenta: {error}") from error

    from diffeoforge.reference_atlas_handoff import initialization

    handoff = initialization(config)
    if handoff:
        if (
            initial_momenta is None
            or hashlib.sha256(initial_momenta.read_bytes()).hexdigest()
            != handoff["initial_momenta_sha256"]
            or handoff["subject_labels"] != [p.name for p in subjects]
        ):
            raise ConfigurationError(
                "Preserved pilot initial momenta or subject identities changed."
            )

    return InputSummary(
        input_directory=input_directory,
        template=template,
        subject_count=len(subjects),
        subjects=subjects,
        initial_control_points=initial_control_points,
        initial_momenta=initial_momenta,
        cohort_template=cohort_template,
    )

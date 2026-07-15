"""Load and validate the draft atlas configuration contract."""

from __future__ import annotations

import json
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


def validate_input_paths(config: Mapping[str, Any], config_path: Path | str) -> InputSummary:
    """Resolve the template and subject glob without parsing mesh geometry yet."""

    source_path = Path(config_path)
    input_config = config["input"]
    input_directory = _resolve_from_config(input_config["directory"], source_path)
    template = _resolve_from_config(input_config["template"], source_path)

    if not input_directory.is_dir():
        raise ConfigurationError(f"Input directory does not exist: {input_directory}")
    if not template.is_file():
        raise ConfigurationError(f"Template mesh does not exist: {template}")
    if template.suffix.lower() != ".vtk":
        raise ConfigurationError(f"Template must be a VTK file: {template}")

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

    subjects = tuple(
        path for path in candidates if path != template and path.suffix.lower() == ".vtk"
    )
    if not subjects:
        raise ConfigurationError(
            f"No subject VTK files match {pattern!r} in {input_directory}."
        )
    if len(set(subjects)) != len(subjects):
        raise ConfigurationError("Subject file selection contains duplicate paths.")

    return InputSummary(
        input_directory=input_directory,
        template=template,
        subject_count=len(subjects),
        subjects=subjects,
    )

"""Read-only exact plan for one future immutable reference-run preparation."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from collections.abc import Mapping
from importlib.resources import files
from io import StringIO
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from diffeoforge import __version__
from diffeoforge.backends import (
    BACKEND_CONTRACT_VERSION,
    BACKEND_ID,
    ENGINE_CONSTANTS,
    build_command,
    render_engine_file_bytes,
    validate_reference_config,
)
from diffeoforge.config import (
    ConfigurationError,
    load_config,
    resolve_output_directory,
    validate_input_paths,
)
from diffeoforge.mesh import inspect_inputs, sha256_file
from diffeoforge.runs import (
    effective_reference_config,
    normalize_run_id,
    reference_input_record,
)

SCHEMA_VERSION = "0.1"
STATUS = "read_only_plan_not_prepared"
SCIENTIFIC_BOUNDARY = (
    "This deterministic plan describes bytes and paths that DiffeoForge would use for "
    "one immutable Deformetrica reference-run preparation. It creates no directory, "
    "copies no mesh, launches no process, and does not validate parameter choice, "
    "registration quality, numerical convergence, or biological interpretation."
)
PLANNED_DIRECTORIES = (
    "config",
    "engine",
    "input/template",
    "input/subjects",
    "logs",
    "output",
)


def _schema() -> Mapping[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "reference-preparation-plan-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_plan(plan: Mapping[str, Any]) -> None:
    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(plan), key=lambda error: list(error.path))
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.path) or "<root>"
    raise ConfigurationError(
        f"Reference preparation plan schema violation at {location}: {first.message}"
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _copied_file(path: str, source: Path, payload_bytes: int, sha256: str) -> dict:
    return {
        "kind": "copied",
        "path": path,
        "source_path": str(source),
        "bytes": payload_bytes,
        "sha256": sha256,
    }


def _generated_file(path: str, payload: bytes) -> dict:
    return {
        "kind": "generated",
        "path": path,
        "bytes": len(payload),
        "sha256": _sha256_bytes(payload),
        "content_utf8": payload.decode("utf-8"),
    }


def _effective_yaml_bytes(effective: Mapping[str, Any]) -> bytes:
    stream = StringIO(newline="\n")
    yaml.safe_dump(
        dict(effective),
        stream,
        sort_keys=False,
        allow_unicode=True,
    )
    return stream.getvalue().encode("utf-8")


def _verify_unchanged(path: Path, expected_sha256: str, label: str) -> None:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ConfigurationError(f"{label} changed while the preparation plan was built: {path}")


def plan_reference_preparation(
    config_path: Path | str,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Describe exact preparation bytes and paths without creating anything."""

    source_config = Path(config_path).expanduser().resolve()
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be an explicit nonempty string")
    source_config_bytes = source_config.read_bytes()
    source_config_sha256 = _sha256_bytes(source_config_bytes)
    config = load_config(source_config)
    validate_reference_config(config)
    summary = validate_input_paths(config, source_config)
    template_metadata, subject_metadata = inspect_inputs(summary)
    output_root = resolve_output_directory(config, source_config)
    if output_root.exists() and not output_root.is_dir():
        raise ConfigurationError(f"Configured output root is not a directory: {output_root}")
    resolved_run_id = normalize_run_id(run_id)
    destination = (output_root / resolved_run_id).resolve()
    if destination.exists():
        raise ConfigurationError(f"Run directory already exists: {destination}")

    staged_template_relative = Path("input") / "template" / summary.template.name
    staged_subject_relatives = [
        Path("input") / "subjects" / subject.name for subject in summary.subjects
    ]
    inputs = [
        reference_input_record(
            "template",
            summary.template,
            staged_template_relative,
            template_metadata,
        ),
        *(
            reference_input_record("subject", source, staged, metadata)
            for source, staged, metadata in zip(
                summary.subjects,
                staged_subject_relatives,
                subject_metadata,
                strict=True,
            )
        ),
    ]
    effective = effective_reference_config(
        config,
        summary.input_directory,
        summary.template,
        output_root,
    )
    effective_bytes = _effective_yaml_bytes(effective)
    engine_bytes = render_engine_file_bytes(
        config,
        Path("..") / staged_template_relative,
        [Path("..") / path for path in staged_subject_relatives],
    )
    protected_files = [
        _copied_file(
            "config/source-config.yaml",
            source_config,
            len(source_config_bytes),
            source_config_sha256,
        ),
        _generated_file("config/effective-config.yaml", effective_bytes),
        _copied_file(
            staged_template_relative.as_posix(),
            summary.template,
            template_metadata.bytes,
            template_metadata.sha256,
        ),
        *(
            _copied_file(
                staged.as_posix(),
                source,
                metadata.bytes,
                metadata.sha256,
            )
            for source, staged, metadata in zip(
                summary.subjects,
                staged_subject_relatives,
                subject_metadata,
                strict=True,
            )
        ),
        *(
            _generated_file(f"engine/{name}", payload)
            for name, payload in engine_bytes.items()
        ),
    ]
    plan = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "source_config": {
            "path": str(source_config),
            "bytes": len(source_config_bytes),
            "sha256": source_config_sha256,
        },
        "run": {
            "run_id": resolved_run_id,
            "output_root": str(output_root),
            "destination": str(destination),
            "destination_exists": False,
        },
        "backend": {
            "id": BACKEND_ID,
            "contract_version": BACKEND_CONTRACT_VERSION,
            "engine_constants": ENGINE_CONSTANTS,
        },
        "planner": {
            "diffeoforge": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "native_newline": "CRLF" if os.linesep == "\r\n" else "LF",
        },
        "directories": list(PLANNED_DIRECTORIES),
        "input_count": {"templates": 1, "subjects": len(summary.subjects)},
        "inputs": inputs,
        "effective_config": effective,
        "protected_files": protected_files,
        "protected_file_count": len(protected_files),
        "total_protected_bytes": sum(int(item["bytes"]) for item in protected_files),
        "command_preview": build_command(config, destination).as_manifest(),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _validate_plan(plan)
    _verify_unchanged(source_config, source_config_sha256, "Configuration")
    current_summary = validate_input_paths(config, source_config)
    if (
        current_summary.input_directory != summary.input_directory
        or current_summary.template != summary.template
        or current_summary.subjects != summary.subjects
    ):
        raise ConfigurationError(
            "Reference input inventory changed while the preparation plan was built"
        )
    for item in inputs:
        geometry = item["geometry"]
        _verify_unchanged(Path(item["source_path"]), str(geometry["sha256"]), "Input mesh")
    if resolve_output_directory(config, source_config) != output_root:
        raise ConfigurationError(
            "Configured output root changed while the preparation plan was built"
        )
    if destination.exists():
        raise ConfigurationError(
            f"Run directory appeared while the preparation plan was built: {destination}"
        )
    return plan

"""Numerical comparison against versioned DiffeoForge reference fixtures."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import inspect_vtk, read_vtk_points, sha256_file


@dataclass(frozen=True)
class NumericArtifact:
    """Parsed numeric values plus a structure signature."""

    signature: Mapping[str, object]
    values: tuple[float, ...]


def _schema() -> Mapping[str, Any]:
    schema_file = files("diffeoforge.schema").joinpath("reference-manifest-v0.1.json")
    return json.loads(schema_file.read_text(encoding="utf-8"))


def _format_schema_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def load_reference_manifest(reference_directory: Path | str) -> Mapping[str, Any]:
    """Load and validate one reference suite manifest."""

    root = Path(reference_directory).resolve()
    manifest_path = root / "reference-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"Could not read reference manifest: {error}") from error

    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.absolute_path))
    if errors:
        details = "\n  - ".join(_format_schema_error(error) for error in errors)
        raise ConfigurationError(f"Reference manifest validation failed:\n  - {details}")

    identifiers = [artifact["id"] for artifact in manifest["artifacts"]]
    fixture_paths = [artifact["fixture_path"] for artifact in manifest["artifacts"]]
    run_paths = [artifact["run_path"] for artifact in manifest["artifacts"]]
    if len(identifiers) != len(set(identifiers)):
        raise ConfigurationError("Reference artifact identifiers must be unique.")
    if len(fixture_paths) != len(set(fixture_paths)):
        raise ConfigurationError("Reference fixture paths must be unique.")
    if len(run_paths) != len(set(run_paths)):
        raise ConfigurationError("Reference run paths must be unique.")
    return manifest


def _resolve_file(root: Path, relative_path: str, label: str) -> Path:
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ConfigurationError(f"{label} path escapes its root: {relative_path}")
    if not path.is_file():
        raise ConfigurationError(f"{label} file does not exist: {path}")
    return path


def _finite_values(tokens: list[str], path: Path) -> tuple[float, ...]:
    try:
        values = tuple(float(token) for token in tokens)
    except ValueError as error:
        raise ConfigurationError(
            f"Numeric reference artifact contains invalid data: {path}"
        ) from error
    if not values or any(not math.isfinite(value) for value in values):
        raise ConfigurationError(f"Numeric reference artifact contains no finite values: {path}")
    return values


def _read_numeric_text(path: Path) -> NumericArtifact:
    try:
        tokens = path.read_text(encoding="utf-8").split()
    except (OSError, UnicodeError) as error:
        raise ConfigurationError(f"Could not read numeric artifact {path}: {error}") from error
    values = _finite_values(tokens, path)
    return NumericArtifact(signature={"values": len(values)}, values=values)


def _read_numeric_csv(path: Path) -> NumericArtifact:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ConfigurationError(f"Could not read numeric CSV {path}: {error}") from error
    if len(rows) < 2 or not rows[0]:
        raise ConfigurationError(f"Numeric CSV has no header or data rows: {path}")

    header = tuple(rows[0])
    if any(len(row) != len(header) for row in rows[1:]):
        raise ConfigurationError(f"Numeric CSV has inconsistent row widths: {path}")
    values = _finite_values([token for row in rows[1:] for token in row], path)
    return NumericArtifact(
        signature={"header": list(header), "rows": len(rows) - 1, "columns": len(header)},
        values=values,
    )


def _read_vtk_coordinates(path: Path) -> NumericArtifact:
    metadata = inspect_vtk(path)
    points = read_vtk_points(path)
    return NumericArtifact(
        signature={"points": metadata.points, "cells": metadata.cells},
        values=tuple(value for point in points for value in point),
    )


def _read_artifact(path: Path, kind: str) -> NumericArtifact:
    readers = {
        "numeric_csv": _read_numeric_csv,
        "numeric_text": _read_numeric_text,
        "vtk_points": _read_vtk_coordinates,
    }
    return readers[kind](path)


def compare_reference_run(
    run_directory: Path | str, reference_directory: Path | str
) -> dict[str, object]:
    """Compare selected run artifacts with a versioned numerical reference."""

    run_root = Path(run_directory).resolve()
    reference_root = Path(reference_directory).resolve()
    if not run_root.is_dir():
        raise ConfigurationError(f"Run directory does not exist: {run_root}")
    if not reference_root.is_dir():
        raise ConfigurationError(f"Reference directory does not exist: {reference_root}")

    manifest = load_reference_manifest(reference_root)
    results = []
    for specification in manifest["artifacts"]:
        fixture_path = _resolve_file(
            reference_root, specification["fixture_path"], "Reference fixture"
        )
        candidate_path = _resolve_file(run_root, specification["run_path"], "Run artifact")
        fixture_hash = sha256_file(fixture_path)
        if fixture_hash != specification["sha256"]:
            raise ConfigurationError(
                f"Reference fixture checksum mismatch for {specification['id']}: {fixture_path}"
            )

        fixture = _read_artifact(fixture_path, specification["kind"])
        candidate = _read_artifact(candidate_path, specification["kind"])
        shape_matches = fixture.signature == candidate.signature
        if shape_matches and len(fixture.values) == len(candidate.values):
            differences = tuple(
                abs(reference - observed)
                for reference, observed in zip(fixture.values, candidate.values, strict=True)
            )
            maximum = max(differences, default=0.0)
            rms = math.sqrt(sum(value * value for value in differences) / len(differences))
        else:
            maximum = None
            rms = None

        tolerances = specification["tolerances"]
        passed = (
            shape_matches
            and maximum is not None
            and rms is not None
            and maximum <= tolerances["max_absolute"]
            and rms <= tolerances["rms"]
        )
        results.append(
            {
                "id": specification["id"],
                "kind": specification["kind"],
                "passed": passed,
                "byte_identical": sha256_file(candidate_path) == fixture_hash,
                "shape_matches": shape_matches,
                "reference_shape": fixture.signature,
                "candidate_shape": candidate.signature,
                "value_count": len(fixture.values),
                "max_absolute_difference": maximum,
                "rms_difference": rms,
                "tolerances": tolerances,
            }
        )

    passed_count = sum(bool(result["passed"]) for result in results)
    return {
        "reference_id": manifest["id"],
        "reference_version": manifest["reference_version"],
        "status": "passed" if passed_count == len(results) else "failed",
        "artifact_count": len(results),
        "passed_count": passed_count,
        "artifacts": results,
    }

"""Verified linear PCA of Deformetrica deterministic-atlas momenta."""

from __future__ import annotations

import csv
import json
import math
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema
import numpy as np

from diffeoforge.analysis.pca import PCAResult, momenta_pca
from diffeoforge.analysis.pca_artifacts import (
    pca_csv_label,
    pca_float,
    pca_loading_rows,
    pca_mean_rows,
    pca_score_rows,
    pca_summary_document,
    write_pca_artifacts,
)
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.result_report import RunReport, collect_run_report
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

REFERENCE_PCA_BUNDLE_VERSION = "0.1"
REFERENCE_PCA_MANIFEST = "reference-pca-manifest.json"
REFERENCE_PCA_SIDECAR = "reference-pca-manifest.sha256"
DEFAULT_REFERENCE_PCA_DIRECTORY = Path("analysis") / "reference-momenta-pca"
MOMENTA_SUFFIX = "__EstimatedParameters__Momenta.txt"
CONTROL_POINTS_SUFFIX = "__EstimatedParameters__ControlPoints.txt"
MAX_MOMENTA_VALUES = 100_000_000
SUBJECT_IDENTITY_SOURCE = "run manifest subject inputs in stored Deformetrica XML order"
FEATURE_ORDER = "subject outer; control point middle; Cartesian x, y, z inner"
SCIENTIFIC_BOUNDARY = (
    "Linear PCA is computed from Deformetrica subject initial momenta in the exact stored "
    "control-point/Cartesian order. It is an exploratory coordinate summary, not proof of "
    "group separation, biological effect, adequate registration, convergence, or causal "
    "interpretation. Component signs are conventional."
)


class ReferencePCAError(RuntimeError):
    """Raised when reference momenta or their derived PCA evidence are invalid."""


@dataclass(frozen=True)
class ReferenceMomentaInput:
    run_directory: Path
    run_report: RunReport
    momenta_path: Path
    control_points_path: Path
    momenta_record: Mapping[str, Any]
    control_points_record: Mapping[str, Any]
    subject_labels: tuple[str, ...]
    momenta: np.ndarray
    control_points: np.ndarray

    def __post_init__(self) -> None:
        for name in ("momenta", "control_points"):
            values = np.array(getattr(self, name), dtype=np.float64, copy=True)
            values.setflags(write=False)
            object.__setattr__(self, name, values)

    @property
    def subject_count(self) -> int:
        return self.momenta.shape[0]

    @property
    def control_point_count(self) -> int:
        return self.momenta.shape[1]


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath("reference-pca-bundle-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_manifest(value: Mapping[str, Any]) -> None:
    try:
        json.dumps(dict(value), allow_nan=False)
        jsonschema.Draft202012Validator(_schema()).validate(dict(value))
    except (TypeError, ValueError, jsonschema.ValidationError) as error:
        if isinstance(error, jsonschema.ValidationError):
            location = ".".join(str(part) for part in error.absolute_path) or "document"
            detail = f" at {location}: {error.message}"
        else:
            detail = f": {error}"
        raise ReferencePCAError(f"Reference PCA manifest is invalid{detail}") from error
    try:
        parsed = datetime.fromisoformat(str(value["created_at"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ReferencePCAError("Reference PCA created_at is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise ReferencePCAError("Reference PCA created_at must contain a timezone offset")


def _positive_header_integer(value: str, label: str) -> int:
    if not value.isdecimal():
        raise ReferencePCAError(f"Deformetrica momenta {label} must be a positive integer")
    normalized = int(value)
    if normalized < 1:
        raise ReferencePCAError(f"Deformetrica momenta {label} must be positive")
    return normalized


def read_deformetrica_momenta(path: Path | str) -> np.ndarray:
    """Strictly read the Deformetrica header plus row-major subject momenta blocks."""

    source = Path(path).expanduser().resolve()
    try:
        handle = source.open("r", encoding="utf-8", errors="strict", newline=None)
    except OSError as error:
        raise ReferencePCAError(
            f"Could not open Deformetrica momenta: {source}: {error}"
        ) from error
    with handle:
        header = handle.readline()
        fields = header.split()
        if len(fields) != 3:
            raise ReferencePCAError(
                "Deformetrica momenta header must contain subjects, control points, dimension"
            )
        subjects = _positive_header_integer(fields[0], "subject count")
        control_points = _positive_header_integer(fields[1], "control-point count")
        dimension = _positive_header_integer(fields[2], "dimension")
        if subjects < 2:
            raise ReferencePCAError("Momenta PCA requires at least two subjects")
        if dimension != 3:
            raise ReferencePCAError(
                f"Only three-dimensional Deformetrica momenta are supported, observed {dimension}"
            )
        expected_rows = subjects * control_points
        if expected_rows * dimension > MAX_MOMENTA_VALUES:
            raise ReferencePCAError(
                "Deformetrica momenta dimensions exceed the guarded in-memory import limit"
            )
        values = np.empty((expected_rows, dimension), dtype=np.float64)
        observed_rows = 0
        for line_number, line in enumerate(handle, start=2):
            if not line.strip():
                continue
            if observed_rows >= expected_rows:
                raise ReferencePCAError(
                    f"Deformetrica momenta contains extra numeric row at line {line_number}"
                )
            components = line.split()
            if len(components) != dimension:
                raise ReferencePCAError(
                    f"Deformetrica momenta line {line_number} must contain {dimension} values"
                )
            try:
                row = tuple(float(component) for component in components)
            except ValueError as error:
                raise ReferencePCAError(
                    f"Deformetrica momenta line {line_number} contains a non-number"
                ) from error
            if not all(math.isfinite(component) for component in row):
                raise ReferencePCAError(
                    f"Deformetrica momenta line {line_number} contains a non-finite value"
                )
            values[observed_rows] = row
            observed_rows += 1
    if observed_rows != expected_rows:
        raise ReferencePCAError(
            f"Deformetrica momenta declares {expected_rows} rows but contains {observed_rows}"
        )
    return values.reshape(subjects, control_points, dimension)


def read_deformetrica_control_points(
    path: Path | str,
    *,
    expected_count: int,
) -> np.ndarray:
    source = Path(path).expanduser().resolve()
    if isinstance(expected_count, bool) or not isinstance(expected_count, int):
        raise TypeError("expected_count must be an integer")
    if expected_count < 1:
        raise ValueError("expected_count must be positive")
    rows: list[tuple[float, float, float]] = []
    try:
        handle = source.open("r", encoding="utf-8", errors="strict", newline=None)
    except OSError as error:
        raise ReferencePCAError(f"Could not open Deformetrica control points: {source}") from error
    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) != 3:
                raise ReferencePCAError(
                    f"Deformetrica control-point line {line_number} must contain three values"
                )
            try:
                row = tuple(float(field) for field in fields)
            except ValueError as error:
                raise ReferencePCAError(
                    f"Deformetrica control-point line {line_number} contains a non-number"
                ) from error
            if not all(math.isfinite(value) for value in row):
                raise ReferencePCAError(
                    f"Deformetrica control-point line {line_number} is non-finite"
                )
            rows.append((row[0], row[1], row[2]))
    if len(rows) != expected_count:
        raise ReferencePCAError(
            f"Momenta declares {expected_count} control points but the parameter file "
            f"contains {len(rows)}"
        )
    return np.asarray(rows, dtype=np.float64)


def _one_output_record(report: RunReport, suffix: str, label: str) -> Mapping[str, Any]:
    matches = tuple(
        record
        for record in report.inventory
        if PurePosixPath(str(record["path"])).name.endswith(suffix)
    )
    if len(matches) != 1:
        raise ReferencePCAError(
            f"Completed Deformetrica output must contain exactly one {label}; found {len(matches)}"
        )
    return matches[0]


def _output_path(run_directory: Path, record: Mapping[str, Any], label: str) -> Path:
    relative = PurePosixPath(str(record["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ReferencePCAError(f"{label} inventory path escapes the output directory")
    candidate = run_directory / "output" / Path(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReferencePCAError(f"{label} is missing or symbolic: {candidate}")
    return candidate.resolve()


def _subject_labels(report: RunReport) -> tuple[str, ...]:
    inputs = report.manifest.get("inputs")
    if not isinstance(inputs, list):
        raise ReferencePCAError("Run manifest does not contain ordered input records")
    labels = tuple(
        PurePosixPath(str(record["staged_path"])).name
        for record in inputs
        if isinstance(record, dict) and record.get("role") == "subject"
    )
    expected = int(report.manifest["input_count"]["subjects"])
    if len(labels) != expected or len(set(labels)) != len(labels):
        raise ReferencePCAError(
            "Run manifest subject labels are missing, duplicated, or differ from input_count"
        )
    return labels


def load_reference_momenta(run_directory: Path | str) -> ReferenceMomentaInput:
    """Reverify a completed reference run and load its exact momenta feature tensor."""

    run_path = Path(run_directory).expanduser().resolve()
    try:
        report = collect_run_report(run_path)
    except (ConfigurationError, OSError, TypeError, ValueError) as error:
        raise ReferencePCAError(f"Could not verify source Deformetrica run: {error}") from error
    if report.result.get("status") != "completed":
        raise ReferencePCAError("Reference PCA requires a completed Deformetrica run")
    failed = tuple(check.label for check in report.checks if check.status != "pass")
    if failed:
        raise ReferencePCAError("Source run evidence failed: " + ", ".join(failed))
    backend = report.manifest.get("backend")
    if not isinstance(backend, dict) or backend.get("id") != "deformetrica_reference":
        raise ReferencePCAError("Reference PCA requires a Deformetrica reference manifest")
    momenta_record = _one_output_record(report, MOMENTA_SUFFIX, "momenta parameter file")
    control_record = _one_output_record(
        report,
        CONTROL_POINTS_SUFFIX,
        "control-point parameter file",
    )
    momenta_path = _output_path(run_path, momenta_record, "Momenta parameter file")
    control_path = _output_path(run_path, control_record, "Control-point parameter file")
    momenta = read_deformetrica_momenta(momenta_path)
    labels = _subject_labels(report)
    if momenta.shape[0] != len(labels):
        raise ReferencePCAError(
            f"Momenta contains {momenta.shape[0]} subjects but the immutable run manifest "
            f"contains {len(labels)}"
        )
    control_points = read_deformetrica_control_points(
        control_path,
        expected_count=momenta.shape[1],
    )
    return ReferenceMomentaInput(
        run_directory=run_path,
        run_report=report,
        momenta_path=momenta_path,
        control_points_path=control_path,
        momenta_record=momenta_record,
        control_points_record=control_record,
        subject_labels=labels,
        momenta=momenta,
        control_points=control_points,
    )


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _write_csv_exclusive(path: Path, rows: Sequence[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)


def _artifact(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _source_artifact(
    record: Mapping[str, Any],
    copied_path: str,
) -> dict[str, object]:
    return {
        "source_path": f"output/{record['path']}",
        "copied_path": copied_path,
        "bytes": int(record["bytes"]),
        "sha256": str(record["sha256"]),
    }


def _parameter_tables(root: Path, inputs: ReferenceMomentaInput) -> None:
    control_rows = [["control_point", "x", "y", "z"]] + [
        [str(index), *(pca_float(value) for value in point)]
        for index, point in enumerate(inputs.control_points)
    ]
    _write_csv_exclusive(root / "parameters" / "control-points.csv", control_rows)
    momenta_rows: list[list[str]] = [["subject_label", "control_point", "x", "y", "z"]]
    for label, subject_momenta in zip(
        inputs.subject_labels,
        inputs.momenta,
        strict=True,
    ):
        momenta_rows.extend(
            [pca_csv_label(label), str(index), *(pca_float(value) for value in point)]
            for index, point in enumerate(subject_momenta)
        )
    _write_csv_exclusive(root / "parameters" / "momenta.csv", momenta_rows)


def _source_run_document(inputs: ReferenceMomentaInput) -> dict[str, object]:
    report = inputs.run_report
    backend = report.manifest["backend"]
    return {
        "run_id": str(report.manifest["run_id"]),
        "backend_id": str(backend["id"]),
        "backend_contract_version": str(backend["contract_version"]),
        "manifest_sha256": sha256_file(inputs.run_directory / "manifest.json"),
        "result_sha256": sha256_file(inputs.run_directory / "result.json"),
        "output_inventory_sha256": sha256_file(
            inputs.run_directory / "output-inventory.json"
        ),
    }


def write_reference_pca_bundle(
    run_directory: Path | str,
    destination: Path | str | None = None,
    *,
    pca_components: int | None = None,
    created_at: str | None = None,
) -> Path:
    """Atomically publish a self-contained, source-bound Deformetrica PCA bundle."""

    inputs = load_reference_momenta(run_directory)
    try:
        pca = momenta_pca(
            np.array(inputs.momenta, dtype=np.float64, copy=True),
            n_components=pca_components,
            subject_labels=inputs.subject_labels,
        )
    except (TypeError, ValueError, np.linalg.LinAlgError) as error:
        raise ReferencePCAError(f"Could not compute momenta PCA: {error}") from error
    target = (
        inputs.run_directory / DEFAULT_REFERENCE_PCA_DIRECTORY
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    if target.exists():
        raise FileExistsError(f"Reference PCA bundle destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        raw_momenta = temporary / "source" / "deformetrica-momenta.txt"
        raw_controls = temporary / "source" / "deformetrica-control-points.txt"
        raw_momenta.parent.mkdir(parents=True)
        shutil.copyfile(inputs.momenta_path, raw_momenta)
        shutil.copyfile(inputs.control_points_path, raw_controls)
        if sha256_file(raw_momenta) != str(inputs.momenta_record["sha256"]):
            raise ReferencePCAError("Copied momenta changed while the PCA bundle was created")
        if sha256_file(raw_controls) != str(inputs.control_points_record["sha256"]):
            raise ReferencePCAError(
                "Copied control points changed while the PCA bundle was created"
            )
        _parameter_tables(temporary, inputs)
        pca_paths = write_pca_artifacts(temporary, pca)
        generated = sorted(path for path in temporary.rglob("*") if path.is_file())
        artifacts = [_artifact(temporary, path) for path in generated]
        timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
        manifest = {
            "bundle_version": REFERENCE_PCA_BUNDLE_VERSION,
            "created_at": timestamp,
            "source_run": _source_run_document(inputs),
            "inputs": {
                "momenta": _source_artifact(
                    inputs.momenta_record,
                    raw_momenta.relative_to(temporary).as_posix(),
                ),
                "control_points": _source_artifact(
                    inputs.control_points_record,
                    raw_controls.relative_to(temporary).as_posix(),
                ),
                "subjects": inputs.subject_count,
                "control_point_count": inputs.control_point_count,
                "dimension": 3,
                "subject_labels": list(inputs.subject_labels),
                "subject_identity_source": SUBJECT_IDENTITY_SOURCE,
                "feature_order": FEATURE_ORDER,
            },
            "pca": {
                "method": "centered linear PCA by deterministic float64 SVD",
                "feature_space": pca.feature_space,
                "components": pca.number_of_components,
                "numerical_rank": pca.numerical_rank,
                "total_variance": pca.total_variance,
                **pca_paths,
            },
            "artifacts": artifacts,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
            "immutability_contract": {
                "publication": "atomic no-replace directory publication",
                "verification": (
                    "schema, complete artifact inventory, hashes, and recomputed PCA tables"
                ),
                "source_binding": "copied raw Deformetrica parameters plus source run hashes",
            },
        }
        _validate_manifest(manifest)
        manifest_path = temporary / REFERENCE_PCA_MANIFEST
        _write_json_exclusive(manifest_path, manifest)
        (temporary / REFERENCE_PCA_SIDECAR).write_text(
            sha256_file(manifest_path) + "\n",
            encoding="ascii",
            newline="\n",
        )
        verify_reference_pca_bundle(temporary, source_run=inputs.run_directory)
        publish_directory_exclusive(temporary, target)
        return verify_reference_pca_bundle(target, source_run=inputs.run_directory).bundle_directory
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


@dataclass(frozen=True)
class ReferencePCABundle:
    bundle_directory: Path
    manifest: Mapping[str, Any]
    pca: PCAResult


def _safe_bundle_path(root: Path, value: object, label: str) -> Path:
    relative = PurePosixPath(str(value))
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() in {"", "."}:
        raise ReferencePCAError(f"{label} escapes the PCA bundle")
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReferencePCAError(f"{label} is symbolic: {relative.as_posix()}")
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ReferencePCAError(
            f"{label} does not resolve inside the PCA bundle"
        ) from error
    return candidate


def _read_csv(path: Path, label: str) -> list[list[str]]:
    try:
        with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
            return list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ReferencePCAError(f"Could not read {label}: {path}") from error


def _assert_numeric_rows_close(
    observed: Sequence[Sequence[str]],
    expected: Sequence[Sequence[str]],
    *,
    label: str,
) -> None:
    if len(observed) != len(expected) or not observed or observed[0] != list(expected[0]):
        raise ReferencePCAError(f"{label} structure differs from recomputed PCA")
    for line, (actual, wanted) in enumerate(zip(observed[1:], expected[1:], strict=True), start=2):
        if len(actual) != len(wanted) or actual[0] != wanted[0]:
            raise ReferencePCAError(f"{label} identity differs at CSV line {line}")
        try:
            actual_values = np.asarray(actual[1:], dtype=np.float64)
            wanted_values = np.asarray(wanted[1:], dtype=np.float64)
        except ValueError as error:
            raise ReferencePCAError(f"{label} contains a non-number at CSV line {line}") from error
        if not bool(
            np.allclose(actual_values, wanted_values, rtol=1e-12, atol=1e-14, equal_nan=False)
        ):
            raise ReferencePCAError(f"{label} values differ at CSV line {line}")


def _verify_summary(path: Path, pca: PCAResult) -> None:
    try:
        observed = load_strict_json_object(path.read_bytes(), path, label="PCA summary")
    except (ConfigurationError, OSError) as error:
        raise ReferencePCAError(str(error)) from error
    expected = pca_summary_document(pca)
    scalar_keys = (
        "feature_space",
        "sample_labels",
        "feature_labels",
        "number_of_components",
        "numerical_rank",
        "tied_component_groups",
        "zero_variance_components",
        "sign_convention",
    )
    if any(observed.get(key) != expected[key] for key in scalar_keys):
        raise ReferencePCAError("PCA summary identity or structural evidence differs")
    for key in (
        "total_variance",
        "singular_values",
        "explained_variance",
        "explained_variance_ratio",
    ):
        try:
            actual = np.asarray(observed[key], dtype=np.float64)
            wanted = np.asarray(expected[key], dtype=np.float64)
        except (KeyError, TypeError, ValueError) as error:
            raise ReferencePCAError(f"PCA summary {key} is invalid") from error
        if actual.shape != wanted.shape or not bool(
            np.allclose(actual, wanted, rtol=1e-12, atol=1e-14, equal_nan=False)
        ):
            raise ReferencePCAError(f"PCA summary {key} differs from recomputation")


def _verify_source_binding(manifest: Mapping[str, Any], source_run: Path) -> None:
    inputs = load_reference_momenta(source_run)
    if manifest["source_run"] != _source_run_document(inputs):
        raise ReferencePCAError("PCA bundle source-run hashes differ from the current run")
    if tuple(manifest["inputs"]["subject_labels"]) != inputs.subject_labels:
        raise ReferencePCAError("PCA bundle subject order differs from the source run")


def verify_reference_pca_bundle(
    bundle_directory: Path | str,
    *,
    source_run: Path | str | None = None,
) -> ReferencePCABundle:
    """Verify bundle inventory and recompute PCA from its copied raw parameters."""

    root = Path(bundle_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ReferencePCAError(f"Reference PCA bundle is missing or symbolic: {root}")
    manifest_path = root / REFERENCE_PCA_MANIFEST
    sidecar_path = root / REFERENCE_PCA_SIDECAR
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise ReferencePCAError("Reference PCA manifest or SHA-256 sidecar is missing")
    expected_manifest_hash = sidecar_path.read_text(encoding="ascii").strip()
    if expected_manifest_hash != sha256_file(manifest_path):
        raise ReferencePCAError("Reference PCA manifest SHA-256 does not match its sidecar")
    try:
        manifest = load_strict_json_object(
            manifest_path.read_bytes(),
            manifest_path,
            label="Reference PCA manifest",
        )
    except (ConfigurationError, OSError) as error:
        raise ReferencePCAError(str(error)) from error
    _validate_manifest(manifest)

    declared: set[str] = set()
    for record in manifest["artifacts"]:
        relative = str(record["path"])
        if relative in declared:
            raise ReferencePCAError(f"Duplicate PCA artifact inventory path: {relative}")
        declared.add(relative)
        path = _safe_bundle_path(root, relative, "PCA artifact")
        if not path.is_file():
            raise ReferencePCAError(f"PCA artifact is missing: {relative}")
        if path.stat().st_size != int(record["bytes"]):
            raise ReferencePCAError(f"PCA artifact size differs: {relative}")
        if sha256_file(path) != str(record["sha256"]):
            raise ReferencePCAError(f"PCA artifact SHA-256 differs: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in {REFERENCE_PCA_MANIFEST, REFERENCE_PCA_SIDECAR}
    }
    if actual != declared:
        raise ReferencePCAError("PCA artifact inventory is incomplete or lists absent files")

    input_document = manifest["inputs"]
    raw_momenta = _safe_bundle_path(
        root,
        input_document["momenta"]["copied_path"],
        "Copied momenta",
    )
    raw_controls = _safe_bundle_path(
        root,
        input_document["control_points"]["copied_path"],
        "Copied control points",
    )
    for path, record, label in (
        (raw_momenta, input_document["momenta"], "momenta"),
        (raw_controls, input_document["control_points"], "control points"),
    ):
        if path.stat().st_size != int(record["bytes"]) or sha256_file(path) != str(
            record["sha256"]
        ):
            raise ReferencePCAError(f"Copied raw Deformetrica {label} differs from source hash")
    momenta = read_deformetrica_momenta(raw_momenta)
    read_deformetrica_control_points(raw_controls, expected_count=momenta.shape[1])
    labels = tuple(input_document["subject_labels"])
    if momenta.shape != (
        int(input_document["subjects"]),
        int(input_document["control_point_count"]),
        3,
    ) or len(labels) != momenta.shape[0]:
        raise ReferencePCAError("Copied raw parameters differ from declared dimensions")
    try:
        pca = momenta_pca(
            np.array(momenta, dtype=np.float64, copy=True),
            n_components=int(manifest["pca"]["components"]),
            subject_labels=labels,
        )
    except (TypeError, ValueError, np.linalg.LinAlgError) as error:
        raise ReferencePCAError(f"Could not recompute momenta PCA: {error}") from error
    if pca.numerical_rank != int(manifest["pca"]["numerical_rank"]) or not math.isclose(
        pca.total_variance,
        float(manifest["pca"]["total_variance"]),
        rel_tol=1e-12,
        abs_tol=1e-14,
    ):
        raise ReferencePCAError("PCA manifest statistics differ from recomputation")
    _verify_summary(_safe_bundle_path(root, manifest["pca"]["summary_path"], "PCA summary"), pca)
    _assert_numeric_rows_close(
        _read_csv(
            _safe_bundle_path(root, manifest["pca"]["scores_path"], "PCA scores"),
            "PCA scores",
        ),
        pca_score_rows(pca),
        label="PCA scores",
    )
    _assert_numeric_rows_close(
        _read_csv(
            _safe_bundle_path(root, manifest["pca"]["loadings_path"], "PCA loadings"),
            "PCA loadings",
        ),
        pca_loading_rows(pca),
        label="PCA loadings",
    )
    _assert_numeric_rows_close(
        _read_csv(_safe_bundle_path(root, manifest["pca"]["mean_path"], "PCA mean"), "PCA mean"),
        pca_mean_rows(pca),
        label="PCA mean",
    )
    if source_run is not None:
        _verify_source_binding(manifest, Path(source_run).expanduser().resolve())
    return ReferencePCABundle(root, manifest, pca)

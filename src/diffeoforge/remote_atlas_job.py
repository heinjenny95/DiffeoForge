"""Portable, hash-bound Modern atlas jobs for explicit remote execution."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema
import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError, validate_input_paths
from diffeoforge.engine.execution import ENGINE_IMPLEMENTATION_VERSION
from diffeoforge.mesh import inspect_inputs, sha256_file
from diffeoforge.modern_progress import ModernProgressCallback
from diffeoforge.modern_workflow import (
    WORKFLOW_VERSION,
    load_modern_workflow_config,
    run_modern_workflow,
    validate_modern_analysis_dimensions,
    verify_modern_workflow,
)
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

REMOTE_ATLAS_JOB_VERSION = "0.1"
MANIFEST_NAME = "remote-atlas-job.json"
MANIFEST_SIDECAR_NAME = "remote-atlas-job.sha256"
PACKAGED_CONFIG_PATH = "config/modern-atlas.yaml"
SCIENTIFIC_BOUNDARY = (
    "This package makes one Modern atlas request portable and hash-verifiable. It does "
    "not establish biological validity, parameter suitability, convergence, server trust, "
    "or production readiness. A verified result retains the scientific boundaries of the "
    "nested Modern workflow and atlas bundle."
)
TRANSFER_BOUNDARY = (
    "Creation and verification perform no network request, upload, authentication, billing, "
    "or telemetry. The package contains raw meshes and specimen filenames; transfer requires "
    "a separate explicit user-authorized mechanism."
)


class RemoteAtlasJobError(RuntimeError):
    """Raised when a portable remote-atlas request or result is invalid."""


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath("remote-atlas-job-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _timestamp(value: str | None) -> str:
    timestamp = value or datetime.now(UTC).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise RemoteAtlasJobError("created_at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise RemoteAtlasJobError("created_at must include a timezone offset")
    return timestamp


def _resolve_config_reference(value: object, config_path: Path, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{label} must be a non-empty path string")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    candidate = candidate.absolute()
    if candidate.is_symlink():
        raise ConfigurationError(f"{label} must not be symbolic: {candidate}")
    if not candidate.is_file():
        raise ConfigurationError(f"{label} does not exist: {candidate}")
    return candidate.resolve()


def _safe_artifact_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RemoteAtlasJobError("Remote job artifact paths must be POSIX-style strings")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or "." in relative.parts
        or ".." in relative.parts
        or (relative.parts and ":" in relative.parts[0])
    ):
        raise RemoteAtlasJobError(f"Unsafe remote job artifact path: {value!r}")
    path = root.joinpath(*relative.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise RemoteAtlasJobError(f"Remote job artifact escapes the package: {value!r}") from error
    return path


def _artifact_record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _copy_bound_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ConfigurationError(f"Remote job input is missing or symbolic: {source}")
    before = sha256_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, destination.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    if sha256_file(source) != before:
        raise RemoteAtlasJobError(f"Remote job input changed while it was copied: {source}")
    if sha256_file(destination) != before:
        raise RemoteAtlasJobError(f"Remote job input copy differs: {source}")


def _optional_source_inputs(
    config: dict[str, Any],
    source_config: Path,
) -> dict[str, Path | None]:
    optimization = config["optimization"]
    if optimization.get("resume_state") is not None:
        raise RemoteAtlasJobError(
            "Remote atlas job v0.1 does not package an existing optimizer resume state; "
            "create a fresh request or recover the interrupted run on the execution host"
        )

    procrustes = config["preprocessing"]["procrustes"]
    landmarks = (
        _resolve_config_reference(
            procrustes["landmarks_file"],
            source_config,
            label="Procrustes landmarks file",
        )
        if procrustes["enabled"]
        else None
    )
    control = config["initialization"]["control_points"]
    control_points = (
        _resolve_config_reference(
            control["path"],
            source_config,
            label="Initial control-points file",
        )
        if control["method"] == "file"
        else None
    )
    momenta_config = config["initialization"]["momenta"]
    momenta = (
        _resolve_config_reference(
            momenta_config["path"],
            source_config,
            label="Initial momenta file",
        )
        if isinstance(momenta_config, dict)
        else None
    )
    return {
        "landmarks": landmarks,
        "control_points": control_points,
        "momenta": momenta,
    }


def _reject_symbolic_mesh_selection(config: dict[str, Any], source_config: Path) -> None:
    input_config = config["input"]
    directory = Path(input_config["directory"]).expanduser()
    if not directory.is_absolute():
        directory = source_config.parent / directory
    directory = directory.absolute()
    if directory.is_symlink():
        raise ConfigurationError(f"Remote input directory must not be symbolic: {directory}")
    template = Path(input_config["template"]).expanduser()
    if not template.is_absolute():
        template = source_config.parent / template
    if template.absolute().is_symlink():
        raise ConfigurationError(f"Remote template must not be symbolic: {template.absolute()}")
    try:
        symbolic = [
            path
            for path in directory.glob(input_config["subject_pattern"])
            if path.is_symlink()
        ]
    except (OSError, ValueError) as error:
        raise ConfigurationError(f"Could not inspect remote subject selection: {error}") from error
    if symbolic:
        raise ConfigurationError(f"Remote subject mesh must not be symbolic: {symbolic[0]}")


def _write_packaged_config(
    config: dict[str, Any],
    optional_inputs: dict[str, Path | None],
    destination: Path,
) -> dict[str, Any]:
    packaged = deepcopy(config)
    packaged["input"]["directory"] = "../inputs/subjects"
    packaged["input"]["template"] = "../inputs/initial-template.vtk"
    packaged["output"]["directory"] = "."
    if optional_inputs["landmarks"] is not None:
        packaged["preprocessing"]["procrustes"]["landmarks_file"] = (
            "../inputs/landmarks.csv"
        )
    if optional_inputs["control_points"] is not None:
        packaged["initialization"]["control_points"]["path"] = (
            "../inputs/control-points.txt"
        )
    if optional_inputs["momenta"] is not None:
        packaged["initialization"]["momenta"]["path"] = "../inputs/momenta.csv"
    rendered = yaml.safe_dump(packaged, sort_keys=False, allow_unicode=True)
    write_text_safely(destination, rendered, overwrite=False)
    return packaged


def create_remote_atlas_job(
    config_path: Path | str,
    destination: Path | str,
    *,
    created_at: str | None = None,
) -> Path:
    """Create an immutable portable Modern request without uploading it."""

    source_config = Path(config_path).expanduser().absolute()
    if source_config.is_symlink() or not source_config.is_file():
        raise ConfigurationError(
            f"Modern workflow configuration is missing or symbolic: {source_config}"
        )
    source_config = source_config.resolve()
    config_sha256 = sha256_file(source_config)
    config = load_modern_workflow_config(source_config)
    _reject_symbolic_mesh_selection(config, source_config)
    inputs = validate_input_paths(config, source_config)
    validate_modern_analysis_dimensions(config, len(inputs.subjects))
    template_metadata, subject_metadata = inspect_inputs(inputs)
    optional_inputs = _optional_source_inputs(config, source_config)

    target = Path(destination).expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Remote atlas job destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        packaged_config_path = temporary / Path(PACKAGED_CONFIG_PATH)
        packaged_config_path.parent.mkdir(parents=True, exist_ok=True)
        packaged_config = _write_packaged_config(
            config,
            optional_inputs,
            packaged_config_path,
        )

        template_destination = temporary / "inputs" / "initial-template.vtk"
        _copy_bound_file(inputs.template, template_destination)
        subject_records: list[dict[str, object]] = []
        for source, metadata in zip(inputs.subjects, subject_metadata, strict=True):
            copied = temporary / "inputs" / "subjects" / source.name
            _copy_bound_file(source, copied)
            subject_records.append(
                {
                    "source_filename": source.name,
                    "packaged_path": copied.relative_to(temporary).as_posix(),
                    "bytes": metadata.bytes,
                    "sha256": metadata.sha256,
                    "points": metadata.points,
                    "triangles": metadata.cells,
                }
            )

        optional_records: dict[str, dict[str, object] | None] = {}
        optional_destinations = {
            "landmarks": temporary / "inputs" / "landmarks.csv",
            "control_points": temporary / "inputs" / "control-points.txt",
            "momenta": temporary / "inputs" / "momenta.csv",
        }
        for label, source in optional_inputs.items():
            if source is None:
                optional_records[label] = None
                continue
            copied = optional_destinations[label]
            _copy_bound_file(source, copied)
            optional_records[label] = {
                "source_filename": source.name,
                "packaged_path": copied.relative_to(temporary).as_posix(),
                "bytes": copied.stat().st_size,
                "sha256": sha256_file(copied),
            }

        artifacts = sorted(
            (
                _artifact_record(path, temporary)
                for path in temporary.rglob("*")
                if path.is_file()
            ),
            key=lambda record: str(record["path"]),
        )
        manifest = {
            "job_version": REMOTE_ATLAS_JOB_VERSION,
            "created_at": _timestamp(created_at),
            "job_type": "modern_atlas",
            "source": {
                "config_filename": source_config.name,
                "config_sha256": config_sha256,
            },
            "execution": {
                "config_path": PACKAGED_CONFIG_PATH,
                "config_sha256": sha256_file(packaged_config_path),
                "expected_engine_implementation": ENGINE_IMPLEMENTATION_VERSION,
                "expected_workflow_version": WORKFLOW_VERSION,
                "device": packaged_config["runtime"]["device"],
                "precision": packaged_config["runtime"]["precision"],
            },
            "input": {
                "units": packaged_config["input"]["units"],
                "template": {
                    "source_filename": inputs.template.name,
                    "packaged_path": template_destination.relative_to(temporary).as_posix(),
                    "bytes": template_metadata.bytes,
                    "sha256": template_metadata.sha256,
                    "points": template_metadata.points,
                    "triangles": template_metadata.cells,
                },
                "subjects": subject_records,
            },
            "optional_inputs": optional_records,
            "artifacts": artifacts,
            "transfer": {
                "contains_raw_meshes": True,
                "contains_specimen_filenames": True,
                "automatic_upload_authorized": False,
            },
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
            "transfer_boundary": TRANSFER_BOUNDARY,
        }
        manifest_path = temporary / MANIFEST_NAME
        write_text_safely(
            manifest_path,
            _canonical_json(manifest),
            overwrite=False,
        )
        write_text_safely(
            temporary / MANIFEST_SIDECAR_NAME,
            f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n",
            overwrite=False,
            encoding="ascii",
        )
        if sha256_file(source_config) != config_sha256:
            raise RemoteAtlasJobError("Source configuration changed while packaging")
        verify_remote_atlas_job(temporary)
        publish_directory_exclusive(temporary, target)
        verify_remote_atlas_job(target)
        return target
    except BaseException:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def _read_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise RemoteAtlasJobError(f"Remote atlas job manifest is missing: {manifest_path}")
    try:
        manifest = load_strict_json_object(
            manifest_path.read_bytes(),
            manifest_path,
            label="Remote atlas job manifest",
        )
    except (ConfigurationError, OSError) as error:
        raise RemoteAtlasJobError(str(error)) from error
    try:
        jsonschema.Draft202012Validator(_schema()).validate(manifest)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise RemoteAtlasJobError(
            f"Remote atlas job schema validation failed at {location}: {error.message}"
        ) from error
    _timestamp(str(manifest["created_at"]))
    return manifest


def verify_remote_atlas_job(directory: Path | str) -> dict[str, Any]:
    """Verify the exact portable request without network or compute."""

    root = Path(directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise RemoteAtlasJobError(f"Remote atlas job directory is missing or symbolic: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RemoteAtlasJobError(f"Remote atlas job contains a symbolic path: {path}")
    manifest = _read_manifest(root)
    if manifest["scientific_boundary"] != SCIENTIFIC_BOUNDARY:
        raise RemoteAtlasJobError("Remote atlas job scientific boundary differs")
    if manifest["transfer_boundary"] != TRANSFER_BOUNDARY:
        raise RemoteAtlasJobError("Remote atlas job transfer boundary differs")

    manifest_path = root / MANIFEST_NAME
    sidecar_path = root / MANIFEST_SIDECAR_NAME
    try:
        sidecar = sidecar_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise RemoteAtlasJobError("Remote atlas job sidecar is unreadable") from error
    if sidecar != f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n":
        raise RemoteAtlasJobError("Remote atlas job manifest SHA-256 sidecar differs")

    artifacts = manifest["artifacts"]
    listed = [record["path"] for record in artifacts]
    if len(listed) != len(set(listed)):
        raise RemoteAtlasJobError("Remote atlas job artifact inventory contains duplicates")
    actual = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative not in {MANIFEST_NAME, MANIFEST_SIDECAR_NAME}:
            actual.add(relative)
    if actual != set(listed):
        raise RemoteAtlasJobError(
            "Remote atlas job exact file inventory differs; "
            f"missing={sorted(set(listed) - actual)}, extra={sorted(actual - set(listed))}"
        )
    for record in artifacts:
        path = _safe_artifact_path(root, record["path"])
        if not path.is_file():
            raise RemoteAtlasJobError(f"Remote atlas job artifact is missing: {record['path']}")
        if path.stat().st_size != record["bytes"]:
            raise RemoteAtlasJobError(f"Remote atlas job artifact size differs: {record['path']}")
        if sha256_file(path) != record["sha256"]:
            raise RemoteAtlasJobError(
                f"Remote atlas job artifact SHA-256 differs: {record['path']}"
            )

    execution = manifest["execution"]
    config_path = _safe_artifact_path(root, execution["config_path"])
    if sha256_file(config_path) != execution["config_sha256"]:
        raise RemoteAtlasJobError("Remote atlas job packaged configuration hash differs")
    config = load_modern_workflow_config(config_path)
    if config["output"]["directory"] != ".":
        raise RemoteAtlasJobError(
            "Packaged remote configuration must require an explicit server output"
        )
    if (
        config["runtime"]["device"] != execution["device"]
        or config["runtime"]["precision"] != execution["precision"]
    ):
        raise RemoteAtlasJobError("Remote atlas job runtime binding differs")
    inputs = validate_input_paths(config, config_path)
    validate_modern_analysis_dimensions(config, len(inputs.subjects))
    template_metadata, subject_metadata = inspect_inputs(inputs)
    template = manifest["input"]["template"]
    if (
        inputs.template != _safe_artifact_path(root, template["packaged_path"]).resolve()
        or template_metadata.bytes != template["bytes"]
        or template_metadata.sha256 != template["sha256"]
        or template_metadata.points != template["points"]
        or template_metadata.cells != template["triangles"]
    ):
        raise RemoteAtlasJobError("Remote atlas job template binding differs")
    subjects = manifest["input"]["subjects"]
    if len(subjects) != len(inputs.subjects):
        raise RemoteAtlasJobError("Remote atlas job subject count differs")
    for source, metadata, record in zip(inputs.subjects, subject_metadata, subjects, strict=True):
        if (
            source != _safe_artifact_path(root, record["packaged_path"]).resolve()
            or source.name != record["source_filename"]
            or metadata.bytes != record["bytes"]
            or metadata.sha256 != record["sha256"]
            or metadata.points != record["points"]
            or metadata.cells != record["triangles"]
        ):
            raise RemoteAtlasJobError(
                f"Remote atlas job subject binding differs: {record['source_filename']}"
            )
    if manifest["input"]["units"] != config["input"]["units"]:
        raise RemoteAtlasJobError("Remote atlas job coordinate units differ")
    optional_paths: dict[str, Path | None] = {
        "landmarks": (
            _resolve_config_reference(
                config["preprocessing"]["procrustes"]["landmarks_file"],
                config_path,
                label="Packaged Procrustes landmarks file",
            )
            if config["preprocessing"]["procrustes"]["enabled"]
            else None
        ),
        "control_points": (
            _resolve_config_reference(
                config["initialization"]["control_points"]["path"],
                config_path,
                label="Packaged initial control-points file",
            )
            if config["initialization"]["control_points"]["method"] == "file"
            else None
        ),
        "momenta": (
            _resolve_config_reference(
                config["initialization"]["momenta"]["path"],
                config_path,
                label="Packaged initial momenta file",
            )
            if isinstance(config["initialization"]["momenta"], dict)
            else None
        ),
    }
    for label, expected_path in optional_paths.items():
        record = manifest["optional_inputs"][label]
        if expected_path is None:
            if record is not None:
                raise RemoteAtlasJobError(
                    f"Remote atlas job unexpectedly records optional input: {label}"
                )
            continue
        if record is None:
            raise RemoteAtlasJobError(f"Remote atlas job omits optional input: {label}")
        recorded_path = _safe_artifact_path(root, record["packaged_path"]).resolve()
        if (
            recorded_path != expected_path
            or expected_path.name != PurePosixPath(record["packaged_path"]).name
            or expected_path.stat().st_size != record["bytes"]
            or sha256_file(expected_path) != record["sha256"]
        ):
            raise RemoteAtlasJobError(f"Remote atlas job optional input binding differs: {label}")
    if execution["expected_workflow_version"] != WORKFLOW_VERSION:
        raise RemoteAtlasJobError("Remote atlas job workflow contract is unsupported")
    return manifest


def verify_remote_atlas_result(
    job_directory: Path | str,
    result_directory: Path | str,
) -> dict[str, Any]:
    """Verify a completed Modern workflow against one exact portable request."""

    job_root = Path(job_directory).expanduser().resolve()
    request = verify_remote_atlas_job(job_root)
    result_root = Path(result_directory).expanduser().resolve()
    result = verify_modern_workflow(result_root)
    execution = request["execution"]
    if result["workflow_version"] != execution["expected_workflow_version"]:
        raise RemoteAtlasJobError("Remote result workflow version differs from the request")
    if result["engine"]["implementation_version"] != execution[
        "expected_engine_implementation"
    ]:
        raise RemoteAtlasJobError("Remote result engine implementation differs from the request")
    if (
        result["engine"]["device"] != execution["device"]
        or result["engine"]["dtype"] != execution["precision"]
    ):
        raise RemoteAtlasJobError("Remote result runtime differs from the request")

    packaged_config = _safe_artifact_path(job_root, execution["config_path"])
    copied_source = result_root / result["config"]["source_path"]
    if sha256_file(copied_source) != sha256_file(packaged_config):
        raise RemoteAtlasJobError("Remote result source configuration differs from the request")
    effective_path = result_root / result["config"]["effective_path"]
    try:
        effective = load_strict_json_object(
            effective_path.read_bytes(),
            effective_path,
            label="Remote result effective configuration",
        )
    except (ConfigurationError, OSError) as error:
        raise RemoteAtlasJobError(str(error)) from error
    if effective != load_modern_workflow_config(packaged_config):
        raise RemoteAtlasJobError("Remote result effective configuration differs from the request")

    expected_meshes = [request["input"]["template"], *request["input"]["subjects"]]
    observed_meshes = [result["input"]["template"], *result["input"]["subjects"]]
    if len(expected_meshes) != len(observed_meshes):
        raise RemoteAtlasJobError("Remote result mesh count differs from the request")
    for expected, observed in zip(expected_meshes, observed_meshes, strict=True):
        packaged_name = PurePosixPath(expected["packaged_path"]).name
        if (
            observed["source_filename"] != packaged_name
            or observed["bytes"] != expected["bytes"]
            or observed["sha256"] != expected["sha256"]
            or observed["points"] != expected["points"]
            or observed["triangles"] != expected["triangles"]
        ):
            raise RemoteAtlasJobError(
                f"Remote result mesh binding differs: {expected['source_filename']}"
            )
    return result


def run_remote_atlas_job(
    job_directory: Path | str,
    destination: Path | str,
    *,
    progress_callback: ModernProgressCallback | None = None,
) -> Path:
    """Execute one verified request on the current host and bind its result."""

    job_root = Path(job_directory).expanduser().resolve()
    request = verify_remote_atlas_job(job_root)
    expected_engine = request["execution"]["expected_engine_implementation"]
    if expected_engine != ENGINE_IMPLEMENTATION_VERSION:
        raise RemoteAtlasJobError(
            "Remote execution host engine implementation differs from the request: "
            f"expected {expected_engine}, observed {ENGINE_IMPLEMENTATION_VERSION}"
        )
    result_root = Path(destination).expanduser().resolve()
    try:
        result_root.relative_to(job_root)
    except ValueError:
        pass
    else:
        raise RemoteAtlasJobError("Remote result must be outside the immutable job package")
    config_path = _safe_artifact_path(job_root, request["execution"]["config_path"])
    completed = run_modern_workflow(
        config_path,
        destination=result_root,
        progress_callback=progress_callback,
    )
    verify_remote_atlas_result(job_root, completed)
    return completed

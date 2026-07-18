"""Prepare, verify, and execute immutable DiffeoForge run directories."""

from __future__ import annotations

import csv
import ctypes
import errno
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import yaml
from jsonschema import Draft202012Validator

from diffeoforge import __version__
from diffeoforge.backends import (
    BACKEND_CONTRACT_VERSION,
    BACKEND_ID,
    ENGINE_CONSTANTS,
    build_command,
    ensure_launcher_available,
    generate_engine_files,
    generate_resume_optimization_file,
    validate_reference_config,
)
from diffeoforge.config import (
    ConfigurationError,
    load_config,
    resolve_output_directory,
    validate_input_paths,
)
from diffeoforge.mesh import MeshMetadata, inspect_inputs, sha256_file

RUN_MANIFEST_VERSION = "0.1"
RESUME_PROVENANCE_VERSION = "0.1"
RESUME_PROVENANCE_PATH = Path("resume") / "resume.json"
RESUME_CHECKPOINT_PATH = Path("resume") / "source-checkpoint.p"
EXECUTION_CHECKPOINT_PATH = Path("output") / "deformetrica-state.p"
RESUMABLE_STATES = frozenset({"failed", "interrupted"})
REFERENCE_DEFORMETRICA_VERSION = "4.3.0"
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
CONVERGENCE_RE = re.compile(
    rf"Log-likelihood\s*=\s*({NUMBER}).*?attachment\s*=\s*({NUMBER})"
    rf".*?regularity\s*=\s*({NUMBER})"
)
ITERATION_RE = re.compile(r"-+\s*Iteration:\s*(\d+)\s*-+")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_run_id(value: object) -> str:
    """Normalize one user-visible reference run identifier."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-._")
    if not cleaned:
        raise ConfigurationError("Project or run name is empty after normalization.")
    return cleaned


def default_run_id(config: Mapping[str, Any]) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{normalize_run_id(config['project']['name'])}"


def _write_json_exclusive(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _write_text_exclusive(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(value)


def _append_event(path: Path, event: Mapping[str, Any]) -> None:
    record = {"timestamp": utc_now(), **event}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _read_events(path: Path) -> list[Mapping[str, Any]]:
    if not path.is_file():
        raise ConfigurationError(f"Run event log is missing: {path}")
    events: list[Mapping[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ConfigurationError(
                    f"Invalid JSON in event log line {line_number}: {path}"
                ) from error
            if not isinstance(value, dict) or "event" not in value:
                raise ConfigurationError(f"Invalid run event at line {line_number}: {path}")
            events.append(value)
    if not events:
        raise ConfigurationError(f"Run event log is empty: {path}")
    return events


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def preparation_environment() -> dict[str, object]:
    return {
        "python": sys.version.replace("\n", " "),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "diffeoforge": __version__,
        "packages": {
            name: _package_version(name)
            for name in ("jsonschema", "PyYAML")
        },
    }


def _manifest_schema() -> Mapping[str, Any]:
    schema_file = files("diffeoforge.schema").joinpath("run-manifest-v0.1.json")
    return json.loads(schema_file.read_text(encoding="utf-8"))


def _resume_schema() -> Mapping[str, Any]:
    schema_file = files("diffeoforge.schema").joinpath("resume-v0.1.json")
    return json.loads(schema_file.read_text(encoding="utf-8"))


def _validate_manifest_schema(manifest: Mapping[str, Any]) -> None:
    validator = Draft202012Validator(_manifest_schema())
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.absolute_path))
    if errors:
        details = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            details.append(f"{location}: {error.message}")
        raise ConfigurationError(
            "Run manifest schema validation failed:\n  - " + "\n  - ".join(details)
        )


def _validate_resume_schema(provenance: Mapping[str, Any]) -> None:
    validator = Draft202012Validator(_resume_schema())
    errors = sorted(
        validator.iter_errors(provenance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            details.append(f"{location}: {error.message}")
        raise ConfigurationError(
            "Resume provenance schema validation failed:\n  - " + "\n  - ".join(details)
        )


def effective_reference_config(
    config: Mapping[str, Any],
    input_directory: Path,
    template: Path,
    output_directory: Path,
) -> dict[str, Any]:
    effective = deepcopy(dict(config))
    effective["input"]["directory"] = str(input_directory)
    effective["input"]["template"] = str(template)
    effective["output"]["directory"] = str(output_directory)
    return effective


def _copy_and_verify(source: Path, destination: Path, expected_hash: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    actual_hash = sha256_file(destination)
    if actual_hash != expected_hash:
        raise ConfigurationError(
            f"Staged input hash mismatch for {source}; expected {expected_hash}, got {actual_hash}."
        )


def reference_input_record(
    role: str,
    source: Path,
    staged: Path,
    metadata: MeshMetadata,
) -> dict[str, object]:
    geometry = metadata.as_manifest()
    geometry.pop("path", None)
    return {
        "role": role,
        "source_path": str(source),
        "staged_path": staged.as_posix(),
        "geometry": geometry,
    }


def _artifact_record(run_directory: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(run_directory).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _safe_cleanup_temporary_run(temp_directory: Path, output_root: Path) -> None:
    resolved_temp = temp_directory.resolve()
    resolved_root = output_root.resolve()
    is_child = resolved_temp.parent == resolved_root
    has_prefix = resolved_temp.name.startswith(".diffeoforge-preparing-")
    if is_child and has_prefix and resolved_temp.exists():
        shutil.rmtree(resolved_temp)


def _publish_directory_exclusive(source: Path, destination: Path) -> None:
    """Atomically publish one directory without replacing an appearing destination."""

    if os.name == "nt":
        try:
            os.rename(source, destination)
        except FileExistsError as error:
            raise ConfigurationError(
                f"Run directory appeared before atomic publication: {destination}"
            ) from error
        except PermissionError as error:
            if destination.exists():
                raise ConfigurationError(
                    f"Run directory appeared before atomic publication: {destination}"
                ) from error
            raise
        return

    if sys.platform.startswith("linux"):
        renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
        if renameat2 is None:
            raise ConfigurationError(
                "Atomic no-replace directory publication is unavailable on this Linux host"
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise ConfigurationError(
                f"Run directory appeared before atomic publication: {destination}"
            )
        raise OSError(error_number, os.strerror(error_number), str(destination))

    if destination.exists():
        raise ConfigurationError(
            f"Run directory appeared before atomic publication: {destination}"
        )
    os.rename(source, destination)


def _assert_staged_run_matches_plan(
    plan: Mapping[str, Any],
    *,
    source_config: Path,
    output_root: Path,
    final_directory: Path,
    manifest: Mapping[str, Any],
    temp_directory: Path,
) -> None:
    """Require every plan-bound preparation value to match private staging."""

    actual_protected = list(manifest["protected_artifacts"])
    expected_protected = [
        {
            "path": str(item["path"]),
            "bytes": int(item["bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in plan["protected_files"]
    ]
    comparisons = {
        "run_id": manifest["run_id"] == plan["run"]["run_id"],
        "output_root": str(output_root) == plan["run"]["output_root"],
        "destination": str(final_directory) == plan["run"]["destination"],
        "source_config_path": str(source_config) == plan["source_config"]["path"],
        "source_config_sha256": (
            manifest["source_config"]["sha256"] == plan["source_config"]["sha256"]
        ),
        "backend": manifest["backend"] == plan["backend"],
        "effective_config": manifest["effective_config"] == plan["effective_config"],
        "input_count": manifest["input_count"] == plan["input_count"],
        "inputs": manifest["inputs"] == plan["inputs"],
        "protected_files": actual_protected == expected_protected,
        "protected_file_count": len(actual_protected) == plan["protected_file_count"],
        "total_protected_bytes": (
            sum(int(item["bytes"]) for item in actual_protected)
            == plan["total_protected_bytes"]
        ),
        "command_preview": manifest["command_preview"] == plan["command_preview"],
        "directories": all(
            (temp_directory / Path(str(relative))).is_dir()
            for relative in plan["directories"]
        ),
    }
    for label, matches in comparisons.items():
        if not matches:
            raise ConfigurationError(
                "Privately staged run does not exactly match the approved reference "
                f"preparation plan at {label}"
            )

    for item in plan["protected_files"]:
        if item["kind"] != "generated":
            continue
        actual = temp_directory / Path(str(item["path"]))
        if actual.read_bytes() != str(item["content_utf8"]).encode("utf-8"):
            raise ConfigurationError(
                "Privately staged generated bytes do not match the approved reference "
                f"preparation plan: {item['path']}"
            )


def _prepare_run(
    config_path: Path | str,
    *,
    run_id: str | None = None,
    output_directory: Path | str | None = None,
    expected_plan: Mapping[str, Any] | None = None,
    before_publish: Callable[[Path, Mapping[str, Any]], None] | None = None,
) -> Path:
    """Create a complete run directory atomically and never overwrite a run."""

    source_config = Path(config_path).expanduser().resolve()
    config = load_config(source_config)
    validate_reference_config(config)
    summary = validate_input_paths(config, source_config)
    template_metadata, subject_metadata = inspect_inputs(summary)

    output_root = (
        Path(output_directory).expanduser().resolve()
        if output_directory is not None
        else resolve_output_directory(config, source_config)
    )
    resolved_run_id = normalize_run_id(run_id or default_run_id(config))
    final_directory = output_root / resolved_run_id
    if expected_plan is not None:
        if str(expected_plan["run"]["run_id"]) != resolved_run_id:
            raise ConfigurationError("Approved plan run_id differs from preparation run_id")
        if Path(str(expected_plan["run"]["output_root"])).resolve() != output_root:
            raise ConfigurationError("Approved plan output root differs from preparation output")
        if Path(str(expected_plan["run"]["destination"])).resolve() != final_directory:
            raise ConfigurationError(
                "Approved plan destination differs from preparation destination"
            )
    if final_directory.exists():
        raise ConfigurationError(f"Run directory already exists: {final_directory}")
    output_root.mkdir(parents=True, exist_ok=True)

    temp_directory = output_root / f".diffeoforge-preparing-{resolved_run_id}-{uuid4().hex}"
    temp_directory.mkdir(exist_ok=False)
    try:
        input_template_directory = temp_directory / "input" / "template"
        input_subject_directory = temp_directory / "input" / "subjects"
        config_directory = temp_directory / "config"
        engine_directory = temp_directory / "engine"
        output_path = temp_directory / "output"
        logs_directory = temp_directory / "logs"
        for directory in (
            input_template_directory,
            input_subject_directory,
            config_directory,
            engine_directory,
            output_path,
            logs_directory,
        ):
            directory.mkdir(parents=True, exist_ok=False)

        staged_template_relative = Path("input") / "template" / summary.template.name
        staged_template = temp_directory / staged_template_relative
        _copy_and_verify(summary.template, staged_template, template_metadata.sha256)

        staged_subject_relatives: list[Path] = []
        input_records = [
            reference_input_record(
                "template",
                summary.template,
                staged_template_relative,
                template_metadata,
            )
        ]
        for source, metadata in zip(summary.subjects, subject_metadata, strict=True):
            staged_relative = Path("input") / "subjects" / source.name
            _copy_and_verify(source, temp_directory / staged_relative, metadata.sha256)
            staged_subject_relatives.append(staged_relative)
            input_records.append(
                reference_input_record("subject", source, staged_relative, metadata)
            )

        source_config_copy = config_directory / "source-config.yaml"
        shutil.copy2(source_config, source_config_copy)
        effective = effective_reference_config(
            config,
            summary.input_directory,
            summary.template,
            output_root,
        )
        effective_config_path = config_directory / "effective-config.yaml"
        with effective_config_path.open("x", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(effective, handle, sort_keys=False, allow_unicode=True)

        engine_files = generate_engine_files(
            config,
            engine_directory,
            Path("..") / staged_template_relative,
            [Path("..") / path for path in staged_subject_relatives],
        )

        protected_paths = [
            source_config_copy,
            effective_config_path,
            staged_template,
            *(temp_directory / path for path in staged_subject_relatives),
            *engine_files,
        ]
        command_preview = build_command(config, final_directory)
        manifest = {
            "manifest_version": RUN_MANIFEST_VERSION,
            "run_id": resolved_run_id,
            "created_at": utc_now(),
            "project": dict(config["project"]),
            "source_config": {
                "path": str(source_config),
                "sha256": sha256_file(source_config_copy),
            },
            "backend": {
                "id": BACKEND_ID,
                "contract_version": BACKEND_CONTRACT_VERSION,
                "engine_constants": ENGINE_CONSTANTS,
            },
            "effective_config": effective,
            "input_count": {
                "templates": 1,
                "subjects": len(summary.subjects),
            },
            "inputs": input_records,
            "protected_artifacts": [
                _artifact_record(temp_directory, path) for path in protected_paths
            ],
            "command_preview": command_preview.as_manifest(),
            "preparation_environment": preparation_environment(),
            "immutability_contract": {
                "manifest": "write-once with SHA-256 sidecar",
                "protected_artifacts": "verified before execution",
                "events": "append-only JSON Lines",
                "output": "must be empty before first execution",
                "run_directory": "never overwritten or reused",
            },
        }
        _validate_manifest_schema(manifest)
        if expected_plan is not None:
            _assert_staged_run_matches_plan(
                expected_plan,
                source_config=source_config,
                output_root=output_root,
                final_directory=final_directory,
                manifest=manifest,
                temp_directory=temp_directory,
            )
        manifest_path = temp_directory / "manifest.json"
        _write_json_exclusive(manifest_path, manifest)
        _write_text_exclusive(
            temp_directory / "manifest.sha256",
            f"{sha256_file(manifest_path)}  manifest.json\n",
        )
        _append_event(
            temp_directory / "events.jsonl",
            {"event": "prepared", "run_id": resolved_run_id},
        )

        if before_publish is not None:
            before_publish(temp_directory, manifest)
        _publish_directory_exclusive(temp_directory, final_directory)
    except Exception:
        _safe_cleanup_temporary_run(temp_directory, output_root)
        raise
    return final_directory


def prepare_run(
    config_path: Path | str,
    *,
    run_id: str | None = None,
    output_directory: Path | str | None = None,
) -> Path:
    """Create a complete run directory atomically and never overwrite a run."""

    return _prepare_run(
        config_path,
        run_id=run_id,
        output_directory=output_directory,
    )


def prepare_run_against_plan(
    config_path: Path | str,
    plan: Mapping[str, Any],
    *,
    before_publish: Callable[[Path, Mapping[str, Any]], None] | None = None,
) -> Path:
    """Atomically prepare only bytes matching one already validated exact plan."""

    if not isinstance(plan, Mapping):
        raise TypeError("plan must be a mapping")
    return _prepare_run(
        config_path,
        run_id=str(plan["run"]["run_id"]),
        output_directory=str(plan["run"]["output_root"]),
        expected_plan=plan,
        before_publish=before_publish,
    )


def _read_manifest(run_directory: Path) -> Mapping[str, Any]:
    manifest_path = run_directory / "manifest.json"
    checksum_path = run_directory / "manifest.sha256"
    if not manifest_path.is_file() or not checksum_path.is_file():
        raise ConfigurationError(f"Run manifest or checksum is missing: {run_directory}")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(manifest_path)
    if expected != actual:
        raise ConfigurationError(
            f"Run manifest checksum mismatch; the prepared manifest changed: {manifest_path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"Run manifest is not valid JSON: {manifest_path}") from error
    if manifest.get("manifest_version") != RUN_MANIFEST_VERSION:
        raise ConfigurationError(
            f"Unsupported run manifest version: {manifest.get('manifest_version')}"
        )
    _validate_manifest_schema(manifest)
    return manifest


def _read_json_object(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must contain a JSON object: {path}")
    return value


def _resolve_run_artifact(run_directory: Path, value: object, label: str) -> Path:
    relative = PurePosixPath(str(value))
    if relative.is_absolute() or ".." in relative.parts:
        raise ConfigurationError(f"{label} escapes the run directory: {relative}")
    candidate = run_directory.joinpath(*relative.parts).resolve()
    if not candidate.is_relative_to(run_directory):
        raise ConfigurationError(f"{label} escapes the run directory: {relative}")
    return candidate


def _verify_protected_artifacts(
    run_directory: Path,
    manifest: Mapping[str, Any],
) -> None:
    for artifact in manifest["protected_artifacts"]:
        candidate = _resolve_run_artifact(
            run_directory,
            artifact["path"],
            "Protected artifact",
        )
        if not candidate.is_file():
            raise ConfigurationError(f"Protected artifact is missing: {candidate}")
        actual = sha256_file(candidate)
        if actual != artifact["sha256"]:
            raise ConfigurationError(f"Protected artifact checksum mismatch: {candidate}")


def verify_prepared_run(run_directory: Path | str) -> Mapping[str, Any]:
    """Verify manifest, protected artifacts, lifecycle, and pristine output."""

    run_path = Path(run_directory).expanduser().resolve()
    manifest = _read_manifest(run_path)
    if manifest.get("run_id") != run_path.name:
        raise ConfigurationError(
            f"Run directory name does not match manifest run_id: {run_path}"
        )
    _verify_protected_artifacts(run_path, manifest)

    events = _read_events(run_path / "events.jsonl")
    if events[-1]["event"] != "prepared":
        raise ConfigurationError(
            f"Run is not awaiting its first execution; last event is {events[-1]['event']!r}."
        )
    output_directory = run_path / "output"
    if not output_directory.is_dir():
        raise ConfigurationError(f"Run output directory is missing: {output_directory}")
    if any(output_directory.iterdir()):
        raise ConfigurationError(
            f"Run output directory is not empty and will not be overwritten: {output_directory}"
        )
    for forbidden in (
        run_path / "result.json",
        run_path / "output-inventory.json",
        run_path / "logs" / "deformetrica.log",
    ):
        if forbidden.exists():
            raise ConfigurationError(f"Execution artifact already exists: {forbidden}")
    return manifest


def _probe_backend_environment(config: Mapping[str, Any]) -> Mapping[str, Any]:
    launcher = config["runtime"]["launcher"]
    packages = ("deformetrica", "torch", "pykeops", "numpy", "scipy")
    script = (
        "import importlib.metadata as m, json, platform, sys\n"
        f"names={packages!r}\n"
        "versions={}\n"
        "for name in names:\n"
        "    try: versions[name]=m.version(name)\n"
        "    except m.PackageNotFoundError: versions[name]=None\n"
        "print(json.dumps({'python':sys.version.replace('\\n',' '),"
        "'python_executable':sys.executable,'platform':platform.platform(),"
        "'packages':versions}, sort_keys=True))\n"
    )

    container_identity: Mapping[str, Any] | None = None
    if launcher["type"] == "wsl":
        python_executable = str(PurePosixPath(launcher["executable"]).parent / "python")
        argv = [
            "wsl.exe",
            "-d",
            launcher["distribution"],
            "--",
            python_executable,
            "-c",
            script,
        ]
    elif launcher["type"] == "container":
        engine = launcher["engine"]
        image = launcher["image"]
        inspected = subprocess.run(
            [engine, "image", "inspect", image],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if inspected.returncode != 0:
            raise ConfigurationError(
                "Could not inspect the Deformetrica container image before execution: "
                f"{inspected.stderr.strip() or inspected.stdout.strip()}"
            )
        try:
            images = json.loads(inspected.stdout)
            image_data = images[0]
            container_identity = {
                "engine": engine,
                "configured_image": image,
                "image_id": image_data["Id"],
                "repo_digests": image_data.get("RepoDigests") or [],
            }
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ConfigurationError(
                "Container image inspection did not return the expected JSON."
            ) from error
        argv = [
            engine,
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--tmpfs=/tmp:rw,exec,nosuid,size=256m",
            "--entrypoint",
            "python",
            image,
            "-c",
            script,
        ]
    else:
        executable = Path(launcher["executable"])
        candidate = executable.parent / ("python.exe" if os.name == "nt" else "python")
        if not executable.is_absolute() or not candidate.is_file():
            return {
                "probe_status": "not_available",
                "reason": "Native executable is PATH-resolved or has no adjacent Python.",
            }
        argv = [str(candidate), "-c", script]

    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise ConfigurationError(
            "Could not probe the Deformetrica environment before execution: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ConfigurationError(
            "Deformetrica environment probe did not return valid JSON."
        ) from error
    if value.get("packages", {}).get("deformetrica") != REFERENCE_DEFORMETRICA_VERSION:
        raise ConfigurationError(
            f"Reference execution requires Deformetrica {REFERENCE_DEFORMETRICA_VERSION}, got "
            f"{value.get('packages', {}).get('deformetrica')!r}."
        )
    if container_identity is not None:
        value["container"] = container_identity
    return {"probe_status": "verified", **value}


def parse_convergence(log_path: Path, csv_path: Path) -> int:
    rows: list[list[float | int]] = []
    current_iteration: int | None = None
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            iteration_match = ITERATION_RE.search(line)
            if iteration_match:
                current_iteration = int(iteration_match.group(1))
            match = CONVERGENCE_RE.search(line)
            if match:
                rows.append(
                    [
                        current_iteration if current_iteration is not None else len(rows),
                        float(match.group(1)),
                        float(match.group(2)),
                        float(match.group(3)),
                    ]
                )
    with csv_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["iteration", "log_likelihood", "attachment", "regularity"])
        writer.writerows(rows)
    return len(rows)


def _inventory_outputs(run_directory: Path) -> Mapping[str, Any]:
    output_directory = run_directory / "output"
    files = sorted(path for path in output_directory.rglob("*") if path.is_file())
    records = [
        {
            "path": path.relative_to(output_directory).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    inventory_path = run_directory / "output-inventory.json"
    _write_json_exclusive(
        inventory_path,
        {
            "inventory_version": "0.1",
            "created_at": utc_now(),
            "files": records,
        },
    )
    return {
        "file_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "inventory_path": "output-inventory.json",
        "inventory_sha256": sha256_file(inventory_path),
    }


def _checkpoint_summary(run_directory: Path) -> Mapping[str, Any]:
    checkpoint_path = run_directory / EXECUTION_CHECKPOINT_PATH
    summary: dict[str, Any] = {
        "available": checkpoint_path.is_file(),
        "path": EXECUTION_CHECKPOINT_PATH.as_posix(),
    }
    if checkpoint_path.is_file():
        summary.update(
            {
                "bytes": checkpoint_path.stat().st_size,
                "sha256": sha256_file(checkpoint_path),
            }
        )
    return summary


def _read_output_inventory(
    run_directory: Path,
    result: Mapping[str, Any],
) -> tuple[Path, Mapping[str, Any]]:
    outputs = result.get("outputs")
    if not isinstance(outputs, dict):
        raise ConfigurationError("Source result does not contain an outputs object.")
    inventory_path = _resolve_run_artifact(
        run_directory,
        outputs.get("inventory_path", "output-inventory.json"),
        "Output inventory",
    )
    if not inventory_path.is_file():
        raise ConfigurationError(f"Source output inventory is missing: {inventory_path}")
    expected_digest = outputs.get("inventory_sha256")
    if not isinstance(expected_digest, str) or sha256_file(inventory_path) != expected_digest:
        raise ConfigurationError(
            f"Source output inventory checksum does not match result.json: {inventory_path}"
        )
    inventory = _read_json_object(inventory_path, "Output inventory")
    if not isinstance(inventory.get("files"), list):
        raise ConfigurationError("Source output inventory does not contain a files array.")
    return inventory_path, inventory


def _load_resume_provenance(run_directory: Path) -> Mapping[str, Any] | None:
    provenance_path = run_directory / RESUME_PROVENANCE_PATH
    if not provenance_path.exists():
        return None
    provenance = _read_json_object(provenance_path, "Resume provenance")
    _validate_resume_schema(provenance)
    checkpoint = provenance["checkpoint"]
    staged_path = _resolve_run_artifact(
        run_directory,
        checkpoint["staged_path"],
        "Protected resume checkpoint",
    )
    if not staged_path.is_file():
        raise ConfigurationError(f"Protected resume checkpoint is missing: {staged_path}")
    if staged_path.stat().st_size != checkpoint["bytes"]:
        raise ConfigurationError(f"Protected resume checkpoint size mismatch: {staged_path}")
    if sha256_file(staged_path) != checkpoint["sha256"]:
        raise ConfigurationError(f"Protected resume checkpoint checksum mismatch: {staged_path}")
    return provenance


def _terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _log_reports_keyboard_interrupt(log_path: Path) -> bool:
    if not log_path.is_file():
        return False
    with log_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - 65536))
        tail = handle.read().decode("utf-8", errors="replace")
    return any(line.strip() == "KeyboardInterrupt" for line in tail.splitlines())


def execute_run(run_directory: Path | str) -> int:
    """Execute a prepared run exactly once and record append-only lifecycle evidence."""

    run_path = Path(run_directory).expanduser().resolve()
    manifest = verify_prepared_run(run_path)
    config = manifest["effective_config"]
    ensure_launcher_available(config)
    environment_probe = _probe_backend_environment(config)
    resume_provenance = _load_resume_provenance(run_path)
    command = build_command(config, run_path)
    event_path = run_path / "events.jsonl"
    log_path = run_path / "logs" / "deformetrica.log"
    started_at = utc_now()
    start_time = time.monotonic()
    _append_event(
        event_path,
        {
            "event": "started",
            "command": command.as_manifest(),
            "backend_environment": environment_probe,
        },
    )

    return_code = 1
    execution_error: str | None = None
    interrupted = False
    process: subprocess.Popen[str] | None = None
    try:
        if resume_provenance is not None:
            checkpoint = resume_provenance["checkpoint"]
            _copy_and_verify(
                run_path / RESUME_CHECKPOINT_PATH,
                run_path / EXECUTION_CHECKPOINT_PATH,
                checkpoint["sha256"],
            )
        environment = os.environ.copy()
        environment.update(command.environment)
        process_group_options: dict[str, Any]
        if os.name == "nt":
            process_group_options = {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
            }
        else:
            process_group_options = {"start_new_session": True}
        with log_path.open("x", encoding="utf-8", newline="\n") as log_handle:
            process = subprocess.Popen(
                list(command.argv),
                cwd=command.working_directory,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **process_group_options,
            )
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                log_handle.write(line)
            return_code = process.wait()
    except KeyboardInterrupt:
        interrupted = True
        return_code = 130
        execution_error = "KeyboardInterrupt: interrupted by user"
        _terminate_process(process)
    except Exception as error:
        execution_error = f"{type(error).__name__}: {error}"
        _terminate_process(process)

    ended_at = utc_now()
    duration_seconds = round(time.monotonic() - start_time, 6)
    if (
        return_code != 0
        and execution_error is None
        and _log_reports_keyboard_interrupt(log_path)
    ):
        interrupted = True
        execution_error = "Backend process reported KeyboardInterrupt"
    convergence_rows = 0
    if log_path.is_file():
        convergence_rows = parse_convergence(
            log_path,
            run_path / "logs" / "convergence.csv",
        )
    output_summary = _inventory_outputs(run_path)
    checkpoint_summary = _checkpoint_summary(run_path)
    if interrupted:
        status = "interrupted"
    else:
        status = "completed" if return_code == 0 and execution_error is None else "failed"
    result = {
        "result_version": "0.1",
        "run_id": manifest["run_id"],
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
        "return_code": return_code,
        "execution_error": execution_error,
        "convergence_rows": convergence_rows,
        "outputs": output_summary,
        "checkpoint": checkpoint_summary,
        "backend_environment": environment_probe,
        "command": command.as_manifest(),
    }
    if resume_provenance is not None:
        result["resume"] = resume_provenance
    _write_json_exclusive(run_path / "result.json", result)
    _append_event(
        event_path,
        {
            "event": status,
            "return_code": return_code,
            "duration_seconds": duration_seconds,
            "checkpoint": checkpoint_summary,
        },
    )
    if execution_error is not None and not interrupted:
        raise ConfigurationError(f"Reference backend execution failed: {execution_error}")
    return return_code


def recover_run(
    run_directory: Path | str,
    *,
    reason: str,
    confirm_process_stopped: bool = False,
) -> Mapping[str, Any]:
    """Finalize an abandoned started run as interrupted without executing anything."""

    if not confirm_process_stopped:
        raise ConfigurationError(
            "Recovery requires --confirm-process-stopped. Confirm this only after checking "
            "that no Deformetrica process is still writing to the run."
        )
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ConfigurationError("Recovery requires a non-empty reason.")

    run_path = Path(run_directory).expanduser().resolve()
    manifest = _read_manifest(run_path)
    _verify_protected_artifacts(run_path, manifest)
    events = _read_events(run_path / "events.jsonl")
    if events[-1]["event"] != "started":
        raise ConfigurationError(
            "Only an abandoned run whose latest event is 'started' can be recovered; "
            f"latest event is {events[-1]['event']!r}."
        )
    for forbidden in (run_path / "result.json", run_path / "output-inventory.json"):
        if forbidden.exists():
            raise ConfigurationError(
                f"Recovery will not replace an existing terminal artifact: {forbidden}"
            )

    log_path = run_path / "logs" / "deformetrica.log"
    convergence_rows = 0
    if log_path.is_file():
        convergence_rows = parse_convergence(
            log_path,
            run_path / "logs" / "convergence.csv",
        )
    output_summary = _inventory_outputs(run_path)
    checkpoint_summary = _checkpoint_summary(run_path)
    ended_at = utc_now()
    started_event = events[-1]
    execution_error = f"Manual recovery after an unclean stop: {normalized_reason}"
    result = {
        "result_version": "0.1",
        "run_id": manifest["run_id"],
        "status": "interrupted",
        "started_at": started_event["timestamp"],
        "ended_at": ended_at,
        "duration_seconds": None,
        "return_code": None,
        "execution_error": execution_error,
        "convergence_rows": convergence_rows,
        "outputs": output_summary,
        "checkpoint": checkpoint_summary,
        "backend_environment": started_event.get("backend_environment"),
        "command": started_event.get("command"),
        "recovery": {
            "recorded_at": ended_at,
            "reason": normalized_reason,
            "process_stopped_confirmed": True,
        },
    }
    _write_json_exclusive(run_path / "result.json", result)
    _append_event(
        run_path / "events.jsonl",
        {
            "event": "interrupted",
            "return_code": None,
            "duration_seconds": None,
            "checkpoint": checkpoint_summary,
            "recovery_reason": normalized_reason,
        },
    )
    return result


def prepare_resume_run(
    source_run_directory: Path | str,
    *,
    run_id: str | None = None,
) -> Path:
    """Prepare an immutable successor from an inventoried failed/interrupted checkpoint."""

    source_run = Path(source_run_directory).expanduser().resolve()
    source_manifest = _read_manifest(source_run)
    if source_manifest.get("run_id") != source_run.name:
        raise ConfigurationError(
            "Source run directory name does not match its manifest run_id: "
            f"{source_run}"
        )
    _verify_protected_artifacts(source_run, source_manifest)
    events = _read_events(source_run / "events.jsonl")
    terminal_status = events[-1]["event"]
    if terminal_status not in RESUMABLE_STATES:
        raise ConfigurationError(
            "Resume requires a failed or interrupted source run; "
            f"latest event is {terminal_status!r}."
        )
    source_result_path = source_run / "result.json"
    source_result = _read_json_object(source_result_path, "Source result")
    if source_result.get("status") != terminal_status:
        raise ConfigurationError(
            "Source result status does not match the terminal lifecycle event."
        )
    if source_result.get("run_id") != source_manifest["run_id"]:
        raise ConfigurationError("Source result run_id does not match the source manifest.")
    if source_result.get("return_code") != events[-1].get("return_code"):
        raise ConfigurationError(
            "Source result return code does not match the terminal lifecycle event."
        )
    backend_environment = source_result.get("backend_environment")
    source_packages = (
        backend_environment.get("packages")
        if isinstance(backend_environment, dict)
        else None
    )
    source_backend_version = (
        source_packages.get("deformetrica") if isinstance(source_packages, dict) else None
    )
    if source_backend_version != REFERENCE_DEFORMETRICA_VERSION:
        raise ConfigurationError(
            "Resume requires source evidence from Deformetrica "
            f"{REFERENCE_DEFORMETRICA_VERSION}; got {source_backend_version!r}."
        )
    inventory_path, inventory = _read_output_inventory(source_run, source_result)
    checkpoint_records = [
        record
        for record in inventory["files"]
        if isinstance(record, dict)
        and record.get("path") == EXECUTION_CHECKPOINT_PATH.name
    ]
    if len(checkpoint_records) != 1:
        raise ConfigurationError(
            "The source run has no unique inventoried Deformetrica checkpoint; it cannot "
            "be resumed. A run stopped before its first save may legitimately have none."
        )
    checkpoint_record = checkpoint_records[0]
    checkpoint_path = _resolve_run_artifact(
        source_run,
        EXECUTION_CHECKPOINT_PATH.as_posix(),
        "Source checkpoint",
    )
    if not checkpoint_path.is_file() or checkpoint_path.stat().st_size < 1:
        raise ConfigurationError(f"Source checkpoint is missing or empty: {checkpoint_path}")
    if checkpoint_path.stat().st_size != checkpoint_record.get("bytes"):
        raise ConfigurationError(
            f"Source checkpoint size differs from its inventory: {checkpoint_path}"
        )
    checkpoint_hash = sha256_file(checkpoint_path)
    if checkpoint_hash != checkpoint_record.get("sha256"):
        raise ConfigurationError(
            f"Source checkpoint checksum differs from its inventory: {checkpoint_path}"
        )

    output_root = source_run.parent
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    resolved_run_id = normalize_run_id(
        run_id or f"{source_manifest['run_id']}-resume-{stamp}"
    )
    final_directory = output_root / resolved_run_id
    if final_directory.exists():
        raise ConfigurationError(f"Run directory already exists: {final_directory}")
    temp_directory = output_root / f".diffeoforge-preparing-{resolved_run_id}-{uuid4().hex}"
    temp_directory.mkdir(exist_ok=False)
    try:
        for relative in ("input", "config", "engine", "output", "logs", "resume"):
            (temp_directory / relative).mkdir(parents=True, exist_ok=False)

        copied_artifacts: list[Path] = []
        for artifact in source_manifest["protected_artifacts"]:
            relative = PurePosixPath(artifact["path"])
            if relative.as_posix() == "engine/optimization_parameters.xml":
                continue
            if relative.parts and relative.parts[0] == "resume":
                continue
            source = _resolve_run_artifact(source_run, artifact["path"], "Source artifact")
            destination = temp_directory.joinpath(*relative.parts)
            _copy_and_verify(source, destination, artifact["sha256"])
            copied_artifacts.append(destination)

        optimization_path = temp_directory / "engine" / "optimization_parameters.xml"
        generate_resume_optimization_file(
            source_manifest["effective_config"],
            optimization_path,
        )
        staged_checkpoint = temp_directory / RESUME_CHECKPOINT_PATH
        _copy_and_verify(checkpoint_path, staged_checkpoint, checkpoint_hash)

        provenance = {
            "resume_version": RESUME_PROVENANCE_VERSION,
            "created_at": utc_now(),
            "source_run": {
                "run_id": source_manifest["run_id"],
                "path": str(source_run),
                "terminal_status": terminal_status,
            },
            "source_manifest": {
                "path": "manifest.json",
                "sha256": sha256_file(source_run / "manifest.json"),
            },
            "source_result": {
                "path": "result.json",
                "sha256": sha256_file(source_result_path),
            },
            "source_output_inventory": {
                "path": inventory_path.relative_to(source_run).as_posix(),
                "sha256": sha256_file(inventory_path),
            },
            "checkpoint": {
                "source_path": str(checkpoint_path),
                "staged_path": RESUME_CHECKPOINT_PATH.as_posix(),
                "execution_path": EXECUTION_CHECKPOINT_PATH.as_posix(),
                "bytes": checkpoint_path.stat().st_size,
                "sha256": checkpoint_hash,
            },
            "semantics": {
                "backend_id": BACKEND_ID,
                "backend_version": REFERENCE_DEFORMETRICA_VERSION,
                "restored": ["current_parameters", "current_iteration"],
                "reinitialized": [
                    "objective_baseline",
                    "gradient",
                    "line_search_step_sizes",
                ],
                "trajectory_continuity": "not_guaranteed",
            },
        }
        _validate_resume_schema(provenance)
        provenance_path = temp_directory / RESUME_PROVENANCE_PATH
        _write_json_exclusive(provenance_path, provenance)

        protected_paths = [
            *copied_artifacts,
            optimization_path,
            staged_checkpoint,
            provenance_path,
        ]
        config = source_manifest["effective_config"]
        command_preview = build_command(config, final_directory)
        manifest = {
            "manifest_version": RUN_MANIFEST_VERSION,
            "run_id": resolved_run_id,
            "created_at": utc_now(),
            "project": source_manifest["project"],
            "source_config": source_manifest["source_config"],
            "backend": source_manifest["backend"],
            "effective_config": config,
            "input_count": source_manifest["input_count"],
            "inputs": source_manifest["inputs"],
            "protected_artifacts": [
                _artifact_record(temp_directory, path) for path in protected_paths
            ],
            "command_preview": command_preview.as_manifest(),
            "preparation_environment": preparation_environment(),
            "immutability_contract": {
                "manifest": "write-once with SHA-256 sidecar",
                "protected_artifacts": "verified before execution",
                "events": "append-only JSON Lines",
                "output": "must be empty before first execution",
                "run_directory": "never overwritten or reused",
            },
        }
        _validate_manifest_schema(manifest)
        manifest_path = temp_directory / "manifest.json"
        _write_json_exclusive(manifest_path, manifest)
        _write_text_exclusive(
            temp_directory / "manifest.sha256",
            f"{sha256_file(manifest_path)}  manifest.json\n",
        )
        _append_event(
            temp_directory / "events.jsonl",
            {
                "event": "prepared",
                "run_id": resolved_run_id,
                "resume_from": {
                    "run_id": source_manifest["run_id"],
                    "terminal_status": terminal_status,
                    "checkpoint_sha256": checkpoint_hash,
                },
            },
        )
        temp_directory.rename(final_directory)
    except Exception:
        _safe_cleanup_temporary_run(temp_directory, output_root)
        raise
    return final_directory


def run_status(run_directory: Path | str) -> Mapping[str, Any]:
    """Return the latest lifecycle state without modifying the run."""

    run_path = Path(run_directory).expanduser().resolve()
    manifest = _read_manifest(run_path)
    events = _read_events(run_path / "events.jsonl")
    result_path = run_path / "result.json"
    result = None
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ConfigurationError(f"Run result is not valid JSON: {result_path}") from error
    return {
        "run_id": manifest["run_id"],
        "run_directory": str(run_path),
        "status": events[-1]["event"],
        "event_count": len(events),
        "result": result,
    }

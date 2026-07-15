"""Prepare, verify, and execute immutable DiffeoForge run directories."""

from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
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
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
CONVERGENCE_RE = re.compile(
    rf"Log-likelihood\s*=\s*({NUMBER}).*?attachment\s*=\s*({NUMBER})"
    rf".*?regularity\s*=\s*({NUMBER})"
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-._")
    if not cleaned:
        raise ConfigurationError("Project or run name is empty after normalization.")
    return cleaned


def default_run_id(config: Mapping[str, Any]) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{_slug(config['project']['name'])}"


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


def _effective_config(
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


def _input_record(
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


def prepare_run(
    config_path: Path | str,
    *,
    run_id: str | None = None,
    output_directory: Path | str | None = None,
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
    output_root.mkdir(parents=True, exist_ok=True)
    resolved_run_id = _slug(run_id or default_run_id(config))
    final_directory = output_root / resolved_run_id
    if final_directory.exists():
        raise ConfigurationError(f"Run directory already exists: {final_directory}")

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
            _input_record(
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
            input_records.append(_input_record("subject", source, staged_relative, metadata))

        source_config_copy = config_directory / "source-config.yaml"
        shutil.copy2(source_config, source_config_copy)
        effective = _effective_config(
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
                "sha256": sha256_file(source_config),
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

        temp_directory.rename(final_directory)
    except Exception:
        _safe_cleanup_temporary_run(temp_directory, output_root)
        raise
    return final_directory


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


def verify_prepared_run(run_directory: Path | str) -> Mapping[str, Any]:
    """Verify manifest, protected artifacts, lifecycle, and pristine output."""

    run_path = Path(run_directory).expanduser().resolve()
    manifest = _read_manifest(run_path)
    if manifest.get("run_id") != run_path.name:
        raise ConfigurationError(
            f"Run directory name does not match manifest run_id: {run_path}"
        )
    for artifact in manifest["protected_artifacts"]:
        relative = PurePosixPath(artifact["path"])
        candidate = run_path.joinpath(*relative.parts).resolve()
        if not candidate.is_relative_to(run_path):
            raise ConfigurationError(f"Protected artifact escapes run directory: {relative}")
        if not candidate.is_file():
            raise ConfigurationError(f"Protected artifact is missing: {candidate}")
        actual = sha256_file(candidate)
        if actual != artifact["sha256"]:
            raise ConfigurationError(
                f"Protected artifact checksum mismatch: {candidate}"
            )

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
    if value.get("packages", {}).get("deformetrica") != "4.3.0":
        raise ConfigurationError(
            "Reference execution requires Deformetrica 4.3.0, got "
            f"{value.get('packages', {}).get('deformetrica')!r}."
        )
    return {"probe_status": "verified", **value}


def parse_convergence(log_path: Path, csv_path: Path) -> int:
    rows: list[list[float | int]] = []
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = CONVERGENCE_RE.search(line)
            if match:
                rows.append(
                    [
                        len(rows),
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


def execute_run(run_directory: Path | str) -> int:
    """Execute a prepared run exactly once and record append-only lifecycle evidence."""

    run_path = Path(run_directory).expanduser().resolve()
    manifest = verify_prepared_run(run_path)
    config = manifest["effective_config"]
    ensure_launcher_available(config)
    environment_probe = _probe_backend_environment(config)
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
    process: subprocess.Popen[str] | None = None
    try:
        environment = os.environ.copy()
        environment.update(command.environment)
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
            )
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                log_handle.write(line)
            return_code = process.wait()
    except Exception as error:
        execution_error = f"{type(error).__name__}: {error}"
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    ended_at = utc_now()
    duration_seconds = round(time.monotonic() - start_time, 6)
    convergence_rows = 0
    if log_path.is_file():
        convergence_rows = parse_convergence(
            log_path,
            run_path / "logs" / "convergence.csv",
        )
    output_summary = _inventory_outputs(run_path)
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
        "backend_environment": environment_probe,
        "command": command.as_manifest(),
    }
    _write_json_exclusive(run_path / "result.json", result)
    _append_event(
        event_path,
        {
            "event": status,
            "return_code": return_code,
            "duration_seconds": duration_seconds,
        },
    )
    if execution_error is not None:
        raise ConfigurationError(f"Reference backend execution failed: {execution_error}")
    return return_code


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

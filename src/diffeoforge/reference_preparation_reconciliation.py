"""Approval-bound read-only reconciliation of reference preparation state."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_preparation_approval import (
    load_saved_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
)
from diffeoforge.runs import verify_prepared_run_against_plan

SCHEMA_VERSION = "0.1"
CHECKS = [
    "approval_request_strict_and_schema_valid",
    "approval_request_matches_external_sha256",
    "embedded_plan_matches_approval_fingerprint",
    "fresh_current_plan_exactly_matches_approved_plan",
    "exact_destination_inspected_without_link_following",
    "exact_private_stage_names_inspected_without_link_following",
    "prepared_candidates_checked_against_approved_plan",
    "observation_repeated_without_state_change",
    "approval_config_and_current_plan_unchanged",
    "no_mutation_performed",
]
SCIENTIFIC_BOUNDARY = (
    "This read-only engineering report binds one exact preparation-only approval to a "
    "fresh current plan and classifies only its exact destination and exact private-stage "
    "names. It never deletes, renames, publishes, resumes, prepares, executes, repairs, or "
    "follows symbolic links. A verified private stage remains unpublished and requires an "
    "explicit future user decision. This report does not prove process liveness, crash "
    "recovery, engine containment, numerical validity, registration quality, convergence, "
    "or biological interpretation."
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _schema() -> Mapping[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "reference-preparation-reconciliation-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate(value: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.path) or "document"
    raise ConfigurationError(
        "Reference preparation reconciliation schema violation at "
        f"{location}: {first.message}"
    )


def validate_reference_preparation_reconciliation(value: Mapping[str, Any]) -> None:
    """Validate one machine-readable reconciliation report."""

    _validate(value)


def serialize_reference_preparation_reconciliation(
    value: Mapping[str, Any],
) -> bytes:
    """Render one validated report as deterministic UTF-8 JSON bytes."""

    _validate(value)
    return (
        json.dumps(dict(value), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _normalize_sha256(value: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError("Expected approval SHA-256 must be a string")
    normalized = value.strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise ConfigurationError(
            "Expected approval SHA-256 must be exactly 64 hexadecimal digits"
        )
    return normalized


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _expected_surface(plan: Mapping[str, Any]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for value in plan["directories"]:
        relative = PurePosixPath(str(value))
        for index in range(1, len(relative.parts) + 1):
            expected[PurePosixPath(*relative.parts[:index]).as_posix()] = "directory"
    for item in plan["protected_files"]:
        relative = PurePosixPath(str(item["path"]))
        for index in range(1, len(relative.parts)):
            expected[PurePosixPath(*relative.parts[:index]).as_posix()] = "directory"
        expected[relative.as_posix()] = "file"
    for name in ("events.jsonl", "manifest.json", "manifest.sha256"):
        expected[name] = "file"
    return dict(sorted(expected.items()))


def _observed_surface(root: Path) -> tuple[dict[str, str], str | None]:
    observed: dict[str, str] = {}
    unsafe: str | None = None

    def visit(directory: Path, relative: PurePosixPath) -> None:
        nonlocal unsafe
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            raise ConfigurationError(
                f"Could not inspect preparation state directory {directory}: {error}"
            ) from error
        for entry in entries:
            child_relative = relative / entry.name
            key = child_relative.as_posix()
            if entry.is_symlink():
                observed[key] = "symbolic_link"
                unsafe = unsafe or key
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    observed[key] = "directory"
                    visit(Path(entry.path), child_relative)
                elif entry.is_file(follow_symlinks=False):
                    observed[key] = "file"
                else:
                    observed[key] = "other"
                    unsafe = unsafe or key
            except OSError as error:
                raise ConfigurationError(
                    f"Could not classify preparation state path {entry.path}: {error}"
                ) from error

    visit(root, PurePosixPath())
    return dict(sorted(observed.items())), unsafe


def _surface_difference(
    expected: Mapping[str, str],
    observed: Mapping[str, str],
) -> str | None:
    for path in sorted(set(expected) | set(observed)):
        wanted = expected.get(path)
        found = observed.get(path)
        if wanted != found:
            return f"Surface differs at {path!r}: expected {wanted!r}, observed {found!r}."
    return None


def _inspect_real_directory(
    path: Path,
    plan: Mapping[str, Any],
    *,
    verified_status: str,
) -> dict[str, Any]:
    observed, unsafe = _observed_surface(path)
    if unsafe is not None:
        return {
            "path": str(path),
            "status": "unsafe_content_link",
            "reason": f"Symbolic or unsupported content was not followed: {unsafe}",
            "manifest_sha256": None,
            "engine_execution_started": None,
        }
    difference = _surface_difference(_expected_surface(plan), observed)
    if difference is not None:
        return {
            "path": str(path),
            "status": "incomplete_or_mismatched",
            "reason": difference,
            "manifest_sha256": None,
            "engine_execution_started": None,
        }
    try:
        verify_prepared_run_against_plan(path, plan)
        manifest_path = path / "manifest.json"
        return {
            "path": str(path),
            "status": verified_status,
            "reason": (
                "Prepared bytes, manifest, lifecycle, pristine output, and complete "
                "surface exactly match the approved plan."
            ),
            "manifest_sha256": sha256_file(manifest_path),
            "engine_execution_started": False,
        }
    except (ConfigurationError, OSError, TypeError, ValueError) as error:
        return {
            "path": str(path),
            "status": "incomplete_or_mismatched",
            "reason": str(error),
            "manifest_sha256": None,
            "engine_execution_started": None,
        }


def _inspect_destination(path: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    if path.is_symlink():
        return {
            "path": str(path),
            "status": "unsafe_link",
            "reason": "The approved destination is a symbolic link and was not followed.",
            "manifest_sha256": None,
            "engine_execution_started": None,
        }
    if not path.exists():
        return {
            "path": str(path),
            "status": "absent",
            "reason": "The exact approved destination does not exist.",
            "manifest_sha256": None,
            "engine_execution_started": None,
        }
    if not path.is_dir():
        return {
            "path": str(path),
            "status": "not_directory",
            "reason": "The exact approved destination exists but is not a directory.",
            "manifest_sha256": None,
            "engine_execution_started": None,
        }
    return _inspect_real_directory(
        path,
        plan,
        verified_status="verified_prepared_not_executed",
    )


def _private_pattern(run_id: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\.diffeoforge-preparing-{re.escape(run_id)}-([0-9a-f]{{32}})$"
    )


def _inspect_private_stages(
    destination: Path,
    plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    parent = destination.parent
    if not parent.exists():
        return []
    if parent.is_symlink() or not parent.is_dir():
        raise ConfigurationError(
            f"Approved destination parent is not a real directory: {parent}"
        )
    pattern = _private_pattern(str(plan["run"]["run_id"]))
    try:
        with os.scandir(parent) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as error:
        raise ConfigurationError(
            f"Could not inspect approved destination parent {parent}: {error}"
        ) from error
    stages: list[dict[str, Any]] = []
    for entry in entries:
        match = pattern.fullmatch(entry.name)
        if match is None:
            continue
        path = Path(entry.path).absolute()
        if entry.is_symlink():
            inspected = {
                "path": str(path),
                "status": "unsafe_link",
                "reason": "Matching private-stage path is a symbolic link and was not followed.",
                "manifest_sha256": None,
                "engine_execution_started": None,
            }
        elif not entry.is_dir(follow_symlinks=False):
            inspected = {
                "path": str(path),
                "status": "not_directory",
                "reason": "Matching private-stage path is not a directory.",
                "manifest_sha256": None,
                "engine_execution_started": None,
            }
        else:
            inspected = _inspect_real_directory(
                path,
                plan,
                verified_status="verified_complete_unpublished",
            )
        stages.append(
            {
                "directory_name": entry.name,
                "token": match.group(1),
                **inspected,
            }
        )
    return stages


def _observe(plan: Mapping[str, Any]) -> dict[str, Any]:
    destination = Path(str(plan["run"]["destination"])).absolute()
    return {
        "destination": _inspect_destination(destination, plan),
        "private_stages": _inspect_private_stages(destination, plan),
    }


def reconcile_reference_preparation(
    request_path: Path | str,
    *,
    current_config_path: Path | str,
    expected_request_sha256: str,
) -> dict[str, Any]:
    """Classify exact approved preparation state without changing it."""

    source = Path(request_path).expanduser().resolve()
    current_config = Path(current_config_path).expanduser().resolve()
    expected_hash = _normalize_sha256(expected_request_sha256)
    request, request_bytes = load_saved_reference_preparation_approval(source)
    observed_hash = _sha256_bytes(request_bytes)
    if observed_hash != expected_hash:
        raise ConfigurationError(
            "Saved approval request does not match the independently recorded SHA-256; "
            f"expected {expected_hash}, observed {observed_hash}"
        )
    config_bytes = current_config.read_bytes()
    approved_plan = request["plan"]
    approved_fingerprint = reference_preparation_plan_fingerprint(approved_plan)
    if approved_fingerprint != request["approval"]["approved_plan_fingerprint"]:
        raise ConfigurationError(
            "Embedded plan does not match the approval fingerprint"
        )
    run_id = str(approved_plan["run"]["run_id"])
    fresh_plan = plan_reference_preparation(
        current_config,
        run_id=run_id,
        allow_existing_destination=True,
    )
    fresh_fingerprint = reference_preparation_plan_fingerprint(fresh_plan)
    if fresh_plan != approved_plan or fresh_fingerprint != approved_fingerprint:
        raise ConfigurationError(
            "Fresh current reference preparation plan does not exactly match the approved "
            f"plan; approved {approved_fingerprint}, current {fresh_fingerprint}"
        )

    first = _observe(approved_plan)
    second = _observe(approved_plan)
    if first != second:
        raise ConfigurationError(
            "Reference preparation state changed during read-only inspection; retry after "
            "the state is stable"
        )
    final_plan = plan_reference_preparation(
        current_config,
        run_id=run_id,
        allow_existing_destination=True,
    )
    if final_plan != approved_plan:
        raise ConfigurationError(
            "Current reference preparation plan changed during read-only inspection"
        )
    if source.read_bytes() != request_bytes or current_config.read_bytes() != config_bytes:
        raise ConfigurationError(
            "Approval request or current config changed during read-only inspection"
        )

    destination_status = first["destination"]["status"]
    private_stages = first["private_stages"]
    if destination_status == "absent" and not private_stages:
        status = "clear_to_prepare"
        action_required = False
    elif destination_status == "verified_prepared_not_executed" and not private_stages:
        status = "published_prepared_not_executed_verified"
        action_required = False
    else:
        status = "attention_required"
        action_required = True

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "action_required": action_required,
        "mutation_performed": False,
        "approval_request": {
            "path": str(source),
            "bytes": len(request_bytes),
            "sha256": observed_hash,
            "expected_sha256": expected_hash,
        },
        "approved_plan": {
            "canonical_fingerprint": approved_fingerprint,
            "run_id": run_id,
            "destination": str(approved_plan["run"]["destination"]),
            "subjects": int(approved_plan["input_count"]["subjects"]),
            "protected_files": int(approved_plan["protected_file_count"]),
        },
        "current_plan": {
            "config_path": str(current_config),
            "config_sha256": _sha256_bytes(config_bytes),
            "canonical_fingerprint": fresh_fingerprint,
            "exactly_matches_approved": True,
        },
        "destination": first["destination"],
        "private_stages": private_stages,
        "state_stable_across_observations": True,
        "checks": CHECKS,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _validate(report)
    return report

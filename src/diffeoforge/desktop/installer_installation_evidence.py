"""Create and verify evidence for one isolated installer lifecycle observation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath, PureWindowsPath

from jsonschema import Draft202012Validator, FormatChecker

from diffeoforge.desktop.installer_build_evidence import (
    verify_installer_build_evidence,
)

SCHEMA_VERSION = "0.1"
STATUS = (
    "isolated_current_user_install_launch_uninstall_observed_not_signed_"
    "distributable_or_released"
)
TARGET = "windows-x86_64-cpu"
CONTRACT_NAME = "installer-installation-evidence-contract-v0.1.json"
WRAPPER_NAME = "observe_installer_installation.ps1"
EVIDENCE_NAME = "installer-installation-evidence.json"
SIDECAR_NAME = "installer-installation-evidence.sha256"
INSTALL_LOG_NAME = "install.log"
INVENTORY_NAME = "installed-file-inventory.json"
INSTALL_OBSERVATION_NAME = "installer-install-observation.json"
SMOKE_OBSERVATION_NAME = "installed-smoke-observation.json"
UNINSTALL_LOG_NAME = "uninstall.log"
UNINSTALL_OBSERVATION_NAME = "installer-uninstall-observation.json"
COMPLETE_NAMES = frozenset(
    (
        INSTALL_LOG_NAME,
        INVENTORY_NAME,
        INSTALL_OBSERVATION_NAME,
        SMOKE_OBSERVATION_NAME,
        UNINSTALL_LOG_NAME,
        UNINSTALL_OBSERVATION_NAME,
        EVIDENCE_NAME,
        SIDECAR_NAME,
    )
)
EVIDENCE_COPY_NAMES = frozenset(
    (
        "freeze-evidence.json",
        "freeze-evidence.sha256",
        "freeze-dependency-metadata.json",
        "freeze-dependency-metadata.sha256",
        "freeze-sbom.cdx.json",
        "freeze-sbom.cdx.sha256",
    )
)
MISSING_RELEASE_GATES = (
    "administrator_install_observation",
    "authenticode_signature",
    "cpu_numerical_release_validation_on_installed_artifact",
    "crash_and_power_loss_reconciliation",
    "external_usability_evaluation",
    "host_wide_no_network_observation",
    "license_compatibility_review",
    "redistribution_approval",
    "scientific_validation",
    "windows_defender_scan",
)
SCIENTIFIC_BOUNDARY = (
    "This document records one current-user install, installed desktop smoke, and "
    "uninstall observation on an ephemeral GitHub-hosted Windows runner. The exact "
    "unsigned setup was not uploaded or released. Process-specific sampling observed "
    "no desktop-process network connections, but this is not host-wide network "
    "isolation. The observation does not establish license or redistribution approval, "
    "security, administrator-mode behavior, numerical correctness, scientific validity, "
    "usability, production suitability, or public-release readiness."
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_UNINSTALLER_PATTERN = re.compile(r"unins[0-9]{3}\.(?:dat|exe|msg)", re.IGNORECASE)


class InstallerInstallationEvidenceError(RuntimeError):
    """Raised when isolated installer evidence fails closed."""


def _is_symbolic_path(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction is not None and is_junction())


def _reject_symbolic_chain(path: Path, *, label: str) -> None:
    current = path
    while True:
        if current.exists() and _is_symbolic_path(current):
            raise InstallerInstallationEvidenceError(
                f"{label} must not use a symbolic path: {current}"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def _real_file(
    value: Path | str, *, label: str, expected_name: str | None = None
) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_file():
        raise InstallerInstallationEvidenceError(
            f"{label} must be an existing real file: {resolved}"
        )
    if expected_name is not None and resolved.name != expected_name:
        raise InstallerInstallationEvidenceError(f"{label} must be named {expected_name}")
    return resolved


def _real_directory(value: Path | str, *, label: str) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_dir():
        raise InstallerInstallationEvidenceError(
            f"{label} must be an existing real directory: {resolved}"
        )
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _json_file(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InstallerInstallationEvidenceError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise InstallerInstallationEvidenceError(f"{label} must be a JSON object")
    return value


def _expected_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Expected {label} SHA-256 must contain 64 lowercase hex characters")
    return value


def _commit(value: str) -> str:
    if not isinstance(value, str) or _COMMIT_PATTERN.fullmatch(value) is None:
        raise ValueError("source_commit must be a lowercase 40-character Git SHA")
    return value


def _timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise InstallerInstallationEvidenceError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InstallerInstallationEvidenceError(
            f"{label} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise InstallerInstallationEvidenceError(f"{label} must include a timezone")
    parsed.astimezone(UTC)
    return value


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath(
        "desktop-installer-installation-evidence-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: object) -> None:
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise InstallerInstallationEvidenceError(
            f"Installer installation evidence schema violation at {location}: {first.message}"
        )


def _validate_contract(path: Path) -> None:
    contract = _json_file(path, label="Installer installation evidence contract")
    runner = contract.get("runner_boundary")
    prerequisites = contract.get("required_prerequisites")
    execution = contract.get("execution")
    output = contract.get("output")
    if (
        contract.get("schema_version") != SCHEMA_VERSION
        or contract.get("target") != TARGET
        or not isinstance(runner, dict)
        or runner.get("github_actions") is not True
        or runner.get("ephemeral_host_required") is not True
        or runner.get("normal_developer_account_execution") is not False
        or not isinstance(prerequisites, dict)
        or prerequisites.get("build_release_candidate") is not False
        or prerequisites.get("setup_authenticode_status") != "NotSigned"
        or not isinstance(execution, dict)
        or execution.get("application_arguments") != ["--smoke"]
        or execution.get("host_wide_network_isolation_claim") is not False
        or not isinstance(output, dict)
        or output.get("exact_files") != sorted(COMPLETE_NAMES)
        or output.get("overwrite") is not False
        or output.get("offline_reconstruction") is not False
        or output.get("retained_artifact_integrity_verification") is not True
        or output.get("setup_upload") is not False
    ):
        raise InstallerInstallationEvidenceError(
            "Installer installation evidence contract differs"
        )


def _source_inputs(project_file: Path | str) -> tuple[Path, Path, Path, Path]:
    project = _real_file(project_file, label="Project file", expected_name="pyproject.toml")
    repository = project.parent
    contract = _real_file(
        repository / "distribution" / "windows" / CONTRACT_NAME,
        label="Installer installation evidence contract",
        expected_name=CONTRACT_NAME,
    )
    wrapper = _real_file(
        repository / "tools" / WRAPPER_NAME,
        label="Installer installation observation wrapper",
        expected_name=WRAPPER_NAME,
    )
    _validate_contract(contract)
    return project, repository, contract, wrapper


def _build_context(
    build_evidence_path: Path | str, *, expected_sha256: str
) -> dict[str, object]:
    expected = _expected_sha256(expected_sha256, label="installer build evidence")
    evidence_path = _real_file(
        build_evidence_path,
        label="Installer build evidence",
        expected_name="installer-build-evidence.json",
    )
    document = verify_installer_build_evidence(
        evidence_path, expected_evidence_sha256=expected
    )
    if (
        document.get("distribution_authorized") is not False
        or document.get("release_authorized") is not False
        or document.get("setup_execution_authorized") is not False
        or document.get("compiler_execution", {}).get("setup_authenticode_status")
        != "NotSigned"
        or document.get("compiler_execution", {}).get("setup_execution") is not False
        or document.get("plan", {}).get("release_candidate") is not False
    ):
        raise InstallerInstallationEvidenceError(
            "Installer build evidence does not retain the non-release unsigned boundary"
        )
    setup_record = document["compiler_execution"]["setup"]
    setup = _real_file(setup_record["path"], label="Setup executable")
    if _file_record(setup) != setup_record:
        raise InstallerInstallationEvidenceError("Setup executable differs from build evidence")
    plan_path = _real_file(document["plan"]["path"], label="Installer build plan")
    plan = _json_file(plan_path, label="Installer build plan")
    inputs = plan.get("inputs")
    if not isinstance(inputs, dict):
        raise InstallerInstallationEvidenceError("Installer build plan inputs differ")
    bundle = _real_directory(inputs["bundle"]["directory"], label="Frozen bundle")
    evidence_dir = _real_directory(
        inputs["evidence"]["directory"], label="Six-file evidence directory"
    )
    license_file = _real_file(
        inputs["license"]["path"], label="License file", expected_name="LICENSE"
    )
    return {
        "document": document,
        "path": evidence_path,
        "expected_sha256": expected,
        "setup": setup,
        "bundle": bundle,
        "evidence_directory": evidence_dir,
        "license": license_file,
    }


def verify_installer_installation_prerequisites(
    build_evidence_path: Path | str,
    *,
    expected_build_evidence_sha256: str,
    project_file: Path | str,
    source_commit: str,
) -> dict[str, object]:
    """Reconstruct every retained input before any setup execution is allowed."""
    project, repository, contract, wrapper = _source_inputs(project_file)
    expected_commit = _commit(source_commit)
    context = _build_context(
        build_evidence_path, expected_sha256=expected_build_evidence_sha256
    )
    if context["document"]["observer_source"]["commit_sha"] != expected_commit:
        raise InstallerInstallationEvidenceError(
            "Installer build evidence source commit differs from observer source commit"
        )
    return {
        "source_commit": expected_commit,
        "repository": str(repository),
        "project": _file_record(project),
        "contract": _file_record(contract),
        "wrapper": _file_record(wrapper),
        "build_evidence": _file_record(context["path"]),
        "setup": _file_record(context["setup"]),
        "bundle_directory": str(context["bundle"]),
        "evidence_directory": str(context["evidence_directory"]),
        "license": _file_record(context["license"]),
    }


def _safe_relative(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise InstallerInstallationEvidenceError(f"Unsafe installed path: {relative!r}")
    return relative


def _inventory(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        if _is_symbolic_path(path):
            raise InstallerInstallationEvidenceError(
                f"Installed tree contains a symbolic path: {_safe_relative(path, root)}"
            )
        if path.is_file():
            record = _file_record(path)
            record["path"] = _safe_relative(path, root)
            records.append(record)
        elif not path.is_dir():
            raise InstallerInstallationEvidenceError(
                f"Installed tree contains an unsupported entry: {_safe_relative(path, root)}"
            )
    if not records:
        raise InstallerInstallationEvidenceError("Installed tree contains no files")
    return records


def _inventory_sha256(records: list[dict[str, object]]) -> str:
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def create_installed_file_inventory(
    install_root: Path | str,
    build_evidence_path: Path | str,
    *,
    expected_build_evidence_sha256: str,
    output_file: Path | str,
) -> dict:
    """Inventory and exact-match one installed tree before application launch."""
    root = _real_directory(install_root, label="Installed application root")
    output = Path(output_file).expanduser().absolute()
    _reject_symbolic_chain(output, label="Installed inventory output")
    if output.exists():
        raise InstallerInstallationEvidenceError(
            f"Installed inventory output already exists: {output}"
        )
    if not output.parent.is_dir():
        raise InstallerInstallationEvidenceError(
            f"Installed inventory output parent does not exist: {output.parent}"
        )
    context = _build_context(
        build_evidence_path, expected_sha256=expected_build_evidence_sha256
    )
    installed = _inventory(root)
    observed = {record["path"]: record for record in installed}
    expected: dict[str, dict[str, object]] = {}
    source_inventory = _inventory(context["bundle"])
    for record in source_inventory:
        expected[record["path"]] = record
    for name in sorted(EVIDENCE_COPY_NAMES):
        source = _real_file(context["evidence_directory"] / name, label=f"Evidence {name}")
        record = _file_record(source)
        record["path"] = f"evidence/{name}"
        expected[record["path"]] = record
    license_record = _file_record(context["license"])
    license_record["path"] = "LICENSE.txt"
    expected["LICENSE.txt"] = license_record
    for relative, record in expected.items():
        if observed.get(relative) != record:
            raise InstallerInstallationEvidenceError(
                f"Installed file differs from its exact source: {relative}"
            )
    extras = sorted(set(observed).difference(expected))
    if not extras or any(_UNINSTALLER_PATTERN.fullmatch(name) is None for name in extras):
        raise InstallerInstallationEvidenceError(
            f"Installed tree has unexpected non-source files: {extras}"
        )
    suffixes = {Path(name).suffix.lower() for name in extras}
    if not {".dat", ".exe"}.issubset(suffixes):
        raise InstallerInstallationEvidenceError(
            "Installed tree lacks the expected Inno uninstaller executable/data pair"
        )
    document = {
        "schema_version": SCHEMA_VERSION,
        "status": "installed_tree_observed_before_launch",
        "install_root": str(root),
        "source_bundle": {
            "directory": str(context["bundle"]),
            "file_count": len(source_inventory),
        },
        "records": installed,
        "file_count": len(installed),
        "total_bytes": sum(int(record["bytes"]) for record in installed),
        "inventory_sha256": _inventory_sha256(installed),
        "source_bundle_copy_verified": True,
        "evidence_copies_verified": True,
        "license_copy_verified": True,
        "uninstaller_files": extras,
    }
    output.write_bytes(_json_bytes(document))
    return document


def _phase(path: Path, *, phase: str) -> dict:
    value = _json_file(path, label=f"{phase} observation")
    if value.get("schema_version") != SCHEMA_VERSION or value.get("phase") != phase:
        raise InstallerInstallationEvidenceError(f"{phase} observation identity differs")
    _timestamp(value.get("observed_at"), label=f"{phase} observation time")
    return value


def _record_matches(path: Path, record: object, *, label: str) -> None:
    if not isinstance(record, dict) or _file_record(path) != record:
        raise InstallerInstallationEvidenceError(f"{label} file record differs")


def _sentinel(value: object, *, label: str) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "bytes", "sha256"}
        or not isinstance(value.get("path"), str)
        or not isinstance(value.get("bytes"), int)
        or value["bytes"] < 1
        or not isinstance(value.get("sha256"), str)
        or _SHA256_PATTERN.fullmatch(value["sha256"]) is None
    ):
        raise InstallerInstallationEvidenceError(f"{label} project sentinel differs")
    return value


def _compose_evidence(
    *,
    build_context: dict[str, object],
    project: Path,
    contract: Path,
    wrapper: Path,
    source_commit: str,
    directory: Path,
) -> dict:
    install_path = directory / INSTALL_OBSERVATION_NAME
    smoke_path = directory / SMOKE_OBSERVATION_NAME
    uninstall_path = directory / UNINSTALL_OBSERVATION_NAME
    inventory_path = directory / INVENTORY_NAME
    install_log = directory / INSTALL_LOG_NAME
    uninstall_log = directory / UNINSTALL_LOG_NAME
    install = _phase(install_path, phase="install")
    smoke = _phase(smoke_path, phase="smoke")
    uninstall = _phase(uninstall_path, phase="uninstall")
    inventory = _json_file(inventory_path, label="Installed file inventory")
    _record_matches(install_log, install.get("log"), label="Install log")
    _record_matches(uninstall_log, uninstall.get("log"), label="Uninstall log")
    if (
        install.get("exit_code") != 0
        or install.get("shortcut_verified") is not True
        or install.get("registration_verified") is not True
        or smoke.get("exit_code") != 0
        or smoke.get("arguments") != ["--smoke"]
        or smoke.get("network_scope")
        != "desktop_process_only_not_host_wide_isolation"
        or smoke.get("network_connection_count") != 0
        or uninstall.get("exit_code") != 0
        or uninstall.get("install_root_absent") is not True
        or uninstall.get("shortcut_absent") is not True
        or uninstall.get("registration_absent") is not True
    ):
        raise InstallerInstallationEvidenceError(
            "Installer lifecycle observation did not satisfy the exact contract"
        )
    sentinels = [
        _sentinel(install.get("sentinel_before"), label="Before-install"),
        _sentinel(install.get("sentinel_after"), label="After-install"),
        _sentinel(smoke.get("sentinel_after"), label="After-smoke"),
        _sentinel(uninstall.get("sentinel_after"), label="After-uninstall"),
    ]
    if any(item != sentinels[0] for item in sentinels[1:]):
        raise InstallerInstallationEvidenceError(
            "Project sentinel changed during installer lifecycle observation"
        )
    required_inventory = {
        "file_count",
        "total_bytes",
        "inventory_sha256",
        "source_bundle_copy_verified",
        "evidence_copies_verified",
        "license_copy_verified",
    }
    if not required_inventory.issubset(inventory):
        raise InstallerInstallationEvidenceError("Installed file inventory is incomplete")
    runner = install.get("runner")
    if (
        not isinstance(runner, dict)
        or runner.get("github_actions") is not True
        or runner.get("ephemeral") is not True
        or runner.get("os") != "Windows"
        or runner.get("architecture") != "X64"
        or not isinstance(runner.get("runner_name"), str)
        or not runner["runner_name"]
        or smoke.get("runner") != runner
        or uninstall.get("runner") != runner
    ):
        raise InstallerInstallationEvidenceError("Ephemeral Windows runner identity differs")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "target": TARGET,
        "observed_at": uninstall["observed_at"],
        "observer_source": {
            "commit_sha": source_commit,
            "project": _file_record(project),
            "contract": _file_record(contract),
            "wrapper": _file_record(wrapper),
        },
        "installer_build_evidence": {
            "document": _file_record(build_context["path"]),
            "expected_sha256": build_context["expected_sha256"],
            "setup": _file_record(build_context["setup"]),
        },
        "runner": runner,
        "install": {
            "observation": _file_record(install_path),
            "log": _file_record(install_log),
            "exit_code": 0,
            "install_root": install["install_root"],
            "shortcut_verified": True,
            "registration_verified": True,
        },
        "installed_inventory": {
            "document": _file_record(inventory_path),
            "file_count": inventory["file_count"],
            "total_bytes": inventory["total_bytes"],
            "inventory_sha256": inventory["inventory_sha256"],
            "source_bundle_copy_verified": True,
            "evidence_copies_verified": True,
            "license_copy_verified": True,
        },
        "installed_smoke": {
            "observation": _file_record(smoke_path),
            "exit_code": 0,
            "arguments": ["--smoke"],
            "process_network_connection_count": 0,
            "scope": "desktop_process_only_not_host_wide_isolation",
        },
        "uninstall": {
            "observation": _file_record(uninstall_path),
            "log": _file_record(uninstall_log),
            "exit_code": 0,
            "install_root_absent": True,
            "shortcut_absent": True,
            "registration_absent": True,
        },
        "project_sentinel": {
            "path": sentinels[0]["path"],
            "before_install": {key: sentinels[0][key] for key in ("bytes", "sha256")},
            "after_install": {key: sentinels[1][key] for key in ("bytes", "sha256")},
            "after_smoke": {key: sentinels[2][key] for key in ("bytes", "sha256")},
            "after_uninstall": {key: sentinels[3][key] for key in ("bytes", "sha256")},
        },
        "setup_distribution_authorized": False,
        "release_authorized": False,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "missing_release_gates": list(MISSING_RELEASE_GATES),
    }


def _directory(path: Path | str) -> Path:
    directory = _real_directory(path, label="Installation evidence directory")
    entries = {item.name for item in directory.iterdir()}
    unsafe = [item for item in directory.iterdir() if _is_symbolic_path(item) or not item.is_file()]
    if entries != COMPLETE_NAMES or unsafe:
        raise InstallerInstallationEvidenceError(
            "Installation evidence directory must contain exactly the eight regular files"
        )
    return directory


def _retained_content_matches(
    path: Path, record: object, *, label: str, expected_name: str
) -> None:
    if (
        not isinstance(record, dict)
        or set(record) != {"path", "bytes", "sha256"}
        or not isinstance(record.get("path"), str)
        or PureWindowsPath(record["path"]).name != expected_name
        or record.get("bytes") != path.stat().st_size
        or record.get("sha256") != _sha256_file(path)
    ):
        raise InstallerInstallationEvidenceError(
            f"Retained {label} content record differs"
        )


def _same_file_content(left: object, right: object, *, label: str) -> None:
    def valid(record: object) -> bool:
        return bool(
            isinstance(record, dict)
            and set(record) == {"path", "bytes", "sha256"}
            and isinstance(record.get("path"), str)
            and record["path"]
            and isinstance(record.get("bytes"), int)
            and record["bytes"] >= 0
            and isinstance(record.get("sha256"), str)
            and _SHA256_PATTERN.fullmatch(record["sha256"]) is not None
        )

    if (
        not valid(left)
        or not valid(right)
        or left.get("bytes") != right.get("bytes")
        or left.get("sha256") != right.get("sha256")
    ):
        raise InstallerInstallationEvidenceError(
            f"Retained {label} content identity differs"
        )


def verify_retained_installer_installation_evidence(
    evidence_path: Path | str, *, expected_evidence_sha256: str
) -> dict:
    """Verify the portable eight-file artifact without claiming build reconstruction."""
    expected = _expected_sha256(expected_evidence_sha256, label="installation evidence")
    path = _real_file(
        evidence_path, label="Installer installation evidence", expected_name=EVIDENCE_NAME
    )
    if _sha256_file(path) != expected:
        raise InstallerInstallationEvidenceError(
            "Installer installation evidence differs from the external SHA-256"
        )
    directory = _directory(path.parent)
    document = _json_file(path, label="Installer installation evidence")
    _validate_schema(document)
    sidecar = (directory / SIDECAR_NAME).read_text(encoding="utf-8")
    if sidecar != f"{expected}  {EVIDENCE_NAME}\n":
        raise InstallerInstallationEvidenceError("Installation evidence sidecar differs")

    install_path = directory / INSTALL_OBSERVATION_NAME
    smoke_path = directory / SMOKE_OBSERVATION_NAME
    uninstall_path = directory / UNINSTALL_OBSERVATION_NAME
    inventory_path = directory / INVENTORY_NAME
    install_log = directory / INSTALL_LOG_NAME
    uninstall_log = directory / UNINSTALL_LOG_NAME
    install = _phase(install_path, phase="install")
    smoke = _phase(smoke_path, phase="smoke")
    uninstall = _phase(uninstall_path, phase="uninstall")
    inventory = _json_file(inventory_path, label="Installed file inventory")

    retained_records = (
        (
            install_path,
            document["install"]["observation"],
            "install observation",
            INSTALL_OBSERVATION_NAME,
        ),
        (install_log, document["install"]["log"], "install log", INSTALL_LOG_NAME),
        (
            inventory_path,
            document["installed_inventory"]["document"],
            "installed inventory",
            INVENTORY_NAME,
        ),
        (
            smoke_path,
            document["installed_smoke"]["observation"],
            "smoke observation",
            SMOKE_OBSERVATION_NAME,
        ),
        (
            uninstall_path,
            document["uninstall"]["observation"],
            "uninstall observation",
            UNINSTALL_OBSERVATION_NAME,
        ),
        (
            uninstall_log,
            document["uninstall"]["log"],
            "uninstall log",
            UNINSTALL_LOG_NAME,
        ),
    )
    for retained_path, record, label, name in retained_records:
        _retained_content_matches(
            retained_path, record, label=label, expected_name=name
        )
    if install.get("log") != document["install"]["log"]:
        raise InstallerInstallationEvidenceError("Retained install log binding differs")
    if uninstall.get("log") != document["uninstall"]["log"]:
        raise InstallerInstallationEvidenceError("Retained uninstall log binding differs")

    runner = document["runner"]
    if (
        install.get("runner") != runner
        or smoke.get("runner") != runner
        or uninstall.get("runner") != runner
        or document.get("observed_at") != uninstall.get("observed_at")
        or install.get("exit_code") != document["install"]["exit_code"]
        or smoke.get("exit_code") != document["installed_smoke"]["exit_code"]
        or uninstall.get("exit_code") != document["uninstall"]["exit_code"]
        or install.get("install_root") != document["install"]["install_root"]
        or uninstall.get("install_root") != document["install"]["install_root"]
        or install.get("shortcut_verified") is not True
        or install.get("registration_verified") is not True
        or smoke.get("arguments") != ["--smoke"]
        or smoke.get("network_scope")
        != "desktop_process_only_not_host_wide_isolation"
        or smoke.get("network_connection_count") != 0
        or smoke.get("network_observations") != []
        or uninstall.get("install_root_absent") is not True
        or uninstall.get("shortcut_absent") is not True
        or uninstall.get("registration_absent") is not True
    ):
        raise InstallerInstallationEvidenceError(
            "Retained installer lifecycle phase binding differs"
        )
    _same_file_content(
        install.get("setup"),
        document["installer_build_evidence"]["setup"],
        label="setup",
    )

    sentinels = [
        _sentinel(install.get("sentinel_before"), label="Before-install"),
        _sentinel(install.get("sentinel_after"), label="After-install"),
        _sentinel(smoke.get("sentinel_after"), label="After-smoke"),
        _sentinel(uninstall.get("sentinel_after"), label="After-uninstall"),
    ]
    if any(item != sentinels[0] for item in sentinels[1:]):
        raise InstallerInstallationEvidenceError(
            "Project sentinel changed in retained lifecycle evidence"
        )
    sentinel_document = document["project_sentinel"]
    if (
        sentinel_document.get("path") != sentinels[0]["path"]
        or sentinel_document.get("before_install")
        != {key: sentinels[0][key] for key in ("bytes", "sha256")}
        or sentinel_document.get("after_install")
        != {key: sentinels[1][key] for key in ("bytes", "sha256")}
        or sentinel_document.get("after_smoke")
        != {key: sentinels[2][key] for key in ("bytes", "sha256")}
        or sentinel_document.get("after_uninstall")
        != {key: sentinels[3][key] for key in ("bytes", "sha256")}
    ):
        raise InstallerInstallationEvidenceError(
            "Retained project sentinel summary differs"
        )

    records = inventory.get("records")
    records_are_valid = isinstance(records, list) and all(
        isinstance(record, dict)
        and set(record) == {"path", "bytes", "sha256"}
        and isinstance(record.get("path"), str)
        and bool(record["path"])
        and not PurePosixPath(record["path"]).is_absolute()
        and all(part not in ("", ".", "..") for part in PurePosixPath(record["path"]).parts)
        and isinstance(record.get("bytes"), int)
        and record["bytes"] >= 0
        and isinstance(record.get("sha256"), str)
        and _SHA256_PATTERN.fullmatch(record["sha256"]) is not None
        for record in records
    )
    if (
        not records_are_valid
        or not records
        or inventory.get("file_count") != len(records)
        or inventory.get("total_bytes")
        != sum(record["bytes"] for record in records)
        or inventory.get("inventory_sha256") != _inventory_sha256(records)
        or inventory.get("source_bundle_copy_verified") is not True
        or inventory.get("evidence_copies_verified") is not True
        or inventory.get("license_copy_verified") is not True
    ):
        raise InstallerInstallationEvidenceError(
            "Retained installed-file inventory summary differs"
        )
    inventory_summary = document["installed_inventory"]
    if any(
        inventory_summary.get(key) != inventory.get(key)
        for key in (
            "file_count",
            "total_bytes",
            "inventory_sha256",
            "source_bundle_copy_verified",
            "evidence_copies_verified",
            "license_copy_verified",
        )
    ):
        raise InstallerInstallationEvidenceError(
            "Retained canonical inventory binding differs"
        )
    indexed = {
        record.get("path"): record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("path"), str)
    }
    if len(indexed) != len(records):
        raise InstallerInstallationEvidenceError(
            "Retained installed-file inventory paths differ"
        )
    _same_file_content(
        indexed.get("DiffeoForge.exe"), smoke.get("program"), label="desktop program"
    )
    uninstall_program = uninstall.get("program")
    uninstaller_name = (
        PureWindowsPath(uninstall_program.get("path", "")).name
        if isinstance(uninstall_program, dict)
        else ""
    )
    if uninstaller_name not in inventory.get("uninstaller_files", []):
        raise InstallerInstallationEvidenceError(
            "Retained uninstaller inventory binding differs"
        )
    _same_file_content(
        indexed.get(uninstaller_name), uninstall_program, label="uninstaller"
    )
    return document


def create_installer_installation_evidence(
    evidence_directory: Path | str,
    build_evidence_path: Path | str,
    *,
    expected_build_evidence_sha256: str,
    project_file: Path | str,
    source_commit: str,
) -> dict:
    """Create canonical lifecycle evidence after all three phases completed."""
    project, _repository, contract, wrapper = _source_inputs(project_file)
    commit = _commit(source_commit)
    directory = _real_directory(evidence_directory, label="Installation evidence directory")
    if (directory / EVIDENCE_NAME).exists() or (directory / SIDECAR_NAME).exists():
        raise InstallerInstallationEvidenceError("Canonical installation evidence already exists")
    if {item.name for item in directory.iterdir()} != COMPLETE_NAMES.difference(
        (EVIDENCE_NAME, SIDECAR_NAME)
    ):
        raise InstallerInstallationEvidenceError(
            "Pre-canonical evidence directory has unexpected files"
        )
    context = _build_context(
        build_evidence_path, expected_sha256=expected_build_evidence_sha256
    )
    if context["document"]["observer_source"]["commit_sha"] != commit:
        raise InstallerInstallationEvidenceError("Observer source commit differs")
    document = _compose_evidence(
        build_context=context,
        project=project,
        contract=contract,
        wrapper=wrapper,
        source_commit=commit,
        directory=directory,
    )
    _validate_schema(document)
    payload = _json_bytes(document)
    evidence_path = directory / EVIDENCE_NAME
    evidence_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (directory / SIDECAR_NAME).write_text(f"{digest}  {EVIDENCE_NAME}\n", encoding="utf-8")
    return document


def verify_installer_installation_evidence(
    evidence_path: Path | str, *, expected_evidence_sha256: str
) -> dict:
    """Reconstruct retained lifecycle evidence without executing setup or application."""
    expected = _expected_sha256(expected_evidence_sha256, label="installation evidence")
    path = _real_file(
        evidence_path, label="Installer installation evidence", expected_name=EVIDENCE_NAME
    )
    if _sha256_file(path) != expected:
        raise InstallerInstallationEvidenceError(
            "Installer installation evidence differs from the external SHA-256"
        )
    directory = _directory(path.parent)
    document = _json_file(path, label="Installer installation evidence")
    _validate_schema(document)
    sidecar = (directory / SIDECAR_NAME).read_text(encoding="utf-8")
    if sidecar != f"{expected}  {EVIDENCE_NAME}\n":
        raise InstallerInstallationEvidenceError("Installation evidence sidecar differs")
    source = document["observer_source"]
    project, _repository, contract, wrapper = _source_inputs(source["project"]["path"])
    for current, record, label in (
        (project, source["project"], "Project"),
        (contract, source["contract"], "Contract"),
        (wrapper, source["wrapper"], "Wrapper"),
    ):
        _record_matches(current, record, label=label)
    build = document["installer_build_evidence"]
    context = _build_context(
        build["document"]["path"], expected_sha256=build["expected_sha256"]
    )
    reconstructed = _compose_evidence(
        build_context=context,
        project=project,
        contract=contract,
        wrapper=wrapper,
        source_commit=source["commit_sha"],
        directory=directory,
    )
    if document != reconstructed or path.read_bytes() != _json_bytes(reconstructed):
        raise InstallerInstallationEvidenceError(
            "Installer installation evidence does not reconstruct exactly"
        )
    return document

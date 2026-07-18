"""Create and verify engineering-only Windows installer build evidence."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from diffeoforge.desktop.inno_portable_toolchain_evidence import (
    verify_inno_portable_toolchain_evidence,
)
from diffeoforge.desktop.installer_plan import (
    PLAN_NAME,
    verify_desktop_installer_build_plan,
    verify_desktop_installer_build_plan_after_build,
)
from diffeoforge.exact_file import write_new_exact_file

SCHEMA_VERSION = "0.1"
STATUS = "engineering_installer_built_not_executed_signed_distributable_or_released"
TARGET = "windows-x86_64-cpu"
EVIDENCE_NAME = "installer-build-evidence.json"
SIDECAR_NAME = "installer-build-evidence.sha256"
OBSERVATION_NAME = "installer-compiler-observation.json"
CONTRACT_NAME = "installer-build-evidence-contract-v0.1.json"
WRAPPER_NAME = "observe_installer_build.ps1"
PORTABLE_EVIDENCE_NAME = "inno-portable-toolchain-evidence.json"
COMPILER_NAME = "ISCC.exe"
RAW_NAMES = frozenset((OBSERVATION_NAME,))
COMPLETE_NAMES = frozenset((OBSERVATION_NAME, EVIDENCE_NAME, SIDECAR_NAME))
MISSING_RELEASE_GATES = (
    "authenticode_signature",
    "clean_windows_vm",
    "cpu_numerical_release_validation",
    "crash_and_power_loss_reconciliation",
    "human_license_inventory",
    "installer_install_uninstall_observation",
    "license_compatibility_review",
    "no_network_observation",
    "project_preservation_observation",
    "redistribution_approval",
    "scientific_validation",
    "windows_defender_scan",
)
SCIENTIFIC_BOUNDARY = (
    "This document records one successful engineering-only compilation of the exact "
    "non-release installer plan with the authenticated portable Inno Setup toolchain. "
    "The resulting setup executable was hashed but never executed, signed, uploaded, "
    "distributed, or released. Offline verification reconstructs retained plan, bundle, "
    "six-file dependency/SBOM evidence, portable toolchain, compiler observation, and "
    "setup bytes. It does not establish install or uninstall behavior, license or "
    "redistribution approval, security, numerical correctness, scientific validity, "
    "production suitability, or bit-for-bit compiler determinism."
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class InstallerBuildEvidenceError(RuntimeError):
    """Raised when engineering installer build evidence fails closed."""


def _is_symbolic_path(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction is not None and is_junction())


def _reject_symbolic_chain(path: Path, *, label: str) -> None:
    current = path
    while True:
        if current.exists() and _is_symbolic_path(current):
            raise InstallerBuildEvidenceError(
                f"{label} must not use a symbolic path: {current}"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def _real_file(value: Path | str, *, label: str, expected_name: str | None = None) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_file():
        raise InstallerBuildEvidenceError(f"{label} must be an existing real file: {resolved}")
    if expected_name is not None and resolved.name != expected_name:
        raise InstallerBuildEvidenceError(f"{label} must be named {expected_name}")
    return resolved


def _real_directory(value: Path | str, *, label: str) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_dir():
        raise InstallerBuildEvidenceError(
            f"{label} must be an existing real directory: {resolved}"
        )
    return resolved


def _is_within(candidate: Path, root: Path) -> bool:
    return candidate == root or root in candidate.parents


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _json_file(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InstallerBuildEvidenceError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise InstallerBuildEvidenceError(f"{label} must be a JSON object")
    return value


def _expected_hash(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Expected {label} SHA-256 must contain 64 lowercase hex characters")
    return value


def _timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise InstallerBuildEvidenceError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InstallerBuildEvidenceError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise InstallerBuildEvidenceError(f"{label} must include a timezone")
    parsed.astimezone(UTC)
    return value


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath(
        "desktop-installer-build-evidence-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: object) -> None:
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise InstallerBuildEvidenceError(
            f"Installer build evidence schema violation at {location}: {first.message}"
        )


def _project_version(project_file: Path) -> str:
    try:
        document = tomllib.loads(project_file.read_text(encoding="utf-8"))
        project = document["project"]
        name = project["name"]
        version = project["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise InstallerBuildEvidenceError("Could not read exact project metadata") from error
    if name != "diffeoforge" or not isinstance(version, str) or not version:
        raise InstallerBuildEvidenceError("Project metadata must identify DiffeoForge")
    return version


def _validate_contract(path: Path) -> None:
    contract = _json_file(path, label="Installer build evidence contract")
    prerequisites = contract.get("required_prerequisites")
    execution = contract.get("execution")
    output = contract.get("output")
    if (
        contract.get("schema_version") != SCHEMA_VERSION
        or contract.get("target") != TARGET
        or not isinstance(prerequisites, dict)
        or prerequisites.get("plan_release_candidate") is not False
        or prerequisites.get("offline_reconstruction_before_compiler_execution") is not True
        or not isinstance(execution, dict)
        or execution.get("compiler") != COMPILER_NAME
        or execution.get("exact_plan_argument_count") != 9
        or execution.get("shell") is not False
        or execution.get("expected_setup_authenticode_status") != "NotSigned"
        or execution.get("setup_execution") is not False
        or execution.get("distribution_authorized") is not False
        or not isinstance(output, dict)
        or output.get("overwrite") is not False
        or output.get("offline_reconstruction") is not True
    ):
        raise InstallerBuildEvidenceError("Installer build evidence contract differs")


def _source_inputs(
    *, project_file: Path | str
) -> tuple[Path, Path, Path, Path]:
    project = _real_file(project_file, label="Project file", expected_name="pyproject.toml")
    repository = project.parent
    contract = _real_file(
        repository / "distribution" / "windows" / CONTRACT_NAME,
        label="Installer build evidence contract",
        expected_name=CONTRACT_NAME,
    )
    wrapper = _real_file(
        repository / "tools" / WRAPPER_NAME,
        label="Installer build observation wrapper",
        expected_name=WRAPPER_NAME,
    )
    _validate_contract(contract)
    return project, repository, contract, wrapper


def _validate_evidence_directory(
    output: Path,
    *,
    forbidden_roots: tuple[Path, ...],
    expected_names: frozenset[str],
) -> None:
    if any(_is_within(output, root) for root in forbidden_roots):
        raise InstallerBuildEvidenceError(
            "Installer build evidence output must be outside repository and all inputs"
        )
    entries = list(output.iterdir())
    if {entry.name for entry in entries} != expected_names or len(entries) != len(
        expected_names
    ):
        raise InstallerBuildEvidenceError(
            "Installer build evidence output differs from the exact file boundary"
        )
    if any(_is_symbolic_path(entry) or not entry.is_file() for entry in entries):
        raise InstallerBuildEvidenceError(
            "Installer build evidence output contains an unsafe entry"
        )


def _prerequisites(
    *,
    plan_path: Path,
    expected_plan_sha256: str,
    portable_evidence_path: Path,
    expected_portable_evidence_sha256: str,
    after_build: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    expected_plan = _expected_hash(expected_plan_sha256, label="installer plan")
    expected_portable = _expected_hash(
        expected_portable_evidence_sha256, label="portable toolchain evidence"
    )
    try:
        if after_build:
            plan = verify_desktop_installer_build_plan_after_build(
                plan_path, expected_plan_sha256=expected_plan
            )
        else:
            plan = verify_desktop_installer_build_plan(
                plan_path, expected_plan_sha256=expected_plan
            )
        portable = verify_inno_portable_toolchain_evidence(
            portable_evidence_path,
            expected_evidence_sha256=expected_portable,
        )
    except Exception as error:
        raise InstallerBuildEvidenceError(
            "Installer plan or portable toolchain prerequisite verification failed"
        ) from error
    if (
        plan["source"]["release_candidate"] is not False
        or plan["compiler"]["program"] != COMPILER_NAME
        or plan["compiler"]["shell"] is not False
        or plan["compiler"]["execution_authorized"] is not False
        or len(plan["compiler"]["arguments"]) != 9
        or plan["toolchain"]["asset_sha256"] != portable["installer"]["sha256"]
        or portable["compiler_probe"]["program"]["path"]
        != str(Path(portable["portable_install"]["installation_directory"]) / COMPILER_NAME)
        or portable["compiler_probe"]["exit_code"] != 0
        or portable["compiler_execution"]["diffeoforge_installer_built"] is not False
        or portable["execution_authorized"] is not False
    ):
        raise InstallerBuildEvidenceError(
            "Installer plan and portable toolchain do not permit the bounded engineering build"
        )
    return plan, portable


def verify_installer_build_prerequisites(
    plan_path: Path | str,
    *,
    expected_plan_sha256: str,
    portable_evidence_path: Path | str,
    expected_portable_evidence_sha256: str,
    project_file: Path | str,
    evidence_output_directory: Path | str,
    observer_source_commit: str,
) -> dict[str, object]:
    """Fail closed before one exact engineering compiler execution."""

    if not isinstance(observer_source_commit, str) or _COMMIT_PATTERN.fullmatch(
        observer_source_commit
    ) is None:
        raise ValueError("Observer source commit must contain 40 lowercase hex characters")
    plan_file = _real_file(plan_path, label="Installer build plan", expected_name=PLAN_NAME)
    portable_file = _real_file(
        portable_evidence_path,
        label="Portable Inno toolchain evidence",
        expected_name=PORTABLE_EVIDENCE_NAME,
    )
    project, repository, _contract, _wrapper = _source_inputs(project_file=project_file)
    output = _real_directory(
        evidence_output_directory, label="Installer build evidence output"
    )
    plan, portable = _prerequisites(
        plan_path=plan_file,
        expected_plan_sha256=expected_plan_sha256,
        portable_evidence_path=portable_file,
        expected_portable_evidence_sha256=expected_portable_evidence_sha256,
        after_build=False,
    )
    toolchain = _real_directory(
        portable["portable_install"]["installation_directory"],
        label="Portable Inno toolchain",
    )
    forbidden = (
        repository,
        Path(plan["inputs"]["bundle"]["directory"]),
        Path(plan["inputs"]["evidence"]["directory"]),
        Path(plan["output"]["directory"]),
        toolchain,
        plan_file.parent,
        portable_file.parent,
    )
    _validate_evidence_directory(
        output, forbidden_roots=forbidden, expected_names=frozenset()
    )
    return {
        "status": "engineering_installer_build_prerequisites_satisfied",
        "observer_source_commit": observer_source_commit,
        "application_version": plan["source"]["application_version"],
        "release_candidate": False,
        "plan_sha256": _expected_hash(expected_plan_sha256, label="installer plan"),
        "portable_evidence_sha256": _expected_hash(
            expected_portable_evidence_sha256, label="portable toolchain evidence"
        ),
        "compiler_execution_scope": "exact_nonrelease_installer_plan_once",
        "setup_execution_authorized": False,
        "distribution_authorized": False,
        "project_version": _project_version(project),
    }


def _compiler_observation(
    path: Path,
    *,
    plan: dict[str, object],
    plan_path: Path,
    plan_sha256: str,
    portable: dict[str, object],
    observer_source_commit: str,
) -> tuple[dict[str, object], str]:
    raw = _json_file(path, label="Installer compiler observation")
    observed_at = _timestamp(raw.get("observed_at"), label="Compiler observation time")
    toolchain = Path(portable["portable_install"]["installation_directory"])
    compiler = _real_file(
        toolchain / COMPILER_NAME, label="Portable ISCC compiler", expected_name=COMPILER_NAME
    )
    setup = _real_file(
        plan["output"]["setup_path"],
        label="Engineering setup output",
        expected_name=plan["output"]["setup_filename"],
    )
    setup_sidecar = _real_file(
        setup.with_name(f"{setup.name}.sha256"),
        label="Engineering setup SHA-256 sidecar",
        expected_name=f"{setup.name}.sha256",
    )
    setup_sha256 = _sha256_file(setup)
    expected_sidecar = f"{setup_sha256}  {setup.name}\n".encode("ascii")
    output_lines = raw.get("output_lines")
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("observed_at") != observed_at
        or raw.get("observer_source_commit") != observer_source_commit
        or raw.get("program_path") != str(compiler)
        or raw.get("program_bytes") != compiler.stat().st_size
        or raw.get("program_sha256") != _sha256_file(compiler)
        or raw.get("plan_path") != str(plan_path)
        or raw.get("plan_sha256") != plan_sha256
        or raw.get("command") != plan["compiler"]["arguments"]
        or raw.get("exit_code") != 0
        or not isinstance(output_lines, list)
        or any(not isinstance(line, str) for line in output_lines)
        or raw.get("setup_path") != str(setup)
        or raw.get("setup_bytes") != setup.stat().st_size
        or raw.get("setup_sha256") != setup_sha256
        or raw.get("setup_authenticode_status") != "NotSigned"
        or raw.get("setup_execution") is not False
        or raw.get("distribution_authorized") is not False
        or setup_sidecar.read_bytes() != expected_sidecar
    ):
        raise InstallerBuildEvidenceError("Installer compiler observation differs")
    return (
        {
            "raw": _file_record(path),
            "program": _file_record(compiler),
            "command": plan["compiler"]["arguments"],
            "exit_code": 0,
            "output_lines": output_lines,
            "setup": _file_record(setup),
            "setup_sidecar": _file_record(setup_sidecar),
            "setup_authenticode_status": "NotSigned",
            "setup_execution": False,
            "distribution_authorized": False,
        },
        observed_at,
    )


def _compose_evidence(
    *,
    plan_path: Path | str,
    expected_plan_sha256: str,
    portable_evidence_path: Path | str,
    expected_portable_evidence_sha256: str,
    project_file: Path | str,
    evidence_output_directory: Path | str,
    observer_source_commit: str,
    expected_output_names: frozenset[str],
) -> dict[str, object]:
    if not isinstance(observer_source_commit, str) or _COMMIT_PATTERN.fullmatch(
        observer_source_commit
    ) is None:
        raise ValueError("Observer source commit must contain 40 lowercase hex characters")
    plan_file = _real_file(plan_path, label="Installer build plan", expected_name=PLAN_NAME)
    portable_file = _real_file(
        portable_evidence_path,
        label="Portable Inno toolchain evidence",
        expected_name=PORTABLE_EVIDENCE_NAME,
    )
    project, repository, contract, wrapper = _source_inputs(project_file=project_file)
    output = _real_directory(
        evidence_output_directory, label="Installer build evidence output"
    )
    plan, portable = _prerequisites(
        plan_path=plan_file,
        expected_plan_sha256=expected_plan_sha256,
        portable_evidence_path=portable_file,
        expected_portable_evidence_sha256=expected_portable_evidence_sha256,
        after_build=True,
    )
    toolchain = _real_directory(
        portable["portable_install"]["installation_directory"],
        label="Portable Inno toolchain",
    )
    forbidden = (
        repository,
        Path(plan["inputs"]["bundle"]["directory"]),
        Path(plan["inputs"]["evidence"]["directory"]),
        Path(plan["output"]["directory"]),
        toolchain,
        plan_file.parent,
        portable_file.parent,
    )
    _validate_evidence_directory(
        output, forbidden_roots=forbidden, expected_names=expected_output_names
    )
    plan_expected = _expected_hash(expected_plan_sha256, label="installer plan")
    portable_expected = _expected_hash(
        expected_portable_evidence_sha256, label="portable toolchain evidence"
    )
    compiler, observed_at = _compiler_observation(
        _real_file(
            output / OBSERVATION_NAME,
            label="Installer compiler observation",
            expected_name=OBSERVATION_NAME,
        ),
        plan=plan,
        plan_path=plan_file,
        plan_sha256=plan_expected,
        portable=portable,
        observer_source_commit=observer_source_commit,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "target": TARGET,
        "observed_at": observed_at,
        "observer_source": {
            "commit_sha": observer_source_commit,
            "project_version": _project_version(project),
            "project": _file_record(project),
            "contract": _file_record(contract),
            "wrapper": _file_record(wrapper),
        },
        "plan": {
            **_file_record(plan_file),
            "expected_sha256": plan_expected,
            "source_commit_sha": plan["source"]["commit_sha"],
            "application_version": plan["source"]["application_version"],
            "release_candidate": False,
            "bundle_inventory_sha256": plan["inputs"]["bundle"]["inventory_sha256"],
            "freeze_evidence_sha256": plan["inputs"]["evidence"][
                "freeze_evidence_sha256"
            ],
            "dependency_evidence_sha256": plan["inputs"]["evidence"][
                "dependency_evidence_sha256"
            ],
            "sbom_sha256": plan["inputs"]["evidence"]["sbom_sha256"],
        },
        "portable_toolchain_evidence": {
            **_file_record(portable_file),
            "expected_sha256": portable_expected,
            "installer_sha256": portable["installer"]["sha256"],
            "compiler_probe_exit_code": portable["compiler_probe"]["exit_code"],
        },
        "compiler_execution": compiler,
        "setup_execution_authorized": False,
        "distribution_authorized": False,
        "release_authorized": False,
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def create_installer_build_evidence(
    plan_path: Path | str,
    *,
    expected_plan_sha256: str,
    portable_evidence_path: Path | str,
    expected_portable_evidence_sha256: str,
    project_file: Path | str,
    evidence_output_directory: Path | str,
    observer_source_commit: str,
) -> Path:
    """Create canonical evidence after one exact engineering compiler run."""

    document = _compose_evidence(
        plan_path=plan_path,
        expected_plan_sha256=expected_plan_sha256,
        portable_evidence_path=portable_evidence_path,
        expected_portable_evidence_sha256=expected_portable_evidence_sha256,
        project_file=project_file,
        evidence_output_directory=evidence_output_directory,
        observer_source_commit=observer_source_commit,
        expected_output_names=RAW_NAMES,
    )
    _validate_schema(document)
    payload = _json_bytes(document)
    output = Path(evidence_output_directory).expanduser().absolute().resolve()
    evidence_path = output / EVIDENCE_NAME
    sidecar_path = output / SIDECAR_NAME
    written: list[Path] = []
    try:
        written.append(
            write_new_exact_file(
                payload, evidence_path, artifact_label="Installer build evidence"
            )
        )
        digest = hashlib.sha256(payload).hexdigest()
        written.append(
            write_new_exact_file(
                f"{digest}  {EVIDENCE_NAME}\n".encode("ascii"),
                sidecar_path,
                artifact_label="Installer build evidence sidecar",
            )
        )
        verify_installer_build_evidence(
            evidence_path, expected_evidence_sha256=digest
        )
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise
    return evidence_path


def verify_installer_build_evidence(
    evidence_path: Path | str,
    *,
    expected_evidence_sha256: str,
) -> dict[str, object]:
    """Offline-reconstruct one retained engineering installer build."""

    expected = _expected_hash(expected_evidence_sha256, label="installer build evidence")
    path = _real_file(
        evidence_path, label="Installer build evidence", expected_name=EVIDENCE_NAME
    )
    sidecar = _real_file(
        path.with_name(SIDECAR_NAME),
        label="Installer build evidence sidecar",
        expected_name=SIDECAR_NAME,
    )
    try:
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8"))
        sidecar_payload = sidecar.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InstallerBuildEvidenceError("Installer build evidence is not readable") from error
    _validate_schema(document)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected:
        raise InstallerBuildEvidenceError(
            "Installer build evidence differs from the externally expected SHA-256"
        )
    if sidecar_payload != f"{digest}  {EVIDENCE_NAME}\n".encode("ascii"):
        raise InstallerBuildEvidenceError("Installer build evidence sidecar is malformed")
    if payload != _json_bytes(document):
        raise InstallerBuildEvidenceError("Installer build evidence is not canonical JSON")
    rebuilt = _compose_evidence(
        plan_path=document["plan"]["path"],
        expected_plan_sha256=document["plan"]["expected_sha256"],
        portable_evidence_path=document["portable_toolchain_evidence"]["path"],
        expected_portable_evidence_sha256=document["portable_toolchain_evidence"][
            "expected_sha256"
        ],
        project_file=document["observer_source"]["project"]["path"],
        evidence_output_directory=path.parent,
        observer_source_commit=document["observer_source"]["commit_sha"],
        expected_output_names=COMPLETE_NAMES,
    )
    if document != rebuilt or payload != _json_bytes(rebuilt):
        raise InstallerBuildEvidenceError(
            "Installer build evidence differs from reconstructed exact observations"
        )
    return document

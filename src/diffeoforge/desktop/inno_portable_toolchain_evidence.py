"""Create and verify portable Inno Setup preparation and compiler-probe evidence."""

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

from diffeoforge.desktop.inno_signature_evidence import verify_inno_signature_evidence
from diffeoforge.desktop.inno_toolchain_evidence import verify_inno_toolchain_evidence
from diffeoforge.exact_file import write_new_exact_file

SCHEMA_VERSION = "0.1"
STATUS = "portable_inno_toolchain_probe_not_diffeoforge_installer_or_release_authorization"
TARGET = "windows-x86_64-cpu"
EVIDENCE_NAME = "inno-portable-toolchain-evidence.json"
SIDECAR_NAME = "inno-portable-toolchain-evidence.sha256"
INSTALL_LOG_NAME = "inno-portable-install.log"
INSTALL_OBSERVATION_NAME = "inno-portable-install-observation.json"
AUTHENTICODE_OBSERVATION_NAME = "inno-portable-authenticode-observation.json"
PROBE_OBSERVATION_NAME = "inno-compiler-probe-observation.json"
CONTRACT_NAME = "inno-portable-toolchain-evidence-contract-v0.1.json"
WRAPPER_NAME = "observe_inno_portable_toolchain.ps1"
PROBE_SCRIPT_NAME = "InnoCompilerProbe.iss"

INSTALLER_NAME = "innosetup-7.0.2-x64.exe"
INSTALLER_BYTES = 17_020_192
INSTALLER_SHA256 = "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1"
EXPECTED_FILE_COUNT = 132
EXPECTED_DIRECTORY_COUNT = 5
EXPECTED_TOTAL_BYTES = 51_400_648
PROBE_SCRIPT_BYTES = 290
PROBE_SCRIPT_SHA256 = "3abf0abb493e821239157a9e1f14b027388f68b4b21fe5bb23a7bbab8ad780a4"
PROBE_OUTPUT_NAME = "DiffeoForge-Compiler-Probe.exe"
SIGNER_SUBJECT = "CN=Pyrsys B.V., O=Pyrsys B.V., S=Noord-Holland, C=NL"
CRITICAL_COMPONENTS = {
    "ISCC.exe": (
        2_016_160,
        "0ff6140d641f84b64204a2c4d52207c6fc437c9f4db8779c83083d84f7e3d70d",
    ),
    "ISCmplr.dll": (
        2_249_120,
        "d63233641c63eb56bbc067c8aa756157740e780a019aa7e5292f37610fbd24af",
    ),
    "ISPP.dll": (
        1_601_440,
        "174a012bbc0e69a9cb43336a04ae2b93ea8d2b93362135541ad49a8dadae2676",
    ),
    "ISSigTool.exe": (
        1_398_688,
        "d381ea69a33e6d4e8fb6f7adc089e8bcf3e7c6b99c20822cf9eb0979bccceae4",
    ),
}
RAW_NAMES = frozenset(
    (
        INSTALL_LOG_NAME,
        INSTALL_OBSERVATION_NAME,
        AUTHENTICODE_OBSERVATION_NAME,
        PROBE_OBSERVATION_NAME,
    )
)
COMPLETE_NAMES = frozenset((*RAW_NAMES, EVIDENCE_NAME, SIDECAR_NAME))
MISSING_RELEASE_GATES = (
    "actual_diffeoforge_installer_build_observation",
    "authenticode_signature_for_diffeoforge_outputs",
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
    "This document records one successful portable current-user preparation of exact Inno "
    "Setup 7.0.2 bytes and one successful compilation of a fixed payload-free probe. The "
    "authenticated installer and ISCC compiler executed only within those scopes. No "
    "DiffeoForge installer was built, installed, or distributed. Offline verification "
    "rechecks retained inputs, prerequisite evidence, the installed inventory, logs, "
    "critical Authenticode observations, and probe output. It does not authorize signing, "
    "installation, redistribution, release, or security, numerical, scientific, or "
    "production-suitability claims."
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SHA1_PATTERN = re.compile(r"[0-9a-f]{40}")
_THUMBPRINT_PATTERN = re.compile(r"[0-9A-F]{40}")


class InnoPortableToolchainEvidenceError(RuntimeError):
    """Raised when portable toolchain or compiler-probe evidence fails closed."""


def _is_symbolic_path(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction is not None and is_junction())


def _reject_symbolic_chain(path: Path, *, label: str) -> None:
    current = path
    while True:
        if current.exists() and _is_symbolic_path(current):
            raise InnoPortableToolchainEvidenceError(
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
        raise InnoPortableToolchainEvidenceError(
            f"{label} must be an existing real file: {resolved}"
        )
    if expected_name is not None and resolved.name != expected_name:
        raise InnoPortableToolchainEvidenceError(f"{label} must be named {expected_name}")
    return resolved


def _real_directory(value: Path | str, *, label: str) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_dir():
        raise InnoPortableToolchainEvidenceError(
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
        raise InnoPortableToolchainEvidenceError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise InnoPortableToolchainEvidenceError(f"{label} must be a JSON object")
    return value


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise InnoPortableToolchainEvidenceError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InnoPortableToolchainEvidenceError(
            f"{label} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise InnoPortableToolchainEvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _expected_hash(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Expected {label} SHA-256 must contain 64 lowercase hex characters")
    return value


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath(
        "desktop-inno-portable-toolchain-evidence-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: object) -> None:
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise InnoPortableToolchainEvidenceError(
            f"Portable toolchain evidence schema violation at {location}: {first.message}"
        )


def _project_version(project_file: Path) -> str:
    try:
        document = tomllib.loads(project_file.read_text(encoding="utf-8"))
        project = document["project"]
        name = project["name"]
        version = project["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise InnoPortableToolchainEvidenceError("Could not read exact project metadata") from error
    if name != "diffeoforge" or not isinstance(version, str) or not version:
        raise InnoPortableToolchainEvidenceError("Project metadata must identify DiffeoForge")
    return version


def _inventory(root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if _is_symbolic_path(path):
            raise InnoPortableToolchainEvidenceError(
                f"Portable toolchain contains a symbolic path: {path}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise InnoPortableToolchainEvidenceError(
                f"Portable toolchain contains a non-file entry: {path}"
            )
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return entries


def _validate_contract(path: Path) -> None:
    contract = _json_file(path, label="Portable toolchain evidence contract")
    installer = contract.get("installer")
    portable = contract.get("portable_install")
    critical = contract.get("critical_components")
    probe = contract.get("compiler_probe")
    if (
        contract.get("schema_version") != SCHEMA_VERSION
        or contract.get("target") != TARGET
        or installer
        != {
            "name": INSTALLER_NAME,
            "bytes": INSTALLER_BYTES,
            "sha256": INSTALLER_SHA256,
        }
        or not isinstance(portable, dict)
        or portable.get("expected_file_count") != EXPECTED_FILE_COUNT
        or portable.get("expected_directory_count") != EXPECTED_DIRECTORY_COUNT
        or portable.get("expected_total_bytes") != EXPECTED_TOTAL_BYTES
        or portable.get("uninstaller_file_count") != 0
        or not isinstance(critical, dict)
        or critical.get("required_signer_subject") != SIGNER_SUBJECT
        or critical.get("files")
        != {
            name: {"bytes": expected[0], "sha256": expected[1]}
            for name, expected in CRITICAL_COMPONENTS.items()
        }
        or not isinstance(probe, dict)
        or probe.get("script") != PROBE_SCRIPT_NAME
        or probe.get("script_bytes") != PROBE_SCRIPT_BYTES
        or probe.get("script_sha256") != PROBE_SCRIPT_SHA256
        or probe.get("expected_output_name") != PROBE_OUTPUT_NAME
        or probe.get("distribution_authorized") is not False
    ):
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain evidence contract differs"
        )


def _validate_directories(
    *,
    repository: Path,
    installer: Path,
    prerequisite_files: tuple[Path, Path],
    toolchain: Path,
    probe_output: Path,
    evidence_output: Path,
    require_empty: bool,
) -> None:
    directories = (toolchain, probe_output, evidence_output)
    if len(set(directories)) != 3:
        raise InnoPortableToolchainEvidenceError(
            "Toolchain, probe output, and evidence output must be distinct"
        )
    forbidden_roots = {repository, installer.parent, *(path.parent for path in prerequisite_files)}
    if any(_is_within(directory, root) for directory in directories for root in forbidden_roots):
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain directories must be outside repository and inputs"
        )
    if any(
        left != right and (_is_within(left, right) or _is_within(right, left))
        for index, left in enumerate(directories)
        for right in directories[index + 1 :]
    ):
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain directories must not contain each other"
        )
    if require_empty and any(any(directory.iterdir()) for directory in directories):
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain preflight requires three empty directories"
        )


def _source_inputs(
    *,
    installer_path: Path | str,
    toolchain_evidence_path: Path | str,
    signature_evidence_path: Path | str,
    project_file: Path | str,
) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
    installer = _real_file(
        installer_path, label="Inno Setup installer", expected_name=INSTALLER_NAME
    )
    if installer.stat().st_size != INSTALLER_BYTES or _sha256_file(installer) != INSTALLER_SHA256:
        raise InnoPortableToolchainEvidenceError("Inno Setup installer size or SHA-256 differs")
    toolchain_evidence = _real_file(
        toolchain_evidence_path,
        label="Inno toolchain prerequisite evidence",
        expected_name="inno-toolchain-evidence.json",
    )
    signature_evidence = _real_file(
        signature_evidence_path,
        label="Inno signature prerequisite evidence",
        expected_name="inno-signature-evidence.json",
    )
    project = _real_file(project_file, label="Project file", expected_name="pyproject.toml")
    repository = project.parent
    contract = _real_file(
        repository / "distribution" / "windows" / CONTRACT_NAME,
        label="Portable toolchain evidence contract",
        expected_name=CONTRACT_NAME,
    )
    probe = _real_file(
        repository / "distribution" / "windows" / PROBE_SCRIPT_NAME,
        label="Inno compiler probe script",
        expected_name=PROBE_SCRIPT_NAME,
    )
    wrapper = _real_file(
        repository / "tools" / WRAPPER_NAME,
        label="Portable toolchain observation wrapper",
        expected_name=WRAPPER_NAME,
    )
    _validate_contract(contract)
    if probe.stat().st_size != PROBE_SCRIPT_BYTES or _sha256_file(probe) != PROBE_SCRIPT_SHA256:
        raise InnoPortableToolchainEvidenceError("Inno compiler probe script differs")
    return (
        installer,
        toolchain_evidence,
        signature_evidence,
        project,
        repository,
        contract,
        probe,
        wrapper,
    )


def _prerequisites(
    *,
    installer: Path,
    toolchain_evidence: Path,
    expected_toolchain_evidence_sha256: str,
    signature_evidence: Path,
    expected_signature_evidence_sha256: str,
) -> dict[str, object]:
    expected_toolchain = _expected_hash(
        expected_toolchain_evidence_sha256, label="toolchain evidence"
    )
    expected_signature = _expected_hash(
        expected_signature_evidence_sha256, label="signature evidence"
    )
    try:
        toolchain_document = verify_inno_toolchain_evidence(
            toolchain_evidence,
            expected_evidence_sha256=expected_toolchain,
        )
        signature_document = verify_inno_signature_evidence(
            signature_evidence,
            expected_evidence_sha256=expected_signature,
        )
    except Exception as error:
        raise InnoPortableToolchainEvidenceError(
            "Inno prerequisite evidence verification failed"
        ) from error
    if (
        toolchain_document["asset"]["path"] != str(installer)
        or toolchain_document["asset"]["sha256"] != INSTALLER_SHA256
        or toolchain_document["execution_authorized"] is not False
        or signature_document["installer"]["path"] != str(installer)
        or signature_document["installer"]["sha256"] != INSTALLER_SHA256
        or signature_document["issigtool_execution"]["exit_code"] != 0
        or signature_document["installer_execution_authorized"] is not False
        or signature_document["execution_authorized"] is not False
    ):
        raise InnoPortableToolchainEvidenceError(
            "Prerequisite evidence does not bind the exact non-executed installer"
        )
    return {
        "toolchain": {
            **_file_record(toolchain_evidence),
            "expected_sha256": expected_toolchain,
            "source_commit_sha": toolchain_document["source"]["commit_sha"],
        },
        "signature": {
            **_file_record(signature_evidence),
            "expected_sha256": expected_signature,
            "source_commit_sha": signature_document["source"]["commit_sha"],
        },
    }


def verify_inno_portable_toolchain_prerequisites(
    installer_path: Path | str,
    *,
    toolchain_evidence_path: Path | str,
    expected_toolchain_evidence_sha256: str,
    signature_evidence_path: Path | str,
    expected_signature_evidence_sha256: str,
    project_file: Path | str,
    toolchain_directory: Path | str,
    probe_output_directory: Path | str,
    evidence_output_directory: Path | str,
    source_commit: str,
) -> dict[str, object]:
    """Fail closed before the authenticated installer is allowed to execute."""

    if not isinstance(source_commit, str) or _SHA1_PATTERN.fullmatch(source_commit) is None:
        raise ValueError("Source commit must contain exactly 40 lowercase hexadecimal characters")
    (
        installer,
        toolchain_evidence,
        signature_evidence,
        project,
        repository,
        _contract,
        _probe,
        _wrapper,
    ) = _source_inputs(
        installer_path=installer_path,
        toolchain_evidence_path=toolchain_evidence_path,
        signature_evidence_path=signature_evidence_path,
        project_file=project_file,
    )
    toolchain = _real_directory(toolchain_directory, label="Portable toolchain directory")
    probe_output = _real_directory(
        probe_output_directory, label="Compiler-probe output directory"
    )
    evidence_output = _real_directory(
        evidence_output_directory, label="Portable evidence output directory"
    )
    _validate_directories(
        repository=repository,
        installer=installer,
        prerequisite_files=(toolchain_evidence, signature_evidence),
        toolchain=toolchain,
        probe_output=probe_output,
        evidence_output=evidence_output,
        require_empty=True,
    )
    prerequisite_records = _prerequisites(
        installer=installer,
        toolchain_evidence=toolchain_evidence,
        expected_toolchain_evidence_sha256=expected_toolchain_evidence_sha256,
        signature_evidence=signature_evidence,
        expected_signature_evidence_sha256=expected_signature_evidence_sha256,
    )
    return {
        "status": "portable_inno_toolchain_prerequisites_satisfied",
        "source_commit": source_commit,
        "installer_sha256": INSTALLER_SHA256,
        "toolchain_evidence_sha256": prerequisite_records["toolchain"]["expected_sha256"],
        "signature_evidence_sha256": prerequisite_records["signature"]["expected_sha256"],
        "installer_execution_scope": "prepare_exact_portable_inno_toolchain_only",
        "diffeoforge_installer_build_authorized": False,
    }


def _install_observation(
    path: Path,
    *,
    log: Path,
    installer: Path,
    toolchain: Path,
    observed_inventory: list[dict[str, object]],
) -> tuple[dict[str, object], str]:
    raw = _json_file(path, label="Portable Inno install observation")
    observed_at = raw.get("observed_at")
    _timestamp(observed_at, label="Portable install observation time")
    raw_inventory = raw.get("installed_inventory")
    if not isinstance(raw_inventory, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("path"), str)
        for item in raw_inventory
    ):
        raise InnoPortableToolchainEvidenceError(
            "Portable Inno raw inventory is not a file-record list"
        )
    canonical_raw_inventory = sorted(raw_inventory, key=lambda item: item["path"])
    expected_command = [
        "/PORTABLE=1",
        "/CURRENTUSER",
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/NOICONS",
        "/LANG=english",
        f'/DIR="{toolchain}"',
        f'/LOG="{log}"',
    ]
    file_count = len(observed_inventory)
    directory_count = sum(1 for item in toolchain.rglob("*") if item.is_dir())
    total_bytes = sum(int(item["bytes"]) for item in observed_inventory)
    uninstaller_count = sum(
        1
        for item in observed_inventory
        if re.fullmatch(r"unins.*\.(?:exe|dat|msg)", Path(str(item["path"])).name, re.I)
    )
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("installer_path") != str(installer)
        or raw.get("installer_bytes") != INSTALLER_BYTES
        or raw.get("installer_sha256") != INSTALLER_SHA256
        or raw.get("command") != expected_command
        or raw.get("exit_code") != 0
        or raw.get("installation_directory") != str(toolchain)
        or raw.get("log_path") != str(log)
        or canonical_raw_inventory != observed_inventory
        or raw.get("installed_file_count") != file_count
        or raw.get("installed_directory_count") != directory_count
        or raw.get("installed_total_bytes") != total_bytes
        or raw.get("uninstaller_file_count") != uninstaller_count
        or raw.get("portable_mode") is not True
        or raw.get("current_user") is not True
        or raw.get("restart") is not False
        or raw.get("system_install_claim") is not False
    ):
        raise InnoPortableToolchainEvidenceError("Portable Inno install observation differs")
    if (
        file_count != EXPECTED_FILE_COUNT
        or directory_count != EXPECTED_DIRECTORY_COUNT
        or total_bytes != EXPECTED_TOTAL_BYTES
        or uninstaller_count != 0
    ):
        raise InnoPortableToolchainEvidenceError(
            "Portable Inno installed inventory summary differs"
        )
    try:
        log_text = log.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise InnoPortableToolchainEvidenceError("Portable install log is unreadable") from error
    if (
        "Installation process succeeded." not in log_text
        or "Need to restart Windows? No" not in log_text
        or "/PORTABLE=1" not in log_text
    ):
        raise InnoPortableToolchainEvidenceError(
            "Portable install log lacks the exact success boundary"
        )
    return (
        {
            "raw": _file_record(path),
            "log": _file_record(log),
            "command": expected_command,
            "exit_code": 0,
            "installation_directory": str(toolchain),
            "installed_file_count": file_count,
            "installed_directory_count": directory_count,
            "installed_total_bytes": total_bytes,
            "inventory": observed_inventory,
            "uninstaller_file_count": 0,
            "portable_mode": True,
            "current_user": True,
            "restart": False,
            "system_install_claim": False,
        },
        str(observed_at),
    )


def _authenticode_observation(
    path: Path,
    *,
    toolchain: Path,
    observed_at: str,
) -> dict[str, object]:
    raw = _json_file(path, label="Portable toolchain Authenticode observation")
    records = raw.get("components")
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("observed_at") != observed_at
        or not isinstance(records, list)
        or len(records) != len(CRITICAL_COMPONENTS)
    ):
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain Authenticode observation differs"
        )
    expected_records: list[dict[str, object]] = []
    for name in sorted(CRITICAL_COMPONENTS):
        component = _real_file(
            toolchain / name,
            label=f"Portable toolchain component {name}",
            expected_name=name,
        )
        expected_bytes, expected_sha256 = CRITICAL_COMPONENTS[name]
        matching = [item for item in records if isinstance(item, dict) and item.get("name") == name]
        if len(matching) != 1:
            raise InnoPortableToolchainEvidenceError(
                f"Portable toolchain component observation is missing: {name}"
            )
        item = matching[0]
        if (
            component.stat().st_size != expected_bytes
            or _sha256_file(component) != expected_sha256
            or item.get("path") != str(component)
            or item.get("bytes") != expected_bytes
            or item.get("sha256") != expected_sha256
            or item.get("status") != "Valid"
            or item.get("signer_subject") != SIGNER_SUBJECT
        ):
            raise InnoPortableToolchainEvidenceError(
                f"Portable toolchain component identity differs: {name}"
            )
        if any(
            not isinstance(item.get(field), str) or not item[field]
            for field in ("signer_issuer", "timestamp_subject")
        ):
            raise InnoPortableToolchainEvidenceError(
                f"Portable toolchain certificate observation is incomplete: {name}"
            )
        for field in ("signer_thumbprint", "timestamp_thumbprint"):
            if (
                not isinstance(item.get(field), str)
                or _THUMBPRINT_PATTERN.fullmatch(item[field]) is None
            ):
                raise InnoPortableToolchainEvidenceError(
                    f"Portable toolchain certificate thumbprint differs: {name}"
                )
        expected_records.append(
            {
                "name": name,
                "file": _file_record(component),
                "status": "Valid",
                "signer_subject": SIGNER_SUBJECT,
                "signer_issuer": item["signer_issuer"],
                "signer_thumbprint": item["signer_thumbprint"],
                "timestamp_subject": item["timestamp_subject"],
                "timestamp_thumbprint": item["timestamp_thumbprint"],
            }
        )
    return {"raw": _file_record(path), "components": expected_records}


def _probe_observation(
    path: Path,
    *,
    toolchain: Path,
    probe_script: Path,
    probe_output: Path,
    observed_at: str,
) -> dict[str, object]:
    raw = _json_file(path, label="Inno compiler-probe observation")
    iscc = _real_file(toolchain / "ISCC.exe", label="ISCC compiler", expected_name="ISCC.exe")
    outputs = list(probe_output.iterdir())
    if len(outputs) != 1:
        raise InnoPortableToolchainEvidenceError(
            "Compiler-probe output must contain exactly one entry"
        )
    output = _real_file(
        outputs[0], label="Inno compiler-probe output", expected_name=PROBE_OUTPUT_NAME
    )
    expected_command = [
        "/Qp",
        "/O+",
        f"/O{probe_output}",
        "/FDiffeoForge-Compiler-Probe",
        str(probe_script),
    ]
    output_lines = raw.get("output_lines")
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("observed_at") != observed_at
        or raw.get("program_path") != str(iscc)
        or raw.get("program_bytes") != iscc.stat().st_size
        or raw.get("program_sha256") != _sha256_file(iscc)
        or raw.get("script_path") != str(probe_script)
        or raw.get("script_bytes") != PROBE_SCRIPT_BYTES
        or raw.get("script_sha256") != PROBE_SCRIPT_SHA256
        or raw.get("command") != expected_command
        or raw.get("exit_code") != 0
        or not isinstance(output_lines, list)
        or any(not isinstance(line, str) for line in output_lines)
        or raw.get("output_path") != str(output)
        or raw.get("output_bytes") != output.stat().st_size
        or raw.get("output_sha256") != _sha256_file(output)
        or raw.get("payload_free") is not True
        or raw.get("distribution_authorized") is not False
    ):
        raise InnoPortableToolchainEvidenceError("Inno compiler-probe observation differs")
    return {
        "raw": _file_record(path),
        "program": _file_record(iscc),
        "script": _file_record(probe_script),
        "command": expected_command,
        "exit_code": 0,
        "output_lines": output_lines,
        "output": _file_record(output),
        "payload_free": True,
        "distribution_authorized": False,
    }


def _compose_evidence(
    *,
    installer_path: Path | str,
    toolchain_evidence_path: Path | str,
    expected_toolchain_evidence_sha256: str,
    signature_evidence_path: Path | str,
    expected_signature_evidence_sha256: str,
    project_file: Path | str,
    toolchain_directory: Path | str,
    probe_output_directory: Path | str,
    evidence_output_directory: Path | str,
    source_commit: str,
    expected_output_names: frozenset[str],
) -> dict[str, object]:
    if not isinstance(source_commit, str) or _SHA1_PATTERN.fullmatch(source_commit) is None:
        raise ValueError("Source commit must contain exactly 40 lowercase hexadecimal characters")
    (
        installer,
        toolchain_evidence,
        signature_evidence,
        project,
        repository,
        contract,
        probe_script,
        wrapper,
    ) = _source_inputs(
        installer_path=installer_path,
        toolchain_evidence_path=toolchain_evidence_path,
        signature_evidence_path=signature_evidence_path,
        project_file=project_file,
    )
    toolchain = _real_directory(toolchain_directory, label="Portable toolchain directory")
    probe_output = _real_directory(
        probe_output_directory, label="Compiler-probe output directory"
    )
    evidence_output = _real_directory(
        evidence_output_directory, label="Portable evidence output directory"
    )
    _validate_directories(
        repository=repository,
        installer=installer,
        prerequisite_files=(toolchain_evidence, signature_evidence),
        toolchain=toolchain,
        probe_output=probe_output,
        evidence_output=evidence_output,
        require_empty=False,
    )
    entries = list(evidence_output.iterdir())
    if {entry.name for entry in entries} != expected_output_names or len(entries) != len(
        expected_output_names
    ):
        raise InnoPortableToolchainEvidenceError(
            "Portable evidence output differs from the exact file boundary"
        )
    if any(_is_symbolic_path(entry) or not entry.is_file() for entry in entries):
        raise InnoPortableToolchainEvidenceError(
            "Portable evidence output contains a symbolic or non-file entry"
        )
    prerequisites = _prerequisites(
        installer=installer,
        toolchain_evidence=toolchain_evidence,
        expected_toolchain_evidence_sha256=expected_toolchain_evidence_sha256,
        signature_evidence=signature_evidence,
        expected_signature_evidence_sha256=expected_signature_evidence_sha256,
    )
    inventory = _inventory(toolchain)
    install, observed_at = _install_observation(
        _real_file(
            evidence_output / INSTALL_OBSERVATION_NAME,
            label="Portable Inno install observation",
            expected_name=INSTALL_OBSERVATION_NAME,
        ),
        log=_real_file(
            evidence_output / INSTALL_LOG_NAME,
            label="Portable Inno install log",
            expected_name=INSTALL_LOG_NAME,
        ),
        installer=installer,
        toolchain=toolchain,
        observed_inventory=inventory,
    )
    authenticode = _authenticode_observation(
        _real_file(
            evidence_output / AUTHENTICODE_OBSERVATION_NAME,
            label="Portable toolchain Authenticode observation",
            expected_name=AUTHENTICODE_OBSERVATION_NAME,
        ),
        toolchain=toolchain,
        observed_at=observed_at,
    )
    probe = _probe_observation(
        _real_file(
            evidence_output / PROBE_OBSERVATION_NAME,
            label="Inno compiler-probe observation",
            expected_name=PROBE_OBSERVATION_NAME,
        ),
        toolchain=toolchain,
        probe_script=probe_script,
        probe_output=probe_output,
        observed_at=observed_at,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "target": TARGET,
        "observed_at": observed_at,
        "source": {
            "commit_sha": source_commit,
            "diffeoforge_version": _project_version(project),
            "project": _file_record(project),
            "contract": _file_record(contract),
            "wrapper": _file_record(wrapper),
            "probe_script": _file_record(probe_script),
        },
        "installer": _file_record(installer),
        "prerequisite_evidence": prerequisites,
        "portable_install": install,
        "critical_authenticode": authenticode,
        "compiler_probe": probe,
        "installer_execution": {
            "occurred": True,
            "scope": "prepare_exact_portable_inno_toolchain_only",
            "system_install_claim": False,
        },
        "compiler_execution": {
            "occurred": True,
            "scope": "compile_fixed_payload_free_probe_only",
            "diffeoforge_installer_built": False,
        },
        "execution_authorized": False,
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def create_inno_portable_toolchain_evidence(
    installer_path: Path | str,
    *,
    toolchain_evidence_path: Path | str,
    expected_toolchain_evidence_sha256: str,
    signature_evidence_path: Path | str,
    expected_signature_evidence_sha256: str,
    project_file: Path | str,
    toolchain_directory: Path | str,
    probe_output_directory: Path | str,
    evidence_output_directory: Path | str,
    source_commit: str,
) -> Path:
    """Create canonical evidence after portable preparation and the fixed probe."""

    document = _compose_evidence(
        installer_path=installer_path,
        toolchain_evidence_path=toolchain_evidence_path,
        expected_toolchain_evidence_sha256=expected_toolchain_evidence_sha256,
        signature_evidence_path=signature_evidence_path,
        expected_signature_evidence_sha256=expected_signature_evidence_sha256,
        project_file=project_file,
        toolchain_directory=toolchain_directory,
        probe_output_directory=probe_output_directory,
        evidence_output_directory=evidence_output_directory,
        source_commit=source_commit,
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
                payload,
                evidence_path,
                artifact_label="Portable Inno toolchain evidence",
            )
        )
        digest = hashlib.sha256(payload).hexdigest()
        written.append(
            write_new_exact_file(
                f"{digest}  {EVIDENCE_NAME}\n".encode("ascii"),
                sidecar_path,
                artifact_label="Portable Inno toolchain evidence sidecar",
            )
        )
        verify_inno_portable_toolchain_evidence(
            evidence_path,
            expected_evidence_sha256=digest,
        )
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise
    return evidence_path


def verify_inno_portable_toolchain_evidence(
    evidence_path: Path | str,
    *,
    expected_evidence_sha256: str,
) -> dict[str, object]:
    """Offline-reconstruct the exact portable toolchain and compiler-probe evidence."""

    expected = _expected_hash(expected_evidence_sha256, label="portable toolchain evidence")
    path = _real_file(
        evidence_path,
        label="Portable Inno toolchain evidence",
        expected_name=EVIDENCE_NAME,
    )
    sidecar = _real_file(
        path.with_name(SIDECAR_NAME),
        label="Portable Inno toolchain evidence sidecar",
        expected_name=SIDECAR_NAME,
    )
    try:
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8"))
        sidecar_payload = sidecar.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InnoPortableToolchainEvidenceError(
            "Portable Inno toolchain evidence is not readable"
        ) from error
    _validate_schema(document)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected:
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain evidence differs from the externally expected SHA-256"
        )
    if sidecar_payload != f"{digest}  {EVIDENCE_NAME}\n".encode("ascii"):
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain evidence sidecar is malformed"
        )
    if payload != _json_bytes(document):
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain evidence is not canonical JSON"
        )
    rebuilt = _compose_evidence(
        installer_path=document["installer"]["path"],
        toolchain_evidence_path=document["prerequisite_evidence"]["toolchain"]["path"],
        expected_toolchain_evidence_sha256=document["prerequisite_evidence"]["toolchain"][
            "expected_sha256"
        ],
        signature_evidence_path=document["prerequisite_evidence"]["signature"]["path"],
        expected_signature_evidence_sha256=document["prerequisite_evidence"]["signature"][
            "expected_sha256"
        ],
        project_file=document["source"]["project"]["path"],
        toolchain_directory=document["portable_install"]["installation_directory"],
        probe_output_directory=Path(document["compiler_probe"]["output"]["path"]).parent,
        evidence_output_directory=path.parent,
        source_commit=document["source"]["commit_sha"],
        expected_output_names=COMPLETE_NAMES,
    )
    if document != rebuilt or payload != _json_bytes(rebuilt):
        raise InnoPortableToolchainEvidenceError(
            "Portable toolchain evidence differs from reconstructed exact observations"
        )
    return document

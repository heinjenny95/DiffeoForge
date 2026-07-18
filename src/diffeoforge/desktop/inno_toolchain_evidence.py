"""Create and verify offline-bound Inno Setup authenticity observations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from diffeoforge.exact_file import write_new_exact_file

SCHEMA_VERSION = "0.1"
STATUS = "toolchain_authenticity_observation_not_execution_or_release_authorization"
TARGET = "windows-x86_64-cpu"
EVIDENCE_NAME = "inno-toolchain-evidence.json"
SIDECAR_NAME = "inno-toolchain-evidence.sha256"
ATTESTATION_NAME = "inno-release-attestation.json"
AUTHENTICODE_NAME = "inno-authenticode-observation.json"
VERIFIER_NAME = "inno-release-verifier-observation.json"
CONTRACT_NAME = "inno-toolchain-evidence-contract-v0.1.json"
WRAPPER_NAME = "observe_inno_toolchain.ps1"
ASSET_NAME = "innosetup-7.0.2-x64.exe"
ASSET_BYTES = 17_020_192
ASSET_SHA256 = "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1"
ASSET_ID = 475_225_237
REPOSITORY = "jrsoftware/issrc"
REPOSITORY_ID = 2_527_983
RELEASE_TAG = "is-7_0_2"
RELEASE_DATABASE_ID = 352_994_135
RELEASE_TAG_OBJECT_SHA1 = "d2509df69f828a7148294e29b2ca252c3250210c"
RELEASE_COMMIT_SHA1 = "c25dc6479cdc3be28e682a025fcf60765bba3de0"
RELEASE_PURL = "pkg:github/jrsoftware/issrc@is-7_0_2"
PREDICATE_TYPE = "https://in-toto.io/attestation/release/v0.2"
ATTESTER_SAN = "https://dotcom.releases.github.com"
TIMESTAMP_AUTHORITY = "timestamp.githubapp.com"
SIGNER_SUBJECT = "CN=Pyrsys B.V., O=Pyrsys B.V., S=Noord-Holland, C=NL"
RAW_NAMES = frozenset((ATTESTATION_NAME, AUTHENTICODE_NAME, VERIFIER_NAME))
COMPLETE_NAMES = frozenset((*RAW_NAMES, EVIDENCE_NAME, SIDECAR_NAME))
MISSING_RELEASE_GATES = (
    "authenticode_signature_for_diffeoforge_outputs",
    "clean_windows_vm",
    "compiler_execution",
    "cpu_numerical_release_validation",
    "crash_and_power_loss_reconciliation",
    "human_license_inventory",
    "inno_signature_tool_observation",
    "installer_install_uninstall_observation",
    "license_compatibility_review",
    "no_network_observation",
    "project_preservation_observation",
    "redistribution_approval",
    "scientific_validation",
    "windows_defender_scan",
)
SCIENTIFIC_BOUNDARY = (
    "This document records one successful GitHub release-attestation and Windows "
    "Authenticode observation for an exact Inno Setup asset. Offline verification "
    "rechecks the recorded output and all available file bindings but does not "
    "cryptographically repeat the network-backed release verification. It does not "
    "authorize execution, installation, compilation, redistribution, release, or "
    "security, numerical, scientific, or production-suitability claims."
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SHA1_PATTERN = re.compile(r"[0-9a-f]{40}")
_THUMBPRINT_PATTERN = re.compile(r"[0-9A-F]{40}")
_GH_VERSION_PATTERN = re.compile(r"gh version ([0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)")


class InnoToolchainEvidenceError(RuntimeError):
    """Raised when a toolchain authenticity observation fails closed."""


def _is_symbolic_path(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction is not None and is_junction())


def _reject_symbolic_chain(path: Path, *, label: str) -> None:
    current = path
    while True:
        if current.exists() and _is_symbolic_path(current):
            raise InnoToolchainEvidenceError(f"{label} must not use a symbolic path: {current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _real_file(
    value: Path | str,
    *,
    label: str,
    expected_name: str | None = None,
) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_file():
        raise InnoToolchainEvidenceError(f"{label} must be an existing real file: {resolved}")
    if expected_name is not None and resolved.name != expected_name:
        raise InnoToolchainEvidenceError(f"{label} must be named {expected_name}")
    return resolved


def _real_directory(value: Path | str, *, label: str) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_dir():
        raise InnoToolchainEvidenceError(f"{label} must be an existing real directory: {resolved}")
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
        raise InnoToolchainEvidenceError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise InnoToolchainEvidenceError(f"{label} must be a JSON object")
    return value


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise InnoToolchainEvidenceError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InnoToolchainEvidenceError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise InnoToolchainEvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath("desktop-inno-toolchain-evidence-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: object) -> None:
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise InnoToolchainEvidenceError(
            f"Inno toolchain evidence schema violation at {location}: {first.message}"
        )


def _project_version(project_file: Path) -> str:
    try:
        document = tomllib.loads(project_file.read_text(encoding="utf-8"))
        project = document["project"]
        name = project["name"]
        version = project["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise InnoToolchainEvidenceError("Could not read exact project metadata") from error
    if name != "diffeoforge" or not isinstance(version, str) or not version:
        raise InnoToolchainEvidenceError("Project metadata must identify DiffeoForge")
    return version


def _validate_contract(path: Path) -> None:
    contract = _json_file(path, label="Inno toolchain evidence contract")
    asset = contract.get("asset")
    release = contract.get("release_attestation")
    authenticode = contract.get("authenticode")
    expected_asset = {
        "name": ASSET_NAME,
        "bytes": ASSET_BYTES,
        "sha256": ASSET_SHA256,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "release_tag": RELEASE_TAG,
        "release_database_id": RELEASE_DATABASE_ID,
        "release_tag_object_sha1": RELEASE_TAG_OBJECT_SHA1,
        "release_commit_sha1": RELEASE_COMMIT_SHA1,
        "release_asset_id": ASSET_ID,
        "release_purl": RELEASE_PURL,
    }
    if (
        contract.get("schema_version") != SCHEMA_VERSION
        or contract.get("target") != TARGET
        or asset != expected_asset
        or not isinstance(release, dict)
        or release.get("predicate_type") != PREDICATE_TYPE
        or release.get("certificate_subject_alternative_name") != ATTESTER_SAN
        or not isinstance(authenticode, dict)
        or authenticode.get("required_status") != "Valid"
        or authenticode.get("required_signer_subject") != SIGNER_SUBJECT
    ):
        raise InnoToolchainEvidenceError("Inno toolchain evidence contract differs")


def _validate_output_directory(
    output: Path,
    *,
    repository: Path,
    asset_parent: Path,
    expected_names: frozenset[str],
) -> None:
    if _is_within(output, repository) or _is_within(output, asset_parent):
        raise InnoToolchainEvidenceError(
            "Toolchain evidence output must be outside repository and asset directory"
        )
    entries = list(output.iterdir())
    if {entry.name for entry in entries} != expected_names or len(entries) != len(expected_names):
        raise InnoToolchainEvidenceError(
            "Toolchain evidence output differs from the exact file boundary"
        )
    if any(_is_symbolic_path(entry) or not entry.is_file() for entry in entries):
        raise InnoToolchainEvidenceError(
            "Toolchain evidence output contains a symbolic or non-file entry"
        )


def _attestation_observation(path: Path) -> dict[str, object]:
    raw = _json_file(path, label="GitHub release attestation")
    try:
        bundle = raw["attestation"]["bundle"]
        envelope = bundle["dsseEnvelope"]
        result = raw["verificationResult"]
        statement = result["statement"]
        decoded = json.loads(base64.b64decode(envelope["payload"], validate=True))
        certificate_san = result["signature"]["certificate"]["subjectAlternativeName"]
        timestamps = result["verifiedTimestamps"]
        predicate = statement["predicate"]
        subjects = statement["subject"]
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as error:
        raise InnoToolchainEvidenceError(
            "GitHub release attestation structure is incomplete"
        ) from error
    if not isinstance(decoded, dict) or decoded != statement:
        raise InnoToolchainEvidenceError(
            "Release attestation DSSE payload differs from the verified statement"
        )
    if (
        bundle.get("mediaType") != "application/vnd.dev.sigstore.bundle.v0.3+json"
        or envelope.get("payloadType") != "application/vnd.in-toto+json"
        or statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != PREDICATE_TYPE
        or certificate_san != ATTESTER_SAN
    ):
        raise InnoToolchainEvidenceError("GitHub release attestation identity differs")
    if not isinstance(predicate, dict) or {
        "repository": predicate.get("repository"),
        "repositoryId": str(predicate.get("repositoryId")),
        "databaseId": str(predicate.get("databaseId")),
        "tag": predicate.get("tag"),
        "purl": predicate.get("purl"),
    } != {
        "repository": REPOSITORY,
        "repositoryId": str(REPOSITORY_ID),
        "databaseId": str(RELEASE_DATABASE_ID),
        "tag": RELEASE_TAG,
        "purl": RELEASE_PURL,
    }:
        raise InnoToolchainEvidenceError("Release attestation predicate differs")
    if not isinstance(subjects, list) or any(not isinstance(item, dict) for item in subjects):
        raise InnoToolchainEvidenceError("Release attestation subjects are missing")
    asset_subjects = [item for item in subjects if item.get("name") == ASSET_NAME]
    tag_subjects = [item for item in subjects if item.get("uri") == RELEASE_PURL]
    if len(asset_subjects) != 1 or asset_subjects[0].get("digest") != {"sha256": ASSET_SHA256}:
        raise InnoToolchainEvidenceError("Release attestation asset digest differs")
    if len(tag_subjects) != 1 or tag_subjects[0].get("digest") != {"sha1": RELEASE_TAG_OBJECT_SHA1}:
        raise InnoToolchainEvidenceError("Release attestation tag identity differs")
    if not isinstance(timestamps, list) or any(not isinstance(item, dict) for item in timestamps):
        raise InnoToolchainEvidenceError("Release attestation verified timestamps are missing")
    authorities = [
        item
        for item in timestamps
        if item.get("type") == "TimestampAuthority" and item.get("uri") == TIMESTAMP_AUTHORITY
    ]
    if len(authorities) != 1:
        raise InnoToolchainEvidenceError("Release attestation timestamp authority differs")
    verified_timestamp = authorities[0].get("timestamp")
    _timestamp(verified_timestamp, label="Release-attestation timestamp")
    return {
        "raw": _file_record(path),
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "release_tag": RELEASE_TAG,
        "release_database_id": RELEASE_DATABASE_ID,
        "release_tag_object_sha1": RELEASE_TAG_OBJECT_SHA1,
        "release_purl": RELEASE_PURL,
        "predicate_type": PREDICATE_TYPE,
        "certificate_subject_alternative_name": certificate_san,
        "verified_timestamp": verified_timestamp,
        "timestamp_authority": TIMESTAMP_AUTHORITY,
        "asset_name": ASSET_NAME,
        "asset_sha256": ASSET_SHA256,
    }


def _authenticode_observation(
    path: Path,
    *,
    asset: Path,
) -> tuple[dict[str, object], str]:
    raw = _json_file(path, label="Authenticode observation")
    expected_asset_path = str(asset)
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("asset_path") != expected_asset_path
        or raw.get("asset_sha256") != ASSET_SHA256
        or raw.get("status") != "Valid"
        or raw.get("signer_subject") != SIGNER_SUBJECT
    ):
        raise InnoToolchainEvidenceError("Authenticode observation identity differs")
    observed_at = raw.get("observed_at")
    if not isinstance(observed_at, str):
        raise InnoToolchainEvidenceError("Authenticode observation time must be a string")
    observed = _timestamp(observed_at, label="Authenticode observation time")
    not_before = _timestamp(raw.get("signer_not_before"), label="Signer not-before")
    not_after = _timestamp(raw.get("signer_not_after"), label="Signer not-after")
    if not not_before <= observed <= not_after:
        raise InnoToolchainEvidenceError(
            "Authenticode observation falls outside signer certificate validity"
        )
    required_strings = (
        "signer_issuer",
        "timestamp_subject",
    )
    if any(not isinstance(raw.get(field), str) or not raw[field] for field in required_strings):
        raise InnoToolchainEvidenceError("Authenticode certificate observation is incomplete")
    for field in ("signer_thumbprint", "timestamp_thumbprint"):
        if not isinstance(raw.get(field), str) or _THUMBPRINT_PATTERN.fullmatch(raw[field]) is None:
            raise InnoToolchainEvidenceError("Authenticode thumbprint observation differs")
    return (
        {
            "raw": _file_record(path),
            "status": "Valid",
            "signer_subject": SIGNER_SUBJECT,
            "signer_issuer": raw["signer_issuer"],
            "signer_thumbprint": raw["signer_thumbprint"],
            "signer_not_before": raw["signer_not_before"],
            "signer_not_after": raw["signer_not_after"],
            "timestamp_subject": raw["timestamp_subject"],
            "timestamp_thumbprint": raw["timestamp_thumbprint"],
        },
        observed_at,
    )


def _verifier_observation(
    path: Path,
    *,
    asset: Path,
    observed_at: str,
) -> dict[str, object]:
    raw = _json_file(path, label="GitHub release verifier observation")
    expected_command = [
        "release",
        "verify-asset",
        str(asset),
        "--repo",
        REPOSITORY,
        "--format",
        "json",
    ]
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("observed_at") != observed_at
        or raw.get("command") != expected_command
        or raw.get("exit_code") != 0
    ):
        raise InnoToolchainEvidenceError("Release verifier observation differs")
    program = _real_file(raw.get("program_path", ""), label="GitHub CLI verifier")
    if raw.get("program_bytes") != program.stat().st_size or raw.get(
        "program_sha256"
    ) != _sha256_file(program):
        raise InnoToolchainEvidenceError("GitHub CLI verifier file binding differs")
    version_output = raw.get("version_output")
    if not isinstance(version_output, str):
        raise InnoToolchainEvidenceError("GitHub CLI version observation is missing")
    match = _GH_VERSION_PATTERN.search(version_output)
    if match is None:
        raise InnoToolchainEvidenceError("GitHub CLI version output is malformed")
    return {
        "raw": _file_record(path),
        "program": _file_record(program),
        "version": match.group(1),
        "command": expected_command,
        "exit_code": 0,
    }


def _compose_evidence(
    *,
    asset_path: Path | str,
    project_file: Path | str,
    output_directory: Path | str,
    source_commit: str,
    expected_output_names: frozenset[str],
) -> dict[str, object]:
    if not isinstance(source_commit, str) or _SHA1_PATTERN.fullmatch(source_commit) is None:
        raise ValueError("Source commit must contain exactly 40 lowercase hexadecimal characters")
    asset = _real_file(asset_path, label="Inno Setup asset", expected_name=ASSET_NAME)
    if asset.stat().st_size != ASSET_BYTES or _sha256_file(asset) != ASSET_SHA256:
        raise InnoToolchainEvidenceError("Inno Setup asset size or SHA-256 differs")
    project = _real_file(project_file, label="Project file", expected_name="pyproject.toml")
    repository = project.parent
    contract = _real_file(
        repository / "distribution" / "windows" / CONTRACT_NAME,
        label="Inno toolchain evidence contract",
        expected_name=CONTRACT_NAME,
    )
    wrapper = _real_file(
        repository / "tools" / WRAPPER_NAME,
        label="Inno toolchain observation wrapper",
        expected_name=WRAPPER_NAME,
    )
    _validate_contract(contract)
    output = _real_directory(output_directory, label="Toolchain evidence output")
    _validate_output_directory(
        output,
        repository=repository,
        asset_parent=asset.parent,
        expected_names=expected_output_names,
    )
    attestation_path = _real_file(
        output / ATTESTATION_NAME,
        label="GitHub release attestation",
        expected_name=ATTESTATION_NAME,
    )
    authenticode_path = _real_file(
        output / AUTHENTICODE_NAME,
        label="Authenticode observation",
        expected_name=AUTHENTICODE_NAME,
    )
    verifier_path = _real_file(
        output / VERIFIER_NAME,
        label="GitHub release verifier observation",
        expected_name=VERIFIER_NAME,
    )
    attestation = _attestation_observation(attestation_path)
    authenticode, observed_at = _authenticode_observation(
        authenticode_path,
        asset=asset,
    )
    verifier = _verifier_observation(
        verifier_path,
        asset=asset,
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
        },
        "asset": {**_file_record(asset), "release_asset_id": ASSET_ID},
        "release_attestation": attestation,
        "authenticode": authenticode,
        "verifier": verifier,
        "execution_authorized": False,
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def create_inno_toolchain_evidence(
    asset_path: Path | str,
    *,
    project_file: Path | str,
    output_directory: Path | str,
    source_commit: str,
) -> Path:
    """Create canonical evidence from three successful raw Windows observations."""

    document = _compose_evidence(
        asset_path=asset_path,
        project_file=project_file,
        output_directory=output_directory,
        source_commit=source_commit,
        expected_output_names=RAW_NAMES,
    )
    _validate_schema(document)
    payload = _json_bytes(document)
    output = Path(output_directory).expanduser().absolute().resolve()
    evidence_path = output / EVIDENCE_NAME
    sidecar_path = output / SIDECAR_NAME
    written: list[Path] = []
    try:
        written.append(
            write_new_exact_file(
                payload,
                evidence_path,
                artifact_label="Inno toolchain evidence",
            )
        )
        digest = hashlib.sha256(payload).hexdigest()
        written.append(
            write_new_exact_file(
                f"{digest}  {EVIDENCE_NAME}\n".encode("ascii"),
                sidecar_path,
                artifact_label="Inno toolchain evidence sidecar",
            )
        )
        verify_inno_toolchain_evidence(
            evidence_path,
            expected_evidence_sha256=digest,
        )
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise
    return evidence_path


def verify_inno_toolchain_evidence(
    evidence_path: Path | str,
    *,
    expected_evidence_sha256: str,
) -> dict[str, object]:
    """Offline-verify exact raw files, source files, asset, and canonical evidence."""

    if (
        not isinstance(expected_evidence_sha256, str)
        or _SHA256_PATTERN.fullmatch(expected_evidence_sha256) is None
    ):
        raise ValueError("Expected evidence SHA-256 must contain 64 lowercase hex characters")
    path = _real_file(
        evidence_path,
        label="Inno toolchain evidence",
        expected_name=EVIDENCE_NAME,
    )
    sidecar = _real_file(
        path.with_name(SIDECAR_NAME),
        label="Inno toolchain evidence sidecar",
        expected_name=SIDECAR_NAME,
    )
    try:
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8"))
        sidecar_payload = sidecar.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InnoToolchainEvidenceError("Inno toolchain evidence is not readable") from error
    _validate_schema(document)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_evidence_sha256:
        raise InnoToolchainEvidenceError(
            "Inno toolchain evidence differs from the externally expected SHA-256"
        )
    if sidecar_payload != f"{digest}  {EVIDENCE_NAME}\n".encode("ascii"):
        raise InnoToolchainEvidenceError("Inno toolchain evidence sidecar is malformed")
    if payload != _json_bytes(document):
        raise InnoToolchainEvidenceError("Inno toolchain evidence is not canonical JSON")
    rebuilt = _compose_evidence(
        asset_path=document["asset"]["path"],
        project_file=document["source"]["project"]["path"],
        output_directory=path.parent,
        source_commit=document["source"]["commit_sha"],
        expected_output_names=COMPLETE_NAMES,
    )
    if document != rebuilt or payload != _json_bytes(rebuilt):
        raise InnoToolchainEvidenceError(
            "Inno toolchain evidence differs from reconstructed exact observations"
        )
    return document

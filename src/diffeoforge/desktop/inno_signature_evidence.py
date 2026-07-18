"""Create and verify evidence for an ISSigTool installer-signature observation."""

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
STATUS = "inno_signature_observation_not_installer_execution_or_release_authorization"
TARGET = "windows-x86_64-cpu"
EVIDENCE_NAME = "inno-signature-evidence.json"
SIDECAR_NAME = "inno-signature-evidence.sha256"
TOOL_ATTESTATION_NAME = "issigtool-release-attestation.json"
TOOL_AUTHENTICODE_NAME = "issigtool-authenticode-observation.json"
TOOL_VERIFIER_NAME = "issigtool-release-verifier-observation.json"
SIGNATURE_ATTESTATION_NAME = "inno-signature-release-attestation.json"
SIGNATURE_VERIFIER_NAME = "inno-signature-release-verifier-observation.json"
TAG_OBSERVATION_NAME = "inno-release-tag-observation.json"
KEY_CONTENT_NAME = "inno-public-key-content-observation.json"
API_VERIFIER_NAME = "inno-release-api-verifier-observation.json"
EXECUTION_NAME = "issigtool-verification-observation.json"
CONTRACT_NAME = "inno-signature-evidence-contract-v0.1.json"
WRAPPER_NAME = "observe_inno_signature.ps1"

REPOSITORY = "jrsoftware/issrc"
REPOSITORY_ID = 2_527_983
PREDICATE_TYPE = "https://in-toto.io/attestation/release/v0.2"
ATTESTER_SAN = "https://dotcom.releases.github.com"
TIMESTAMP_AUTHORITY = "timestamp.githubapp.com"
SIGNER_SUBJECT = "CN=Pyrsys B.V., O=Pyrsys B.V., S=Noord-Holland, C=NL"

INSTALLER_NAME = "innosetup-7.0.2-x64.exe"
INSTALLER_BYTES = 17_020_192
INSTALLER_SHA256 = "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1"
INSTALLER_ASSET_ID = 475_225_237

SIGNATURE_NAME = "innosetup-7.0.2-x64.exe.issig"
SIGNATURE_BYTES = 380
SIGNATURE_SHA256 = "b85f4a9c527ee573d308840e859ff3ca99c8a750acb259d51f111301c7ef71bd"
SIGNATURE_ASSET_ID = 475_225_360
INSTALLER_RELEASE_TAG = "is-7_0_2"
INSTALLER_RELEASE_DATABASE_ID = 352_994_135
INSTALLER_RELEASE_TAG_OBJECT_SHA1 = "d2509df69f828a7148294e29b2ca252c3250210c"
INSTALLER_RELEASE_COMMIT_SHA1 = "c25dc6479cdc3be28e682a025fcf60765bba3de0"
INSTALLER_RELEASE_PURL = "pkg:github/jrsoftware/issrc@is-7_0_2"

TOOL_NAME = "ISSigTool.exe"
TOOL_BYTES = 919_184
TOOL_SHA256 = "aea490d45665a88c0c832d25647d21c1b87962efedb25668caec05678e0fd7c6"
TOOL_ASSET_ID = 430_321_504
TOOL_RELEASE_TAG = "is-6_7_3"
TOOL_RELEASE_DATABASE_ID = 329_538_987
TOOL_RELEASE_TAG_OBJECT_SHA1 = "c7af86b4b2fd03371185df2b09a1dca8d472ab70"
TOOL_RELEASE_PURL = "pkg:github/jrsoftware/issrc@is-6_7_3"

KEY_NAME = "def02.ispublickey"
KEY_BYTES = 248
KEY_SHA256 = "32bea6bceb4ac7c4e6b3becdf3fb38de77378c5e76d494ab907d87cfab9e597b"
KEY_GIT_BLOB_SHA1 = "ab717206d876bd9d63a9bbb16bcf0e5f6928af73"
TAG_API_ENDPOINT = "repos/jrsoftware/issrc/git/tags/" + INSTALLER_RELEASE_TAG_OBJECT_SHA1
KEY_API_ENDPOINT = (
    "repos/jrsoftware/issrc/contents/def02.ispublickey?ref=" + INSTALLER_RELEASE_COMMIT_SHA1
)

PREREQUISITE_NAMES = frozenset(
    (
        TOOL_ATTESTATION_NAME,
        TOOL_AUTHENTICODE_NAME,
        TOOL_VERIFIER_NAME,
        SIGNATURE_ATTESTATION_NAME,
        SIGNATURE_VERIFIER_NAME,
        TAG_OBSERVATION_NAME,
        KEY_CONTENT_NAME,
        API_VERIFIER_NAME,
    )
)
RAW_NAMES = frozenset((*PREREQUISITE_NAMES, EXECUTION_NAME))
COMPLETE_NAMES = frozenset((*RAW_NAMES, EVIDENCE_NAME, SIDECAR_NAME))
MISSING_RELEASE_GATES = (
    "authenticode_signature_for_diffeoforge_outputs",
    "clean_windows_vm",
    "compiler_execution",
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
    "This document records one successful execution of an independently release-attested "
    "and Authenticode-validated ISSigTool executable to read and verify the ECDSA signature "
    "of one exact, non-executed Inno Setup installer. Offline verification rechecks the "
    "recorded outputs and all available byte and provenance bindings but does not repeat "
    "the network-backed GitHub checks or the cryptographic ISSigTool operation. It does "
    "not authorize installer execution, installation, compilation, redistribution, "
    "release, or security, numerical, scientific, or production-suitability claims."
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SHA1_PATTERN = re.compile(r"[0-9a-f]{40}")
_THUMBPRINT_PATTERN = re.compile(r"[0-9A-F]{40}")
_GH_VERSION_PATTERN = re.compile(r"gh version ([0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)")


class InnoSignatureEvidenceError(RuntimeError):
    """Raised when an Inno signature observation fails closed."""


def _is_symbolic_path(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction is not None and is_junction())


def _reject_symbolic_chain(path: Path, *, label: str) -> None:
    current = path
    while True:
        if current.exists() and _is_symbolic_path(current):
            raise InnoSignatureEvidenceError(f"{label} must not use a symbolic path: {current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _real_file(value: Path | str, *, label: str, expected_name: str | None = None) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_file():
        raise InnoSignatureEvidenceError(f"{label} must be an existing real file: {resolved}")
    if expected_name is not None and resolved.name != expected_name:
        raise InnoSignatureEvidenceError(f"{label} must be named {expected_name}")
    return resolved


def _real_directory(value: Path | str, *, label: str) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_dir():
        raise InnoSignatureEvidenceError(f"{label} must be an existing real directory: {resolved}")
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
        raise InnoSignatureEvidenceError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise InnoSignatureEvidenceError(f"{label} must be a JSON object")
    return value


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise InnoSignatureEvidenceError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InnoSignatureEvidenceError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise InnoSignatureEvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath("desktop-inno-signature-evidence-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: object) -> None:
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise InnoSignatureEvidenceError(
            f"Inno signature evidence schema violation at {location}: {first.message}"
        )


def _project_version(project_file: Path) -> str:
    try:
        document = tomllib.loads(project_file.read_text(encoding="utf-8"))
        project = document["project"]
        name = project["name"]
        version = project["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise InnoSignatureEvidenceError("Could not read exact project metadata") from error
    if name != "diffeoforge" or not isinstance(version, str) or not version:
        raise InnoSignatureEvidenceError("Project metadata must identify DiffeoForge")
    return version


def _validate_exact_file(
    path: Path,
    *,
    label: str,
    expected_bytes: int,
    expected_sha256: str,
) -> None:
    if path.stat().st_size != expected_bytes or _sha256_file(path) != expected_sha256:
        raise InnoSignatureEvidenceError(f"{label} size or SHA-256 differs")


def _validate_contract(path: Path) -> None:
    contract = _json_file(path, label="Inno signature evidence contract")
    installer = contract.get("installer")
    signature = contract.get("signature")
    tool = contract.get("signature_tool")
    key = contract.get("public_key")
    execution = contract.get("execution")
    if (
        contract.get("schema_version") != SCHEMA_VERSION
        or contract.get("target") != TARGET
        or installer
        != {
            "name": INSTALLER_NAME,
            "bytes": INSTALLER_BYTES,
            "sha256": INSTALLER_SHA256,
            "release_asset_id": INSTALLER_ASSET_ID,
        }
        or not isinstance(signature, dict)
        or signature.get("name") != SIGNATURE_NAME
        or signature.get("bytes") != SIGNATURE_BYTES
        or signature.get("sha256") != SIGNATURE_SHA256
        or signature.get("release_asset_id") != SIGNATURE_ASSET_ID
        or signature.get("release_tag") != INSTALLER_RELEASE_TAG
        or signature.get("release_tag_object_sha1") != INSTALLER_RELEASE_TAG_OBJECT_SHA1
        or not isinstance(tool, dict)
        or tool.get("name") != TOOL_NAME
        or tool.get("bytes") != TOOL_BYTES
        or tool.get("sha256") != TOOL_SHA256
        or tool.get("release_asset_id") != TOOL_ASSET_ID
        or tool.get("release_tag") != TOOL_RELEASE_TAG
        or tool.get("release_tag_object_sha1") != TOOL_RELEASE_TAG_OBJECT_SHA1
        or tool.get("required_authenticode_signer_subject") != SIGNER_SUBJECT
        or not isinstance(key, dict)
        or key.get("name") != KEY_NAME
        or key.get("bytes") != KEY_BYTES
        or key.get("sha256") != KEY_SHA256
        or key.get("git_blob_sha1") != KEY_GIT_BLOB_SHA1
        or key.get("release_commit_sha1") != INSTALLER_RELEASE_COMMIT_SHA1
        or key.get("content_api_path") != KEY_API_ENDPOINT
        or not isinstance(execution, dict)
        or execution.get("installer_execution") is not False
        or execution.get("execution_authorized") is not False
    ):
        raise InnoSignatureEvidenceError("Inno signature evidence contract differs")


def _validate_output_directory(
    output: Path,
    *,
    repository: Path,
    inputs: tuple[Path, ...],
    expected_names: frozenset[str],
) -> None:
    forbidden_roots = {repository, *(path.parent for path in inputs)}
    if any(_is_within(output, root) for root in forbidden_roots) or any(
        _is_within(path, output) for path in inputs
    ):
        raise InnoSignatureEvidenceError(
            "Signature evidence output must be outside repository and all inputs"
        )
    entries = list(output.iterdir())
    if {entry.name for entry in entries} != expected_names or len(entries) != len(expected_names):
        raise InnoSignatureEvidenceError(
            "Signature evidence output differs from the exact file boundary"
        )
    if any(_is_symbolic_path(entry) or not entry.is_file() for entry in entries):
        raise InnoSignatureEvidenceError(
            "Signature evidence output contains a symbolic or non-file entry"
        )


def _release_observation(
    path: Path,
    *,
    label: str,
    release_tag: str,
    release_database_id: int,
    release_tag_object_sha1: str,
    release_purl: str,
    subject_name: str,
    subject_sha256: str,
) -> dict[str, object]:
    raw = _json_file(path, label=label)
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
        raise InnoSignatureEvidenceError(f"{label} structure is incomplete") from error
    if not isinstance(decoded, dict) or decoded != statement:
        raise InnoSignatureEvidenceError(f"{label} DSSE payload differs")
    if (
        bundle.get("mediaType") != "application/vnd.dev.sigstore.bundle.v0.3+json"
        or envelope.get("payloadType") != "application/vnd.in-toto+json"
        or statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != PREDICATE_TYPE
        or certificate_san != ATTESTER_SAN
    ):
        raise InnoSignatureEvidenceError(f"{label} identity differs")
    expected_predicate = {
        "repository": REPOSITORY,
        "repositoryId": str(REPOSITORY_ID),
        "databaseId": str(release_database_id),
        "tag": release_tag,
        "purl": release_purl,
    }
    if (
        not isinstance(predicate, dict)
        or {
            "repository": predicate.get("repository"),
            "repositoryId": str(predicate.get("repositoryId")),
            "databaseId": str(predicate.get("databaseId")),
            "tag": predicate.get("tag"),
            "purl": predicate.get("purl"),
        }
        != expected_predicate
    ):
        raise InnoSignatureEvidenceError(f"{label} predicate differs")
    if not isinstance(subjects, list) or any(not isinstance(item, dict) for item in subjects):
        raise InnoSignatureEvidenceError(f"{label} subjects are missing")
    matching_files = [item for item in subjects if item.get("name") == subject_name]
    matching_tags = [item for item in subjects if item.get("uri") == release_purl]
    if len(matching_files) != 1 or matching_files[0].get("digest") != {"sha256": subject_sha256}:
        raise InnoSignatureEvidenceError(f"{label} file digest differs")
    if len(matching_tags) != 1 or matching_tags[0].get("digest") != {
        "sha1": release_tag_object_sha1
    }:
        raise InnoSignatureEvidenceError(f"{label} tag identity differs")
    if not isinstance(timestamps, list) or any(not isinstance(item, dict) for item in timestamps):
        raise InnoSignatureEvidenceError(f"{label} verified timestamps are missing")
    authorities = [
        item
        for item in timestamps
        if item.get("type") == "TimestampAuthority" and item.get("uri") == TIMESTAMP_AUTHORITY
    ]
    if len(authorities) != 1:
        raise InnoSignatureEvidenceError(f"{label} timestamp authority differs")
    verified_timestamp = authorities[0].get("timestamp")
    _timestamp(verified_timestamp, label=f"{label} timestamp")
    return {
        "raw": _file_record(path),
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "release_tag": release_tag,
        "release_database_id": release_database_id,
        "release_tag_object_sha1": release_tag_object_sha1,
        "release_purl": release_purl,
        "predicate_type": PREDICATE_TYPE,
        "certificate_subject_alternative_name": certificate_san,
        "verified_timestamp": verified_timestamp,
        "timestamp_authority": TIMESTAMP_AUTHORITY,
        "subject_name": subject_name,
        "subject_sha256": subject_sha256,
    }


def _authenticode_observation(path: Path, *, tool: Path) -> tuple[dict[str, object], str]:
    raw = _json_file(path, label="ISSigTool Authenticode observation")
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("asset_path") != str(tool)
        or raw.get("asset_sha256") != TOOL_SHA256
        or raw.get("status") != "Valid"
        or raw.get("signer_subject") != SIGNER_SUBJECT
    ):
        raise InnoSignatureEvidenceError("ISSigTool Authenticode identity differs")
    observed_at = raw.get("observed_at")
    observed = _timestamp(observed_at, label="ISSigTool Authenticode observation time")
    not_before = _timestamp(raw.get("signer_not_before"), label="Signer not-before")
    not_after = _timestamp(raw.get("signer_not_after"), label="Signer not-after")
    if not not_before <= observed <= not_after:
        raise InnoSignatureEvidenceError(
            "ISSigTool Authenticode observation falls outside signer validity"
        )
    if any(
        not isinstance(raw.get(field), str) or not raw[field]
        for field in ("signer_issuer", "timestamp_subject")
    ):
        raise InnoSignatureEvidenceError("ISSigTool Authenticode observation is incomplete")
    for field in ("signer_thumbprint", "timestamp_thumbprint"):
        if not isinstance(raw.get(field), str) or _THUMBPRINT_PATTERN.fullmatch(raw[field]) is None:
            raise InnoSignatureEvidenceError("ISSigTool Authenticode thumbprint differs")
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
        str(observed_at),
    )


def _github_program(raw: dict, *, label: str) -> tuple[dict[str, object], str]:
    program = _real_file(raw.get("program_path", ""), label=f"{label} GitHub CLI")
    if raw.get("program_bytes") != program.stat().st_size or raw.get(
        "program_sha256"
    ) != _sha256_file(program):
        raise InnoSignatureEvidenceError(f"{label} GitHub CLI binding differs")
    version_output = raw.get("version_output")
    if not isinstance(version_output, str):
        raise InnoSignatureEvidenceError(f"{label} GitHub CLI version is missing")
    match = _GH_VERSION_PATTERN.search(version_output)
    if match is None:
        raise InnoSignatureEvidenceError(f"{label} GitHub CLI version is malformed")
    return _file_record(program), match.group(1)


def _release_verifier_observation(
    path: Path,
    *,
    label: str,
    subject: Path,
    release_tag: str,
    observed_at: str,
) -> dict[str, object]:
    raw = _json_file(path, label=label)
    expected_command = [
        "release",
        "verify-asset",
        release_tag,
        str(subject),
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
        raise InnoSignatureEvidenceError(f"{label} differs")
    program, version = _github_program(raw, label=label)
    return {
        "raw": _file_record(path),
        "program": program,
        "version": version,
        "command": expected_command,
        "exit_code": 0,
    }


def _tag_observation(path: Path) -> dict[str, object]:
    raw = _json_file(path, label="Inno release tag observation")
    verification = raw.get("verification")
    target = raw.get("object")
    if (
        raw.get("sha") != INSTALLER_RELEASE_TAG_OBJECT_SHA1
        or raw.get("tag") != INSTALLER_RELEASE_TAG
        or not isinstance(target, dict)
        or target.get("type") != "commit"
        or target.get("sha") != INSTALLER_RELEASE_COMMIT_SHA1
        or not isinstance(verification, dict)
        or verification.get("verified") is not True
        or verification.get("reason") != "valid"
    ):
        raise InnoSignatureEvidenceError("Inno release tag identity or verification differs")
    payload = verification.get("payload")
    signature = verification.get("signature")
    if (
        not isinstance(payload, str)
        or f"object {INSTALLER_RELEASE_COMMIT_SHA1}\ntype commit\ntag {INSTALLER_RELEASE_TAG}\n"
        not in payload
        or not isinstance(signature, str)
        or "BEGIN PGP SIGNATURE" not in signature
    ):
        raise InnoSignatureEvidenceError("Inno release tag signature record is incomplete")
    verified_at = verification.get("verified_at")
    _timestamp(verified_at, label="Inno release tag verification time")
    return {
        "raw": _file_record(path),
        "tag": INSTALLER_RELEASE_TAG,
        "tag_object_sha1": INSTALLER_RELEASE_TAG_OBJECT_SHA1,
        "commit_sha1": INSTALLER_RELEASE_COMMIT_SHA1,
        "verified": True,
        "reason": "valid",
        "verified_at": verified_at,
    }


def _key_content_observation(path: Path, *, key: Path) -> dict[str, object]:
    raw = _json_file(path, label="Inno public-key content observation")
    try:
        encoded = raw["content"]
        if not isinstance(encoded, str):
            raise TypeError
        decoded = base64.b64decode("".join(encoded.split()), validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error) as error:
        raise InnoSignatureEvidenceError("Inno public-key content is not valid base64") from error
    expected_download = (
        "https://raw.githubusercontent.com/jrsoftware/issrc/"
        f"{INSTALLER_RELEASE_COMMIT_SHA1}/{KEY_NAME}"
    )
    if (
        raw.get("type") != "file"
        or raw.get("name") != KEY_NAME
        or raw.get("path") != KEY_NAME
        or raw.get("sha") != KEY_GIT_BLOB_SHA1
        or raw.get("size") != KEY_BYTES
        or raw.get("encoding") != "base64"
        or raw.get("download_url") != expected_download
        or decoded != key.read_bytes()
        or _sha256_file(key) != KEY_SHA256
    ):
        raise InnoSignatureEvidenceError("Inno public-key content identity differs")
    return {
        "raw": _file_record(path),
        "git_blob_sha1": KEY_GIT_BLOB_SHA1,
        "release_commit_sha1": INSTALLER_RELEASE_COMMIT_SHA1,
        "download_url": expected_download,
        "content_sha256": KEY_SHA256,
    }


def _api_verifier_observation(
    path: Path,
    *,
    output: Path,
    observed_at: str,
) -> dict[str, object]:
    raw = _json_file(path, label="Inno release API verifier observation")
    expected_commands = [
        {
            "arguments": ["api", TAG_API_ENDPOINT],
            "exit_code": 0,
            "output_file": TAG_OBSERVATION_NAME,
            "output_sha256": _sha256_file(output / TAG_OBSERVATION_NAME),
        },
        {
            "arguments": ["api", KEY_API_ENDPOINT],
            "exit_code": 0,
            "output_file": KEY_CONTENT_NAME,
            "output_sha256": _sha256_file(output / KEY_CONTENT_NAME),
        },
    ]
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("observed_at") != observed_at
        or raw.get("commands") != expected_commands
    ):
        raise InnoSignatureEvidenceError("Inno release API verifier observation differs")
    program, version = _github_program(raw, label="Inno release API verifier")
    return {
        "raw": _file_record(path),
        "program": program,
        "version": version,
        "commands": expected_commands,
    }


def _execution_observation(
    path: Path,
    *,
    installer: Path,
    signature: Path,
    key: Path,
    tool: Path,
    observed_at: str,
) -> dict[str, object]:
    raw = _json_file(path, label="ISSigTool verification observation")
    expected_command = [f"--key-file={key}", "verify", str(installer)]
    expected_hashes = {
        "installer_sha256": INSTALLER_SHA256,
        "signature_sha256": SIGNATURE_SHA256,
        "public_key_sha256": KEY_SHA256,
        "signature_tool_sha256": TOOL_SHA256,
    }
    if (
        raw.get("schema_version") != SCHEMA_VERSION
        or raw.get("observed_at") != observed_at
        or raw.get("program_path") != str(tool)
        or raw.get("program_bytes") != TOOL_BYTES
        or raw.get("program_sha256") != TOOL_SHA256
        or raw.get("signature_path") != str(signature)
        or raw.get("command") != expected_command
        or raw.get("exit_code") != 0
        or raw.get("output_lines") != [f"{installer}: OK"]
        or raw.get("inputs_before") != expected_hashes
        or raw.get("inputs_after") != expected_hashes
        or raw.get("signature_tool_execution_scope") != "verify_exact_installer_signature_only"
        or raw.get("installer_execution") is not False
    ):
        raise InnoSignatureEvidenceError("ISSigTool verification observation differs")
    return {
        "raw": _file_record(path),
        "program": _file_record(tool),
        "command": expected_command,
        "exit_code": 0,
        "output_lines": [f"{installer}: OK"],
        "inputs_before": expected_hashes,
        "inputs_after": expected_hashes,
        "signature_tool_execution_scope": "verify_exact_installer_signature_only",
        "installer_execution": False,
    }


def _inputs(
    *,
    installer_path: Path | str,
    signature_path: Path | str,
    public_key_path: Path | str,
    signature_tool_path: Path | str,
    project_file: Path | str,
) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
    installer = _real_file(
        installer_path, label="Inno Setup installer", expected_name=INSTALLER_NAME
    )
    signature = _real_file(
        signature_path, label="Inno Setup signature", expected_name=SIGNATURE_NAME
    )
    key = _real_file(public_key_path, label="Inno public key", expected_name=KEY_NAME)
    tool = _real_file(signature_tool_path, label="ISSigTool", expected_name=TOOL_NAME)
    if signature != installer.with_name(SIGNATURE_NAME):
        raise InnoSignatureEvidenceError("Inno signature must be adjacent to the installer")
    _validate_exact_file(
        installer,
        label="Inno Setup installer",
        expected_bytes=INSTALLER_BYTES,
        expected_sha256=INSTALLER_SHA256,
    )
    _validate_exact_file(
        signature,
        label="Inno Setup signature",
        expected_bytes=SIGNATURE_BYTES,
        expected_sha256=SIGNATURE_SHA256,
    )
    _validate_exact_file(
        key,
        label="Inno public key",
        expected_bytes=KEY_BYTES,
        expected_sha256=KEY_SHA256,
    )
    _validate_exact_file(
        tool,
        label="ISSigTool",
        expected_bytes=TOOL_BYTES,
        expected_sha256=TOOL_SHA256,
    )
    project = _real_file(project_file, label="Project file", expected_name="pyproject.toml")
    repository = project.parent
    contract = _real_file(
        repository / "distribution" / "windows" / CONTRACT_NAME,
        label="Inno signature evidence contract",
        expected_name=CONTRACT_NAME,
    )
    wrapper = _real_file(
        repository / "tools" / WRAPPER_NAME,
        label="Inno signature observation wrapper",
        expected_name=WRAPPER_NAME,
    )
    _validate_contract(contract)
    return installer, signature, key, tool, project, repository, contract, wrapper


def _compose_prerequisites(
    *,
    installer_path: Path | str,
    signature_path: Path | str,
    public_key_path: Path | str,
    signature_tool_path: Path | str,
    project_file: Path | str,
    output_directory: Path | str,
    source_commit: str,
    expected_output_names: frozenset[str],
) -> dict[str, object]:
    if not isinstance(source_commit, str) or _SHA1_PATTERN.fullmatch(source_commit) is None:
        raise ValueError("Source commit must contain exactly 40 lowercase hexadecimal characters")
    (
        installer,
        signature,
        key,
        tool,
        project,
        repository,
        contract,
        wrapper,
    ) = _inputs(
        installer_path=installer_path,
        signature_path=signature_path,
        public_key_path=public_key_path,
        signature_tool_path=signature_tool_path,
        project_file=project_file,
    )
    output = _real_directory(output_directory, label="Inno signature evidence output")
    _validate_output_directory(
        output,
        repository=repository,
        inputs=(installer, signature, key, tool),
        expected_names=expected_output_names,
    )
    tool_attestation = _release_observation(
        _real_file(
            output / TOOL_ATTESTATION_NAME,
            label="ISSigTool release attestation",
            expected_name=TOOL_ATTESTATION_NAME,
        ),
        label="ISSigTool release attestation",
        release_tag=TOOL_RELEASE_TAG,
        release_database_id=TOOL_RELEASE_DATABASE_ID,
        release_tag_object_sha1=TOOL_RELEASE_TAG_OBJECT_SHA1,
        release_purl=TOOL_RELEASE_PURL,
        subject_name=TOOL_NAME,
        subject_sha256=TOOL_SHA256,
    )
    tool_authenticode, observed_at = _authenticode_observation(
        _real_file(
            output / TOOL_AUTHENTICODE_NAME,
            label="ISSigTool Authenticode observation",
            expected_name=TOOL_AUTHENTICODE_NAME,
        ),
        tool=tool,
    )
    tool_verifier = _release_verifier_observation(
        _real_file(
            output / TOOL_VERIFIER_NAME,
            label="ISSigTool release verifier observation",
            expected_name=TOOL_VERIFIER_NAME,
        ),
        label="ISSigTool release verifier observation",
        subject=tool,
        release_tag=TOOL_RELEASE_TAG,
        observed_at=observed_at,
    )
    signature_attestation = _release_observation(
        _real_file(
            output / SIGNATURE_ATTESTATION_NAME,
            label="Inno signature release attestation",
            expected_name=SIGNATURE_ATTESTATION_NAME,
        ),
        label="Inno signature release attestation",
        release_tag=INSTALLER_RELEASE_TAG,
        release_database_id=INSTALLER_RELEASE_DATABASE_ID,
        release_tag_object_sha1=INSTALLER_RELEASE_TAG_OBJECT_SHA1,
        release_purl=INSTALLER_RELEASE_PURL,
        subject_name=SIGNATURE_NAME,
        subject_sha256=SIGNATURE_SHA256,
    )
    signature_verifier = _release_verifier_observation(
        _real_file(
            output / SIGNATURE_VERIFIER_NAME,
            label="Inno signature release verifier observation",
            expected_name=SIGNATURE_VERIFIER_NAME,
        ),
        label="Inno signature release verifier observation",
        subject=signature,
        release_tag=INSTALLER_RELEASE_TAG,
        observed_at=observed_at,
    )
    release_tag = _tag_observation(
        _real_file(
            output / TAG_OBSERVATION_NAME,
            label="Inno release tag observation",
            expected_name=TAG_OBSERVATION_NAME,
        )
    )
    key_content = _key_content_observation(
        _real_file(
            output / KEY_CONTENT_NAME,
            label="Inno public-key content observation",
            expected_name=KEY_CONTENT_NAME,
        ),
        key=key,
    )
    api_verifier = _api_verifier_observation(
        _real_file(
            output / API_VERIFIER_NAME,
            label="Inno release API verifier observation",
            expected_name=API_VERIFIER_NAME,
        ),
        output=output,
        observed_at=observed_at,
    )
    return {
        "observed_at": observed_at,
        "source": {
            "commit_sha": source_commit,
            "diffeoforge_version": _project_version(project),
            "project": _file_record(project),
            "contract": _file_record(contract),
            "wrapper": _file_record(wrapper),
        },
        "installer_path": installer,
        "signature_path": signature,
        "key_path": key,
        "tool_path": tool,
        "installer": {**_file_record(installer), "release_asset_id": INSTALLER_ASSET_ID},
        "signature": {
            **_file_record(signature),
            "release_asset_id": SIGNATURE_ASSET_ID,
            "release_attestation": signature_attestation,
            "release_verifier": signature_verifier,
        },
        "signature_tool": {
            **_file_record(tool),
            "release_asset_id": TOOL_ASSET_ID,
            "release_attestation": tool_attestation,
            "authenticode": tool_authenticode,
            "release_verifier": tool_verifier,
        },
        "public_key": {
            **_file_record(key),
            "release_tag": release_tag,
            "content": key_content,
        },
        "github_api_verifier": api_verifier,
    }


def verify_inno_signature_prerequisites(
    installer_path: Path | str,
    *,
    signature_path: Path | str,
    public_key_path: Path | str,
    signature_tool_path: Path | str,
    project_file: Path | str,
    output_directory: Path | str,
    source_commit: str,
) -> dict[str, object]:
    """Validate every prerequisite before ISSigTool is allowed to execute."""

    prerequisites = _compose_prerequisites(
        installer_path=installer_path,
        signature_path=signature_path,
        public_key_path=public_key_path,
        signature_tool_path=signature_tool_path,
        project_file=project_file,
        output_directory=output_directory,
        source_commit=source_commit,
        expected_output_names=PREREQUISITE_NAMES,
    )
    return {
        "status": "issigtool_verifier_prerequisites_satisfied",
        "installer_sha256": prerequisites["installer"]["sha256"],
        "signature_sha256": prerequisites["signature"]["sha256"],
        "public_key_sha256": prerequisites["public_key"]["sha256"],
        "signature_tool_sha256": prerequisites["signature_tool"]["sha256"],
        "signature_tool_execution_scope": "verify_exact_installer_signature_only",
        "installer_execution_authorized": False,
    }


def _compose_evidence(
    *,
    installer_path: Path | str,
    signature_path: Path | str,
    public_key_path: Path | str,
    signature_tool_path: Path | str,
    project_file: Path | str,
    output_directory: Path | str,
    source_commit: str,
    expected_output_names: frozenset[str],
) -> dict[str, object]:
    prerequisites = _compose_prerequisites(
        installer_path=installer_path,
        signature_path=signature_path,
        public_key_path=public_key_path,
        signature_tool_path=signature_tool_path,
        project_file=project_file,
        output_directory=output_directory,
        source_commit=source_commit,
        expected_output_names=expected_output_names,
    )
    output = Path(output_directory).expanduser().absolute().resolve()
    execution = _execution_observation(
        _real_file(
            output / EXECUTION_NAME,
            label="ISSigTool verification observation",
            expected_name=EXECUTION_NAME,
        ),
        installer=prerequisites.pop("installer_path"),
        signature=prerequisites.pop("signature_path"),
        key=prerequisites.pop("key_path"),
        tool=prerequisites.pop("tool_path"),
        observed_at=str(prerequisites["observed_at"]),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "target": TARGET,
        **prerequisites,
        "issigtool_execution": execution,
        "installer_execution_authorized": False,
        "execution_authorized": False,
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def create_inno_signature_evidence(
    installer_path: Path | str,
    *,
    signature_path: Path | str,
    public_key_path: Path | str,
    signature_tool_path: Path | str,
    project_file: Path | str,
    output_directory: Path | str,
    source_commit: str,
) -> Path:
    """Create canonical evidence from nine successful raw observations."""

    document = _compose_evidence(
        installer_path=installer_path,
        signature_path=signature_path,
        public_key_path=public_key_path,
        signature_tool_path=signature_tool_path,
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
                artifact_label="Inno signature evidence",
            )
        )
        digest = hashlib.sha256(payload).hexdigest()
        written.append(
            write_new_exact_file(
                f"{digest}  {EVIDENCE_NAME}\n".encode("ascii"),
                sidecar_path,
                artifact_label="Inno signature evidence sidecar",
            )
        )
        verify_inno_signature_evidence(
            evidence_path,
            expected_evidence_sha256=digest,
        )
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise
    return evidence_path


def verify_inno_signature_evidence(
    evidence_path: Path | str,
    *,
    expected_evidence_sha256: str,
) -> dict[str, object]:
    """Offline-verify all inputs, observations, provenance, and canonical evidence."""

    if (
        not isinstance(expected_evidence_sha256, str)
        or _SHA256_PATTERN.fullmatch(expected_evidence_sha256) is None
    ):
        raise ValueError("Expected evidence SHA-256 must contain 64 lowercase hex characters")
    path = _real_file(evidence_path, label="Inno signature evidence", expected_name=EVIDENCE_NAME)
    sidecar = _real_file(
        path.with_name(SIDECAR_NAME),
        label="Inno signature evidence sidecar",
        expected_name=SIDECAR_NAME,
    )
    try:
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8"))
        sidecar_payload = sidecar.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InnoSignatureEvidenceError("Inno signature evidence is not readable") from error
    _validate_schema(document)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_evidence_sha256:
        raise InnoSignatureEvidenceError(
            "Inno signature evidence differs from the externally expected SHA-256"
        )
    if sidecar_payload != f"{digest}  {EVIDENCE_NAME}\n".encode("ascii"):
        raise InnoSignatureEvidenceError("Inno signature evidence sidecar is malformed")
    if payload != _json_bytes(document):
        raise InnoSignatureEvidenceError("Inno signature evidence is not canonical JSON")
    rebuilt = _compose_evidence(
        installer_path=document["installer"]["path"],
        signature_path=document["signature"]["path"],
        public_key_path=document["public_key"]["path"],
        signature_tool_path=document["signature_tool"]["path"],
        project_file=document["source"]["project"]["path"],
        output_directory=path.parent,
        source_commit=document["source"]["commit_sha"],
        expected_output_names=COMPLETE_NAMES,
    )
    if document != rebuilt or payload != _json_bytes(rebuilt):
        raise InnoSignatureEvidenceError(
            "Inno signature evidence differs from reconstructed exact observations"
        )
    return document

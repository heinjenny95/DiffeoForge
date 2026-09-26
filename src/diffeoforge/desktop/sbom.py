"""Create and verify deterministic CycloneDX post-build SBOM evidence."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import quote

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.dependency_metadata_evidence import (
    EVIDENCE_NAME as DEPENDENCY_EVIDENCE_NAME,
)
from diffeoforge.desktop.dependency_metadata_evidence import (
    verify_desktop_dependency_metadata_evidence,
)
from diffeoforge.desktop.freeze_evidence import (
    MANIFEST_NAME as FREEZE_EVIDENCE_NAME,
)
from diffeoforge.desktop.freeze_evidence import (
    verify_desktop_freeze_evidence,
    verify_desktop_freeze_evidence_document,
)
from diffeoforge.exact_file import write_new_exact_file

SPEC_VERSION = "1.7"
BUILDER_DISTRIBUTION = "cyclonedx-python-lib"
BUILDER_VERSION = "11.11.0"
SBOM_NAME = "freeze-sbom.cdx.json"
SIDECAR_NAME = "freeze-sbom.cdx.sha256"
TARGET = "windows-x86_64-cpu"
STATUS = "post_build_sbom_not_license_or_release_approval"
SCIENTIFIC_BOUNDARY = (
    "This deterministic post-build SBOM maps exact, externally hash-bound Windows "
    "freeze and installed-distribution metadata evidence. Its incomplete composition "
    "does not prove a resolved runtime dependency graph. License expressions and "
    "license-related evidence remain unreviewed and do not imply compatibility or "
    "redistribution approval. This is not installer, security, numerical, biological, "
    "or production-suitability evidence."
)
MISSING_RELEASE_GATES = (
    "authenticode_signature",
    "clean_windows_vm",
    "cpu_numerical_release_validation",
    "crash_reconciliation",
    "installer_and_uninstaller",
    "license_compatibility_review",
    "license_inventory_human_review",
    "no_network_observation",
    "redistribution_approval",
    "windows_defender_scan",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class DesktopSbomError(RuntimeError):
    """Raised when deterministic SBOM creation or verification fails closed."""


def _is_symbolic_path(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction is not None and is_junction())


def _expected_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Expected {label} SHA-256 must be a string")
    normalized = value.lower()
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        raise ValueError(
            f"Expected {label} SHA-256 must contain 64 hexadecimal characters"
        )
    return normalized


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: dict) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _normalized_name(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise DesktopSbomError("Runtime distribution names must be nonempty strings")
    normalized = re.sub(r"[-_.]+", "-", value).lower()
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) is None:
        raise DesktopSbomError(
            f"Runtime distribution name cannot be normalized safely: {value!r}"
        )
    return normalized


def _purl(name: str, version: str) -> str:
    if not isinstance(version, str) or not version:
        raise DesktopSbomError("Runtime distribution versions must be nonempty strings")
    return f"pkg:pypi/{_normalized_name(name)}@{quote(version, safe='-._~')}"


def _builder_api() -> tuple[type, object, Callable[[str], bool]]:
    try:
        observed = importlib.metadata.version(BUILDER_DISTRIBUTION)
        from cyclonedx.schema import SchemaVersion
        from cyclonedx.spdx import is_expression
        from cyclonedx.validation.json import JsonStrictValidator
    except (ImportError, importlib.metadata.PackageNotFoundError) as error:
        raise DesktopSbomError(
            f"SBOM creation and verification require builder-only "
            f"{BUILDER_DISTRIBUTION}=={BUILDER_VERSION}"
        ) from error
    if observed != BUILDER_VERSION:
        raise DesktopSbomError(
            f"SBOM builder version differs: expected {BUILDER_VERSION}, "
            f"observed {observed}"
        )
    return JsonStrictValidator, SchemaVersion.V1_7, is_expression


def _validate_cyclonedx(payload: bytes) -> None:
    validator_type, schema_version, _ = _builder_api()
    try:
        text = payload.decode("utf-8")
    except UnicodeError as error:
        raise DesktopSbomError("CycloneDX SBOM is not valid UTF-8") from error
    error = validator_type(schema_version).validate_str(text)
    if error is not None:
        raise DesktopSbomError(f"CycloneDX 1.7 schema validation failed: {error}")


def _property(name: str, value: object) -> dict[str, str]:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return {"name": name, "value": rendered}


def _sorted_properties(values: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(values, key=lambda value: (value["name"], value["value"]))


def _package_component(
    package: Mapping[str, object],
    *,
    is_spdx_expression: Callable[[str], bool],
) -> dict:
    name = str(package["name"])
    version = str(package["version"])
    metadata = package["metadata"]
    if not isinstance(metadata, Mapping):
        raise DesktopSbomError(f"Dependency metadata is not an object: {name}")
    purl = _purl(name, version)
    properties = [
        _property("diffeoforge:evidence:metadata-bytes", metadata["bytes"]),
        _property("diffeoforge:evidence:metadata-name", metadata["name"]),
        _property("diffeoforge:evidence:metadata-sha256", metadata["sha256"]),
        _property(
            "diffeoforge:evidence:metadata-version",
            metadata["metadata_version"],
        ),
        _property("diffeoforge:evidence:review-status", package["review_status"]),
    ]
    license_field = metadata["license_field"]
    if license_field is not None:
        properties.append(
            _property("diffeoforge:evidence:legacy-license-field", license_field)
        )
    for classifier in metadata["license_classifiers"]:
        properties.append(
            _property("diffeoforge:evidence:license-classifier", classifier)
        )
    for declared in metadata["license_files_declared"]:
        properties.append(
            _property("diffeoforge:evidence:declared-license-file", declared)
        )
    for record in package["license_files"]:
        properties.append(
            _property("diffeoforge:evidence:license-file-record", record)
        )
    for unresolved in package["unresolved_declared_license_files"]:
        properties.append(
            _property(
                "diffeoforge:evidence:unresolved-declared-license-file",
                unresolved,
            )
        )
    for observation in package["observations"]:
        properties.append(
            _property("diffeoforge:evidence:license-observation", observation)
        )
    component = {
        "type": "library",
        "bom-ref": purl,
        "name": name,
        "version": version,
        "purl": purl,
        "scope": "required",
        "properties": _sorted_properties(properties),
    }
    expression = metadata["license_expression"]
    if expression is not None:
        if not isinstance(expression, str) or not is_spdx_expression(expression):
            raise DesktopSbomError(
                f"Dependency metadata contains an invalid SPDX License-Expression: {name}"
            )
        component["licenses"] = [{"expression": expression}]
    return component


def _cross_check_sources(freeze: dict, dependencies: dict) -> None:
    if freeze["schema_version"] not in {"0.3", "0.4"}:
        raise DesktopSbomError(
            "CycloneDX SBOM requires freeze schema_version 0.3 or 0.4"
        )
    if freeze["target"] != TARGET or dependencies["target"] != TARGET:
        raise DesktopSbomError("SBOM source target differs from windows-x86_64-cpu")
    source = dependencies["source"]
    if source["freeze_evidence_schema_version"] != freeze["schema_version"]:
        raise DesktopSbomError("Dependency evidence freeze schema binding differs")
    if source["source_commit_sha"] != freeze["source"]["commit_sha"]:
        raise DesktopSbomError("Dependency evidence source commit binding differs")
    if source["bundle_inventory_sha256"] != freeze["bundle"]["inventory_sha256"]:
        raise DesktopSbomError("Dependency evidence bundle inventory binding differs")
    runtime_packages = {
        _normalized_name(name): version
        for name, version in freeze["runtime_packages"].items()
    }
    if len(runtime_packages) != len(freeze["runtime_packages"]):
        raise DesktopSbomError(
            "Freeze runtime package names normalize to duplicate values"
        )
    observed_packages = {
        package["name"]: package["version"] for package in dependencies["packages"]
    }
    if observed_packages != runtime_packages:
        raise DesktopSbomError(
            "Dependency evidence package set differs from freeze runtime packages"
        )


def _source_documents(
    freeze_evidence_path: Path | str,
    dependency_evidence_path: Path | str,
    *,
    expected_freeze_evidence_sha256: str,
    expected_dependency_evidence_sha256: str,
) -> tuple[dict, dict, str, str]:
    freeze_sha256 = _expected_sha256(
        expected_freeze_evidence_sha256, label="freeze evidence"
    )
    dependency_sha256 = _expected_sha256(
        expected_dependency_evidence_sha256, label="dependency evidence"
    )
    freeze = verify_desktop_freeze_evidence_document(
        freeze_evidence_path,
        expected_sha256=freeze_sha256,
    )
    dependency_path = Path(dependency_evidence_path).expanduser().absolute()
    if dependency_path.name != DEPENDENCY_EVIDENCE_NAME:
        raise DesktopSbomError(
            f"Dependency evidence must be named {DEPENDENCY_EVIDENCE_NAME}"
        )
    if _is_symbolic_path(dependency_path) or not dependency_path.is_file():
        raise DesktopSbomError("Dependency evidence is missing or symbolic")
    try:
        dependency_payload = dependency_path.read_bytes()
    except OSError as error:
        raise DesktopSbomError("Dependency evidence is not readable") from error
    if _sha256_bytes(dependency_payload) != dependency_sha256:
        raise DesktopSbomError(
            "Dependency evidence differs from the externally expected SHA-256"
        )
    dependencies = verify_desktop_dependency_metadata_evidence(
        dependency_path,
        expected_freeze_evidence_sha256=freeze_sha256,
    )
    if dependencies["source"]["freeze_evidence_sha256"] != freeze_sha256:
        raise DesktopSbomError("Dependency evidence freeze SHA-256 binding differs")
    _cross_check_sources(freeze, dependencies)
    return freeze, dependencies, freeze_sha256, dependency_sha256


def _bom_document(
    freeze: dict,
    dependencies: dict,
    *,
    freeze_sha256: str,
    dependency_sha256: str,
) -> dict:
    _, _, is_spdx_expression = _builder_api()
    components = [
        _package_component(package, is_spdx_expression=is_spdx_expression)
        for package in dependencies["packages"]
    ]
    components.sort(key=lambda component: component["purl"])
    inventory_sha256 = freeze["bundle"]["inventory_sha256"]
    root_ref = f"urn:diffeoforge:{TARGET}:{inventory_sha256}"
    root_properties = [
        _property("diffeoforge:evidence:status", STATUS),
        _property("diffeoforge:evidence:target", TARGET),
        _property("diffeoforge:evidence:source-commit-sha", freeze["source"]["commit_sha"]),
        _property("diffeoforge:evidence:bundle-inventory-sha256", inventory_sha256),
        _property("diffeoforge:evidence:freeze-evidence-sha256", freeze_sha256),
        _property("diffeoforge:evidence:dependency-evidence-sha256", dependency_sha256),
        _property(
            "diffeoforge:evidence:package-set-sha256",
            dependencies["package_set_sha256"],
        ),
        _property("diffeoforge:evidence:composition", "incomplete"),
        _property("diffeoforge:evidence:license-review", "not_reviewed"),
        _property("diffeoforge:evidence:redistribution-review", "not_reviewed"),
        _property("diffeoforge:evidence:scientific-boundary", SCIENTIFIC_BOUNDARY),
    ]
    root_properties.extend(
        _property("diffeoforge:evidence:missing-release-gate", gate)
        for gate in MISSING_RELEASE_GATES
    )
    tool_purl = _purl(BUILDER_DISTRIBUTION, BUILDER_VERSION)
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.7.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "serialNumber": (
            f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, dependency_sha256)}"
        ),
        "version": 1,
        "metadata": {
            "timestamp": freeze["created_at"],
            "lifecycles": [{"phase": "post-build"}],
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "bom-ref": tool_purl,
                        "name": BUILDER_DISTRIBUTION,
                        "version": BUILDER_VERSION,
                        "purl": tool_purl,
                    }
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": "DiffeoForge",
                "version": freeze["runtime_packages"]["diffeoforge"],
                "properties": _sorted_properties(root_properties),
            },
        },
        "components": components,
        "compositions": [{"aggregate": "incomplete", "assemblies": [root_ref]}],
    }


def _output_directory(value: Path | str, *, bundle: Path) -> Path:
    supplied = Path(value).expanduser().absolute()
    if _is_symbolic_path(supplied) or not supplied.is_dir():
        raise ConfigurationError(
            f"SBOM output must be an existing real directory: {supplied}"
        )
    resolved = supplied.resolve()
    try:
        resolved.relative_to(bundle)
    except ValueError:
        pass
    else:
        raise ConfigurationError("SBOM must be written outside the frozen bundle")
    return resolved


def create_desktop_cyclonedx_sbom(
    bundle_directory: Path | str,
    dependency_evidence_path: Path | str,
    *,
    expected_freeze_evidence_sha256: str,
    expected_dependency_evidence_sha256: str,
    output_directory: Path | str,
) -> Path:
    """Create a deterministic, exact, non-overwriting CycloneDX 1.7 SBOM."""

    supplied_bundle = Path(bundle_directory).expanduser().absolute()
    if _is_symbolic_path(supplied_bundle):
        raise DesktopSbomError("Frozen bundle root must not be symbolic")
    bundle = supplied_bundle.resolve()
    verify_desktop_freeze_evidence(bundle)
    freeze_path = bundle / FREEZE_EVIDENCE_NAME
    freeze, dependencies, freeze_sha256, dependency_sha256 = _source_documents(
        freeze_path,
        dependency_evidence_path,
        expected_freeze_evidence_sha256=expected_freeze_evidence_sha256,
        expected_dependency_evidence_sha256=expected_dependency_evidence_sha256,
    )
    document = _bom_document(
        freeze,
        dependencies,
        freeze_sha256=freeze_sha256,
        dependency_sha256=dependency_sha256,
    )
    payload = _json_bytes(document)
    _validate_cyclonedx(payload)
    destination = _output_directory(output_directory, bundle=bundle)
    sbom_path = destination / SBOM_NAME
    sidecar_path = destination / SIDECAR_NAME
    if sbom_path.exists() or _is_symbolic_path(sbom_path):
        raise ConfigurationError(
            f"CycloneDX SBOM already exists and will not be overwritten: {sbom_path}"
        )
    if sidecar_path.exists() or _is_symbolic_path(sidecar_path):
        raise ConfigurationError(
            f"CycloneDX SBOM sidecar already exists and will not be overwritten: "
            f"{sidecar_path}"
        )
    written: list[Path] = []
    try:
        written.append(
            write_new_exact_file(
                payload,
                sbom_path,
                artifact_label="CycloneDX SBOM",
            )
        )
        written.append(
            write_new_exact_file(
                f"{_sha256_bytes(payload)}  {SBOM_NAME}\n".encode("ascii"),
                sidecar_path,
                artifact_label="CycloneDX SBOM sidecar",
            )
        )
        verify_desktop_cyclonedx_sbom(
            sbom_path,
            freeze_evidence_path=freeze_path,
            dependency_evidence_path=dependency_evidence_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
        )
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise
    return sbom_path


def verify_desktop_cyclonedx_sbom(
    sbom_path: Path | str,
    *,
    freeze_evidence_path: Path | str,
    dependency_evidence_path: Path | str,
    expected_freeze_evidence_sha256: str,
    expected_dependency_evidence_sha256: str,
    expected_sbom_sha256: str | None = None,
) -> dict:
    """Verify exact source bindings, deterministic mapping, sidecar, and schema."""

    freeze, dependencies, freeze_sha256, dependency_sha256 = _source_documents(
        freeze_evidence_path,
        dependency_evidence_path,
        expected_freeze_evidence_sha256=expected_freeze_evidence_sha256,
        expected_dependency_evidence_sha256=expected_dependency_evidence_sha256,
    )
    path = Path(sbom_path).expanduser().absolute()
    if path.name != SBOM_NAME:
        raise DesktopSbomError(f"CycloneDX SBOM must be named {SBOM_NAME}")
    sidecar_path = path.with_name(SIDECAR_NAME)
    if (
        _is_symbolic_path(path)
        or _is_symbolic_path(sidecar_path)
        or not path.is_file()
        or not sidecar_path.is_file()
    ):
        raise DesktopSbomError("CycloneDX SBOM or sidecar is missing")
    try:
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8"))
        sidecar = sidecar_path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopSbomError("CycloneDX SBOM is not readable") from error
    observed_sha256 = _sha256_bytes(payload)
    if expected_sbom_sha256 is not None and observed_sha256 != _expected_sha256(
        expected_sbom_sha256, label="SBOM"
    ):
        raise DesktopSbomError("CycloneDX SBOM differs from the externally expected SHA-256")
    if sidecar != f"{observed_sha256}  {SBOM_NAME}\n".encode("ascii"):
        raise DesktopSbomError("CycloneDX SBOM sidecar is malformed")
    if payload != _json_bytes(document):
        raise DesktopSbomError("CycloneDX SBOM is not canonical JSON")
    _validate_cyclonedx(payload)
    expected = _bom_document(
        freeze,
        dependencies,
        freeze_sha256=freeze_sha256,
        dependency_sha256=dependency_sha256,
    )
    if document != expected or payload != _json_bytes(expected):
        raise DesktopSbomError(
            "CycloneDX SBOM differs from the deterministic source-evidence mapping"
        )
    return document

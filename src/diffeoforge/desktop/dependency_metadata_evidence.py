"""Inventory installed distribution metadata without making license decisions."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.freeze_evidence import (
    MANIFEST_NAME as FREEZE_MANIFEST_NAME,
)
from diffeoforge.desktop.freeze_evidence import verify_desktop_freeze_evidence
from diffeoforge.exact_file import write_new_exact_file

SCHEMA_VERSION = "0.1"
STATUS = "distribution_metadata_inventory_not_license_or_redistribution_approval"
TARGET = "windows-x86_64-cpu"
EVIDENCE_NAME = "freeze-dependency-metadata.json"
SIDECAR_NAME = "freeze-dependency-metadata.sha256"
SCIENTIFIC_BOUNDARY = (
    "This evidence records installed Python distribution metadata and exact hashes of "
    "locally discoverable license-related files for one hash-bound Windows freeze. "
    "Metadata fields can be absent, legacy, ambiguous, or scoped only to one distribution "
    "archive. This is not a license inventory, compatibility review, redistribution "
    "approval, SBOM, installer result, numerical validation, or scientific validation."
)
MISSING_RELEASE_GATES = (
    "license_compatibility_review",
    "license_inventory",
    "redistribution_approval",
    "sbom",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_LICENSE_BASENAME_PREFIXES = (
    "authors",
    "copying",
    "copyright",
    "license",
    "notice",
)


class DesktopDependencyMetadataEvidenceError(RuntimeError):
    """Raised when dependency metadata evidence fails closed."""


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath(
        f"desktop-dependency-metadata-evidence-v{SCHEMA_VERSION}.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: object) -> None:
    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise DesktopDependencyMetadataEvidenceError(
            f"Dependency metadata evidence schema violation at {location}: {first.message}"
        )


def _normalized_name(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise DesktopDependencyMetadataEvidenceError(
            "Distribution names must be nonempty strings"
        )
    normalized = re.sub(r"[-_.]+", "-", value).lower()
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) is None:
        raise DesktopDependencyMetadataEvidenceError(
            f"Distribution name cannot be normalized safely: {value!r}"
        )
    return normalized


def _expected_sha256(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected freeze evidence SHA-256 must be a string")
    normalized = value.lower()
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        raise ValueError(
            "Expected freeze evidence SHA-256 must contain 64 hexadecimal characters"
        )
    return normalized


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: dict) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _safe_distribution_path(value: object) -> str:
    path = str(value).replace("\\", "/")
    relative = PurePosixPath(path)
    if (
        not path
        or relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or (relative.parts and ":" in relative.parts[0])
    ):
        raise DesktopDependencyMetadataEvidenceError(
            f"Unsafe installed distribution path: {path!r}"
        )
    return relative.as_posix()


def _read_installed_file(package_path: object, relative: str) -> bytes:
    try:
        located = Path(package_path.locate()).absolute()  # type: ignore[attr-defined]
    except (AttributeError, NotImplementedError, OSError, TypeError) as error:
        raise DesktopDependencyMetadataEvidenceError(
            f"Could not locate installed distribution file: {relative}"
        ) from error
    if located.is_symlink() or not located.is_file():
        raise DesktopDependencyMetadataEvidenceError(
            f"Installed distribution file is missing or symbolic: {relative}"
        )
    try:
        return located.read_bytes()
    except OSError as error:
        raise DesktopDependencyMetadataEvidenceError(
            f"Could not read installed distribution file: {relative}"
        ) from error


def _metadata_values(metadata: object, field: str) -> list[str]:
    try:
        values = metadata.get_all(field)  # type: ignore[attr-defined]
    except AttributeError as error:
        raise DesktopDependencyMetadataEvidenceError(
            "Installed distribution metadata does not provide get_all()"
        ) from error
    if values is None:
        return []
    return [value for value in values if isinstance(value, str) and value]


def _metadata_value(metadata: object, field: str) -> str | None:
    try:
        value = metadata.get(field)  # type: ignore[attr-defined]
    except AttributeError as error:
        raise DesktopDependencyMetadataEvidenceError(
            "Installed distribution metadata does not provide get()"
        ) from error
    return value if isinstance(value, str) and value else None


def _declared_match(relative: str, declared: str) -> bool:
    normalized = declared.replace("\\", "/").strip("/").lower()
    if not normalized or ".." in PurePosixPath(normalized).parts:
        return False
    observed = relative.lower()
    return observed.endswith(f"/{normalized}") or observed.endswith(
        f"/licenses/{normalized}"
    )


def _is_license_candidate(relative: str) -> bool:
    path = PurePosixPath(relative)
    lowered_parts = tuple(part.lower() for part in path.parts)
    in_dist_info = any(part.endswith(".dist-info") for part in lowered_parts)
    if not in_dist_info:
        return False
    if "licenses" in lowered_parts:
        return True
    basename = path.name.lower()
    return any(basename.startswith(prefix) for prefix in _LICENSE_BASENAME_PREFIXES)


def _indexed_relevant_distribution_files(distribution_files: object) -> list[tuple[str, object]]:
    indexed = []
    for item in distribution_files:  # type: ignore[union-attr]
        raw = str(item).replace("\\", "/")
        try:
            relative = _safe_distribution_path(item)
        except DesktopDependencyMetadataEvidenceError:
            lowered = raw.lower()
            basename = PurePosixPath(lowered).name
            license_like = "/licenses/" in lowered or any(
                basename.startswith(prefix) for prefix in _LICENSE_BASENAME_PREFIXES
            )
            if lowered.endswith(".dist-info/metadata") or license_like:
                raise
            continue
        if relative.endswith(".dist-info/METADATA") or _is_license_candidate(relative):
            indexed.append((relative, item))
    return sorted(indexed, key=lambda pair: pair[0])


def _package_record(name: str, expected_version: str) -> dict:
    normalized = _normalized_name(name)
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError as error:
        raise DesktopDependencyMetadataEvidenceError(
            f"Freeze environment is missing distribution metadata: {name}"
        ) from error
    observed_name = _metadata_value(distribution.metadata, "Name")
    observed_version = distribution.version
    if observed_name is None or _normalized_name(observed_name) != normalized:
        raise DesktopDependencyMetadataEvidenceError(
            f"Installed distribution name differs for {name!r}: {observed_name!r}"
        )
    if observed_version != expected_version:
        raise DesktopDependencyMetadataEvidenceError(
            f"Installed distribution version differs for {normalized}: "
            f"expected {expected_version!r}, observed {observed_version!r}"
        )
    distribution_files = distribution.files
    if distribution_files is None:
        raise DesktopDependencyMetadataEvidenceError(
            f"Installed distribution file records are unavailable: {normalized}"
        )
    indexed = _indexed_relevant_distribution_files(distribution_files)
    metadata_candidates = [
        (relative, item)
        for relative, item in indexed
        if len(PurePosixPath(relative).parts) == 2
        and PurePosixPath(relative).parts[0].endswith(".dist-info")
        and PurePosixPath(relative).name == "METADATA"
    ]
    if len(metadata_candidates) != 1:
        raise DesktopDependencyMetadataEvidenceError(
            f"Expected exactly one installed METADATA file for {normalized}, "
            f"observed {len(metadata_candidates)}"
        )
    metadata_relative, metadata_path = metadata_candidates[0]
    metadata_root = PurePosixPath(metadata_relative).parts[0]
    metadata_bytes = _read_installed_file(metadata_path, metadata_relative)
    declared = sorted(set(_metadata_values(distribution.metadata, "License-File")))
    license_expression = _metadata_value(distribution.metadata, "License-Expression")
    license_field = _metadata_value(distribution.metadata, "License")
    classifiers = sorted(
        {
            value
            for value in _metadata_values(distribution.metadata, "Classifier")
            if value.startswith("License ::")
        }
    )
    requires_dist = sorted(_metadata_values(distribution.metadata, "Requires-Dist"))
    license_files = []
    matched_declared: set[str] = set()
    for relative, item in indexed:
        if PurePosixPath(relative).parts[0] != metadata_root:
            continue
        matching = [value for value in declared if _declared_match(relative, value)]
        if not matching and not _is_license_candidate(relative):
            continue
        payload = _read_installed_file(item, relative)
        matched_declared.update(matching)
        license_files.append(
            {
                "path": relative,
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
                "source": "declared" if matching else "discovered",
            }
        )
    unresolved = sorted(set(declared) - matched_declared)
    observations = []
    if license_expression is None:
        observations.append("license_expression_absent")
    if not declared:
        observations.append("declared_license_files_absent")
    if license_field is not None:
        observations.append("legacy_license_field_present")
    if license_expression is not None and license_field is not None:
        observations.append("license_and_expression_both_present")
    if classifiers:
        observations.append("license_classifiers_present")
    if unresolved:
        observations.append("declared_license_file_not_installed")
    if not license_files:
        observations.append("license_file_candidates_absent")
    metadata_version = _metadata_value(distribution.metadata, "Metadata-Version")
    if metadata_version is None:
        raise DesktopDependencyMetadataEvidenceError(
            f"Installed distribution has no Metadata-Version: {normalized}"
        )
    return {
        "name": normalized,
        "version": expected_version,
        "metadata": {
            "metadata_version": metadata_version,
            "name": observed_name,
            "version": observed_version,
            "bytes": len(metadata_bytes),
            "sha256": _sha256_bytes(metadata_bytes),
            "license_expression": license_expression,
            "license_field": license_field,
            "license_classifiers": classifiers,
            "license_files_declared": declared,
            "requires_dist": requires_dist,
        },
        "license_files": license_files,
        "unresolved_declared_license_files": unresolved,
        "observations": sorted(observations),
        "review_status": "unreviewed",
    }


def _package_set_sha256(packages: list[dict]) -> str:
    payload = json.dumps(
        packages,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _output_directory(value: Path | str, *, bundle: Path) -> Path:
    supplied = Path(value).expanduser().absolute()
    if supplied.is_symlink() or not supplied.is_dir():
        raise ConfigurationError(
            f"Dependency metadata evidence output must be an existing real directory: {supplied}"
        )
    resolved = supplied.resolve()
    try:
        resolved.relative_to(bundle)
    except ValueError:
        pass
    else:
        raise ConfigurationError(
            "Dependency metadata evidence must be written outside the frozen bundle"
        )
    return resolved


def create_desktop_dependency_metadata_evidence(
    bundle_directory: Path | str,
    *,
    expected_freeze_evidence_sha256: str,
    output_directory: Path | str,
) -> Path:
    """Create exact non-overwriting metadata evidence for one verified freeze."""

    expected = _expected_sha256(expected_freeze_evidence_sha256)
    bundle = Path(bundle_directory).expanduser().absolute().resolve()
    manifest = verify_desktop_freeze_evidence(bundle)
    if manifest["schema_version"] != "0.3":
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence requires desktop freeze schema_version 0.3"
        )
    manifest_path = bundle / FREEZE_MANIFEST_NAME
    manifest_sha256 = _sha256_bytes(manifest_path.read_bytes())
    if manifest_sha256 != expected:
        raise DesktopDependencyMetadataEvidenceError(
            "Desktop freeze evidence differs from the externally expected SHA-256"
        )
    runtime_packages = manifest["runtime_packages"]
    if not isinstance(runtime_packages, Mapping):
        raise DesktopDependencyMetadataEvidenceError(
            "Desktop freeze runtime_packages must be an object"
        )
    normalized_names: set[str] = set()
    packages = []
    for name, version in runtime_packages.items():
        normalized = _normalized_name(name)
        if normalized in normalized_names:
            raise DesktopDependencyMetadataEvidenceError(
                f"Desktop freeze runtime_packages normalize to a duplicate: {normalized}"
            )
        normalized_names.add(normalized)
        packages.append(_package_record(name, version))
    packages.sort(key=lambda package: package["name"])
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "target": TARGET,
        "source": {
            "freeze_evidence_schema_version": manifest["schema_version"],
            "freeze_evidence_sha256": manifest_sha256,
            "source_commit_sha": manifest["source"]["commit_sha"],
            "bundle_inventory_sha256": manifest["bundle"]["inventory_sha256"],
        },
        "generator": {
            "diffeoforge": manifest["runtime_packages"]["diffeoforge"],
            "python": platform.python_version(),
        },
        "package_count": len(packages),
        "package_set_sha256": _package_set_sha256(packages),
        "packages": packages,
        "review_boundary": {
            "license_compatibility": "not_reviewed",
            "redistribution": "not_reviewed",
            "sbom": "not_an_sbom",
        },
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _validate_schema(evidence)
    destination = _output_directory(output_directory, bundle=bundle)
    evidence_path = destination / EVIDENCE_NAME
    sidecar_path = destination / SIDECAR_NAME
    if evidence_path.exists() or evidence_path.is_symlink():
        raise ConfigurationError(
            f"Dependency metadata evidence already exists and will not be overwritten: "
            f"{evidence_path}"
        )
    if sidecar_path.exists() or sidecar_path.is_symlink():
        raise ConfigurationError(
            f"Dependency metadata evidence sidecar already exists and will not be overwritten: "
            f"{sidecar_path}"
        )
    payload = _json_bytes(evidence)
    written: list[Path] = []
    try:
        written.append(
            write_new_exact_file(
                payload,
                evidence_path,
                artifact_label="Dependency metadata evidence",
            )
        )
        sidecar = f"{_sha256_bytes(payload)}  {EVIDENCE_NAME}\n".encode("ascii")
        written.append(
            write_new_exact_file(
                sidecar,
                sidecar_path,
                artifact_label="Dependency metadata evidence sidecar",
            )
        )
        verify_desktop_dependency_metadata_evidence(
            evidence_path,
            expected_freeze_evidence_sha256=expected,
        )
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise
    return evidence_path


def verify_desktop_dependency_metadata_evidence(
    evidence_path: Path | str,
    *,
    expected_freeze_evidence_sha256: str,
) -> dict:
    """Verify schema, exact sidecar, package order, aggregate hash, and source hash."""

    expected = _expected_sha256(expected_freeze_evidence_sha256)
    path = Path(evidence_path).expanduser().absolute()
    if path.name != EVIDENCE_NAME:
        raise DesktopDependencyMetadataEvidenceError(
            f"Dependency metadata evidence must be named {EVIDENCE_NAME}"
        )
    sidecar_path = path.with_name(SIDECAR_NAME)
    if (
        path.is_symlink()
        or sidecar_path.is_symlink()
        or not path.is_file()
        or not sidecar_path.is_file()
    ):
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence or sidecar is missing"
        )
    try:
        payload = path.read_bytes()
        evidence = json.loads(payload.decode("utf-8"))
        sidecar = sidecar_path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence is not readable"
        ) from error
    _validate_schema(evidence)
    evidence_sha256 = _sha256_bytes(payload)
    expected_sidecar = f"{evidence_sha256}  {EVIDENCE_NAME}\n".encode("ascii")
    if sidecar != expected_sidecar:
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence sidecar is malformed"
        )
    if payload != _json_bytes(evidence):
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence is not canonical JSON"
        )
    if evidence["source"]["freeze_evidence_sha256"] != expected:
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence source differs from the externally expected SHA-256"
        )
    packages = evidence["packages"]
    names = [package["name"] for package in packages]
    if names != sorted(names) or len(names) != len(set(names)):
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence package names are not unique and sorted"
        )
    if evidence["package_count"] != len(packages):
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence package count differs"
        )
    if evidence["package_set_sha256"] != _package_set_sha256(packages):
        raise DesktopDependencyMetadataEvidenceError(
            "Dependency metadata evidence package-set SHA-256 differs"
        )
    for package in packages:
        metadata = package["metadata"]
        if _normalized_name(metadata["name"]) != package["name"]:
            raise DesktopDependencyMetadataEvidenceError(
                f"Dependency metadata name differs for {package['name']}"
            )
        if metadata["version"] != package["version"]:
            raise DesktopDependencyMetadataEvidenceError(
                f"Dependency metadata version differs for {package['name']}"
            )
        ordered_fields = (
            "license_classifiers",
            "license_files_declared",
            "requires_dist",
        )
        for field in ordered_fields:
            if metadata[field] != sorted(metadata[field]):
                raise DesktopDependencyMetadataEvidenceError(
                    f"Dependency metadata field is not sorted: {package['name']}.{field}"
                )
        license_paths = [record["path"] for record in package["license_files"]]
        if license_paths != sorted(license_paths) or len(license_paths) != len(
            set(license_paths)
        ):
            raise DesktopDependencyMetadataEvidenceError(
                f"Dependency metadata license-file paths differ for {package['name']}"
            )
        for field in ("unresolved_declared_license_files", "observations"):
            values = package[field]
            if values != sorted(values):
                raise DesktopDependencyMetadataEvidenceError(
                    f"Dependency metadata field is not sorted: {package['name']}.{field}"
                )
    return evidence

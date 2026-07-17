"""Create and verify exact inventories for Windows desktop freeze evidence."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "0.1"
STATUS = "engineering_evidence_not_a_release"
TARGET = "windows-x86_64-cpu"
MANIFEST_NAME = "freeze-evidence.json"
SIDECAR_NAME = "freeze-evidence.sha256"
DESKTOP_EXECUTABLE = "DiffeoForge.exe"
WORKER_EXECUTABLE = "DiffeoForgeWorker.exe"
SCIENTIFIC_BOUNDARY = (
    "This exact-file inventory is engineering evidence for one Windows CPU freeze. "
    "It is not an installer, signature, SBOM, license approval, clean-machine result, "
    "Deformetrica-equivalence result, biological validation, GPU result, or evidence of "
    "production suitability for cohorts of 300 or more specimens."
)
MISSING_RELEASE_GATES = (
    "authenticode_signature",
    "clean_windows_vm",
    "cpu_numerical_release_validation",
    "crash_reconciliation",
    "installer_and_uninstaller",
    "license_inventory",
    "no_network_observation",
    "sbom",
    "windows_defender_scan",
)
_PACKAGE_DISTRIBUTIONS = (
    "altgraph",
    "attrs",
    "diffeoforge",
    "filelock",
    "fsspec",
    "jinja2",
    "jsonschema",
    "jsonschema-specifications",
    "markupsafe",
    "mpmath",
    "networkx",
    "numpy",
    "packaging",
    "pefile",
    "psutil",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "pyside6-essentials",
    "pywin32-ctypes",
    "pyyaml",
    "referencing",
    "rpds-py",
    "setuptools",
    "shiboken6",
    "sympy",
    "torch",
    "typing-extensions",
)
_EVIDENCE_FILES = frozenset((MANIFEST_NAME, SIDECAR_NAME))


class DesktopFreezeEvidenceError(RuntimeError):
    """Raised when a frozen desktop bundle or its evidence fails closed."""


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath("desktop-freeze-evidence-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: object) -> None:
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise DesktopFreezeEvidenceError(
            f"Desktop freeze evidence schema violation at {location}: {first.message}"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_root(directory: Path | str) -> Path:
    supplied = Path(directory).expanduser().absolute()
    if supplied.is_symlink():
        raise DesktopFreezeEvidenceError("Desktop bundle root must not be a symbolic link")
    root = supplied.resolve()
    if not root.is_dir():
        raise DesktopFreezeEvidenceError(f"Desktop bundle directory does not exist: {root}")
    return root


def _inventory(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise DesktopFreezeEvidenceError(f"Desktop bundle contains a symbolic link: {relative}")
        if not path.is_file() or relative in _EVIDENCE_FILES:
            continue
        records.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    if not records:
        raise DesktopFreezeEvidenceError("Desktop bundle contains no inventoried files")
    return records


def _inventory_sha256(records: list[dict[str, object]]) -> str:
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_commit(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("source_commit must be a lowercase 40-character Git SHA")
    return value


def _validate_created_at(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("created_at must be a nonempty timezone-aware ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("created_at must be valid ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must include a timezone")
    return value


def _default_package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in _PACKAGE_DISTRIBUTIONS:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise DesktopFreezeEvidenceError(
                f"Freeze environment is missing required distribution metadata: {name}"
            ) from error
    return versions


def _package_versions(value: Mapping[str, str] | None) -> dict[str, str]:
    supplied = _default_package_versions() if value is None else dict(value)
    if not supplied or any(
        not isinstance(name, str) or not name or not isinstance(version, str) or not version
        for name, version in supplied.items()
    ):
        raise ValueError("package_versions must map nonempty names to nonempty versions")
    required = {
        "diffeoforge",
        "numpy",
        "psutil",
        "pyinstaller",
        "pyside6-essentials",
        "shiboken6",
        "torch",
    }
    missing = sorted(required - supplied.keys())
    if missing:
        raise DesktopFreezeEvidenceError(
            f"Freeze environment package versions are incomplete: {missing}"
        )
    return dict(sorted(supplied.items()))


def _require_entry_points(root: Path) -> None:
    for name in (DESKTOP_EXECUTABLE, WORKER_EXECUTABLE):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise DesktopFreezeEvidenceError(
                f"Desktop freeze entry point is missing or symbolic: {name}"
            )


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def create_desktop_freeze_evidence(
    directory: Path | str,
    *,
    source_commit: str,
    created_at: str | None = None,
    package_versions: Mapping[str, str] | None = None,
    python_version: str | None = None,
    platform_description: str | None = None,
) -> Path:
    """Create non-overwriting exact-file evidence for one Windows one-dir bundle."""

    root = _bundle_root(directory)
    manifest_path = root / MANIFEST_NAME
    sidecar_path = root / SIDECAR_NAME
    if manifest_path.exists() or sidecar_path.exists():
        raise FileExistsError("Desktop freeze evidence already exists and will not be replaced")
    commit = _validate_commit(source_commit)
    timestamp = _validate_created_at(
        created_at
        if created_at is not None
        else datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    observed_platform = (
        platform.platform() if platform_description is None else platform_description
    )
    if not isinstance(observed_platform, str) or not observed_platform.startswith("Windows-"):
        raise DesktopFreezeEvidenceError(
            "Desktop freeze evidence creation is restricted to an observed Windows host"
        )
    observed_python = platform.python_version() if python_version is None else python_version
    if not isinstance(observed_python, str) or not observed_python:
        raise ValueError("python_version must be a nonempty string")
    versions = _package_versions(package_versions)
    _require_entry_points(root)
    records = _inventory(root)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "created_at": timestamp,
        "target": TARGET,
        "source": {"commit_sha": commit, "dirty_worktree_allowed": False},
        "builder": {
            "name": "PyInstaller",
            "version": versions["pyinstaller"],
            "mode": "onedir",
            "python": observed_python,
            "platform": observed_platform,
        },
        "runtime_packages": versions,
        "entry_points": {
            "desktop": DESKTOP_EXECUTABLE,
            "worker": WORKER_EXECUTABLE,
        },
        "bundle": {
            "directory_name": root.name,
            "file_count": len(records),
            "total_bytes": sum(int(record["bytes"]) for record in records),
            "inventory_sha256": _inventory_sha256(records),
            "files": records,
        },
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _validate_schema(manifest)
    manifest_bytes = _json_bytes(manifest)
    try:
        with manifest_path.open("xb") as handle:
            handle.write(manifest_bytes)
        with sidecar_path.open("x", encoding="ascii", newline="\n") as handle:
            handle.write(f"{hashlib.sha256(manifest_bytes).hexdigest()}  {MANIFEST_NAME}\n")
    except Exception:
        manifest_path.unlink(missing_ok=True)
        sidecar_path.unlink(missing_ok=True)
        raise
    verify_desktop_freeze_evidence(root)
    return manifest_path


def _safe_inventory_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DesktopFreezeEvidenceError("Inventory paths must be nonempty POSIX paths")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or (relative.parts and ":" in relative.parts[0])
    ):
        raise DesktopFreezeEvidenceError(f"Unsafe desktop inventory path: {value!r}")
    path = root.joinpath(*relative.parts)
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except ValueError as error:
        raise DesktopFreezeEvidenceError("Desktop inventory path escapes the bundle") from error
    if path.is_symlink() or not path.is_file():
        raise DesktopFreezeEvidenceError(f"Desktop inventory file is missing or symbolic: {value}")
    return resolved


def verify_desktop_freeze_evidence(directory: Path | str) -> dict:
    """Verify schema, sidecar, entry points, exact inventory, sizes, and hashes."""

    root = _bundle_root(directory)
    manifest_path = root / MANIFEST_NAME
    sidecar_path = root / SIDECAR_NAME
    if (
        manifest_path.is_symlink()
        or sidecar_path.is_symlink()
        or not manifest_path.is_file()
        or not sidecar_path.is_file()
    ):
        raise DesktopFreezeEvidenceError("Desktop freeze evidence or sidecar is missing")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        sidecar = sidecar_path.read_text(encoding="ascii").strip().split()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopFreezeEvidenceError("Desktop freeze evidence is not readable") from error
    _validate_schema(manifest)
    if len(sidecar) != 2 or sidecar[1] != MANIFEST_NAME:
        raise DesktopFreezeEvidenceError("Desktop freeze evidence sidecar is malformed")
    if sidecar[0] != hashlib.sha256(manifest_bytes).hexdigest():
        raise DesktopFreezeEvidenceError("Desktop freeze evidence SHA-256 differs")
    _validate_created_at(manifest["created_at"])
    if manifest["bundle"]["directory_name"] != root.name:
        raise DesktopFreezeEvidenceError("Desktop bundle directory name differs from evidence")
    _require_entry_points(root)

    records = manifest["bundle"]["files"]
    paths = [record["path"] for record in records]
    if len(paths) != len(set(paths)):
        raise DesktopFreezeEvidenceError("Desktop freeze inventory contains duplicate paths")
    if paths != sorted(paths):
        raise DesktopFreezeEvidenceError("Desktop freeze inventory paths are not sorted")
    expected_files = set(paths)
    observed_records = _inventory(root)
    observed_files = {record["path"] for record in observed_records}
    if observed_files != expected_files:
        missing = sorted(expected_files - observed_files)
        extra = sorted(observed_files - expected_files)
        raise DesktopFreezeEvidenceError(
            f"Desktop freeze file inventory differs: missing={missing}, extra={extra}"
        )
    for record in records:
        path = _safe_inventory_path(root, record["path"])
        if path.stat().st_size != record["bytes"]:
            raise DesktopFreezeEvidenceError(f"Desktop freeze file size differs: {record['path']}")
        if _sha256_file(path) != record["sha256"]:
            raise DesktopFreezeEvidenceError(
                f"Desktop freeze file SHA-256 differs: {record['path']}"
            )
    if manifest["bundle"]["file_count"] != len(records):
        raise DesktopFreezeEvidenceError("Desktop freeze file count differs")
    if manifest["bundle"]["total_bytes"] != sum(int(record["bytes"]) for record in records):
        raise DesktopFreezeEvidenceError("Desktop freeze total byte count differs")
    if manifest["bundle"]["inventory_sha256"] != _inventory_sha256(records):
        raise DesktopFreezeEvidenceError("Desktop freeze inventory SHA-256 differs")
    if set(manifest["entry_points"].values()) - expected_files:
        raise DesktopFreezeEvidenceError("Desktop freeze entry point is not inventoried")
    return manifest

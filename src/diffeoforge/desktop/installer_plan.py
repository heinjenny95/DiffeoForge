"""Create and verify deterministic, non-executing Windows installer build plans."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator

from diffeoforge.desktop.dependency_metadata_evidence import (
    EVIDENCE_NAME as DEPENDENCY_EVIDENCE_NAME,
)
from diffeoforge.desktop.dependency_metadata_evidence import (
    SIDECAR_NAME as DEPENDENCY_SIDECAR_NAME,
)
from diffeoforge.desktop.freeze_evidence import (
    MANIFEST_NAME as FREEZE_EVIDENCE_NAME,
)
from diffeoforge.desktop.freeze_evidence import (
    SIDECAR_NAME as FREEZE_SIDECAR_NAME,
)
from diffeoforge.desktop.freeze_evidence import verify_desktop_freeze_evidence
from diffeoforge.desktop.sbom import SBOM_NAME, verify_desktop_cyclonedx_sbom
from diffeoforge.desktop.sbom import SIDECAR_NAME as SBOM_SIDECAR_NAME
from diffeoforge.exact_file import write_new_exact_file

SCHEMA_VERSION = "0.1"
STATUS = "installer_build_plan_not_an_installer_or_release_artifact"
TARGET = "windows-x86_64-cpu"
PLAN_NAME = "installer-build-plan.json"
SIDECAR_NAME = "installer-build-plan.sha256"
SCRIPT_NAME = "DiffeoForge.iss"
CONTRACT_NAME = "installer-contract-v0.1.json"
TOOLCHAIN_NAME = "Inno Setup"
TOOLCHAIN_VERSION = "7.0.2"
TOOLCHAIN_EDITION = "x64"
TOOLCHAIN_RELEASE_REPOSITORY = "jrsoftware/issrc"
TOOLCHAIN_RELEASE_TAG = "is-7_0_2"
TOOLCHAIN_ASSET = "innosetup-7.0.2-x64.exe"
TOOLCHAIN_ASSET_BYTES = 17_020_192
TOOLCHAIN_ASSET_SHA256 = "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1"
COMPILER = "ISCC.exe"
SCIENTIFIC_BOUNDARY = (
    "This deterministic document is a non-executing plan for one Windows CPU "
    "installer build. It is not an installer, a toolchain authenticity observation, "
    "license or redistribution approval, a signature, clean-machine result, security "
    "result, numerical validation, scientific validation, or evidence of production "
    "suitability."
)
MISSING_RELEASE_GATES = (
    "authenticode_signature",
    "clean_windows_vm",
    "cpu_numerical_release_validation",
    "crash_and_power_loss_reconciliation",
    "human_license_inventory",
    "installer_execution",
    "installer_install_uninstall_observation",
    "license_compatibility_review",
    "no_network_observation",
    "project_preservation_observation",
    "redistribution_approval",
    "scientific_validation",
    "toolchain_authenticity_observation",
    "windows_defender_scan",
)
EXPECTED_EVIDENCE_NAMES = frozenset(
    (
        FREEZE_EVIDENCE_NAME,
        FREEZE_SIDECAR_NAME,
        DEPENDENCY_EVIDENCE_NAME,
        DEPENDENCY_SIDECAR_NAME,
        SBOM_NAME,
        SBOM_SIDECAR_NAME,
    )
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_SAFE_OUTPUT_PART_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


class DesktopInstallerPlanError(RuntimeError):
    """Raised when an installer build plan or one of its exact inputs is unsafe."""


def _is_symbolic_path(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction is not None and is_junction())


def _reject_symbolic_chain(path: Path, *, label: str) -> None:
    current = path
    while True:
        if current.exists() and _is_symbolic_path(current):
            raise DesktopInstallerPlanError(f"{label} must not use a symbolic path: {current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _real_directory(value: Path | str, *, label: str) -> Path:
    supplied = Path(value).expanduser().absolute()
    _reject_symbolic_chain(supplied, label=label)
    resolved = supplied.resolve()
    if not resolved.is_dir():
        raise DesktopInstallerPlanError(f"{label} must be an existing real directory: {resolved}")
    return resolved


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
        raise DesktopInstallerPlanError(f"{label} must be an existing real file: {resolved}")
    if expected_name is not None and resolved.name != expected_name:
        raise DesktopInstallerPlanError(f"{label} must be named {expected_name}")
    return resolved


def _is_within(candidate: Path, root: Path) -> bool:
    return candidate == root or root in candidate.parents


def _expected_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Expected {label} SHA-256 must be a string")
    normalized = value.lower()
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"Expected {label} SHA-256 must contain 64 hexadecimal characters")
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _schema() -> dict:
    resource = files("diffeoforge.schema").joinpath("desktop-installer-build-plan-v0.1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_schema(value: object) -> None:
    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise DesktopInstallerPlanError(
            f"Installer build plan schema violation at {location}: {first.message}"
        )


def _file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _project_version(project_file: Path) -> str:
    try:
        document = tomllib.loads(project_file.read_text(encoding="utf-8"))
        project = document["project"]
        name = project["name"]
        version = project["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise DesktopInstallerPlanError("Could not read exact project name and version") from error
    if name != "diffeoforge" or not isinstance(version, str) or not version:
        raise DesktopInstallerPlanError(
            "Project metadata must identify a nonempty DiffeoForge version"
        )
    return version


def _development_version(version: str) -> bool:
    return bool(re.search(r"(?:^|[._-])dev\d*(?:$|[.+_-])", version, re.IGNORECASE))


def _output_version(version: str) -> str:
    rendered = re.sub(r"[^A-Za-z0-9._-]+", "_", version).strip("._-")
    if not rendered or _SAFE_OUTPUT_PART_PATTERN.fullmatch(rendered) is None:
        raise DesktopInstallerPlanError("Application version cannot form a safe setup filename")
    return rendered


def _safe_define(value: str, *, label: str) -> str:
    if not value or any(character in value for character in ('"', "\r", "\n", "\0")):
        raise DesktopInstallerPlanError(f"{label} cannot be represented as an ISCC define")
    return value


def _validate_contract(contract_path: Path) -> None:
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopInstallerPlanError("Installer contract is not readable JSON") from error
    toolchain = contract.get("toolchain")
    if contract.get("schema_version") != "0.1" or contract.get("target") != TARGET:
        raise DesktopInstallerPlanError("Installer contract version or target differs")
    expected = {
        "name": TOOLCHAIN_NAME,
        "version": TOOLCHAIN_VERSION,
        "edition": TOOLCHAIN_EDITION,
        "release_repository": TOOLCHAIN_RELEASE_REPOSITORY,
        "release_tag": TOOLCHAIN_RELEASE_TAG,
        "asset": TOOLCHAIN_ASSET,
        "asset_bytes": TOOLCHAIN_ASSET_BYTES,
        "asset_sha256": TOOLCHAIN_ASSET_SHA256,
        "compiler": COMPILER,
    }
    if not isinstance(toolchain, Mapping) or any(
        toolchain.get(key) != value for key, value in expected.items()
    ):
        raise DesktopInstallerPlanError("Installer contract toolchain identity differs")


def _validate_evidence_directory(path: Path) -> None:
    entries = list(path.iterdir())
    names = {entry.name for entry in entries}
    if len(entries) != 6 or names != EXPECTED_EVIDENCE_NAMES:
        raise DesktopInstallerPlanError(
            "Installer evidence directory must contain exactly the six approved files"
        )
    unsafe = [entry.name for entry in entries if _is_symbolic_path(entry) or not entry.is_file()]
    if unsafe:
        raise DesktopInstallerPlanError(
            f"Installer evidence directory contains an unsafe entry: {sorted(unsafe)[0]}"
        )


def _validate_output_directory(
    output: Path,
    *,
    input_roots: tuple[Path, ...],
    allowed_entries: frozenset[str],
) -> None:
    if any(_is_within(output, root) for root in input_roots):
        raise DesktopInstallerPlanError(
            "Installer output directory must be outside repository and evidence inputs"
        )
    observed = {entry.name for entry in output.iterdir()}
    if observed != allowed_entries:
        raise DesktopInstallerPlanError(
            "Installer output directory contains entries outside the expected plan boundary"
        )
    for entry in output.iterdir():
        if _is_symbolic_path(entry) or not entry.is_file():
            raise DesktopInstallerPlanError("Installer output boundary contains an unsafe entry")


def _compiler_arguments(
    *,
    version: str,
    source_commit: str,
    bundle: Path,
    evidence: Path,
    license_file: Path,
    output: Path,
    output_basename: str,
    script: Path,
) -> list[str]:
    values = {
        "AppVersion": version,
        "SourceCommit": source_commit,
        "BundleDir": str(bundle),
        "EvidenceDir": str(evidence),
        "LicenseFile": str(license_file),
        "OutputDir": str(output),
        "OutputBaseFilename": output_basename,
    }
    arguments = ["/Qp"]
    arguments.extend(
        f"/D{name}={_safe_define(value, label=name)}" for name, value in values.items()
    )
    arguments.append(str(script))
    return arguments


def _compose_plan(
    *,
    bundle_directory: Path | str,
    evidence_directory: Path | str,
    project_file: Path | str,
    output_directory: Path | str,
    expected_freeze_evidence_sha256: str,
    expected_dependency_evidence_sha256: str,
    expected_sbom_sha256: str,
    release_candidate: bool,
    allowed_output_entries: frozenset[str],
) -> dict[str, object]:
    bundle = _real_directory(bundle_directory, label="Frozen bundle")
    evidence = _real_directory(evidence_directory, label="Installer evidence")
    project_path = _real_file(
        project_file,
        label="Project file",
        expected_name="pyproject.toml",
    )
    repository = project_path.parent
    script = _real_file(
        repository / "distribution" / "windows" / SCRIPT_NAME,
        label="Installer script",
        expected_name=SCRIPT_NAME,
    )
    contract = _real_file(
        repository / "distribution" / "windows" / CONTRACT_NAME,
        label="Installer contract",
        expected_name=CONTRACT_NAME,
    )
    license_file = _real_file(
        repository / "LICENSE",
        label="Project license",
        expected_name="LICENSE",
    )
    output = _real_directory(output_directory, label="Installer output")
    if _is_within(evidence, bundle) or _is_within(bundle, evidence):
        raise DesktopInstallerPlanError("Frozen bundle and evidence directory must be separate")
    _validate_output_directory(
        output,
        input_roots=(repository, bundle, evidence),
        allowed_entries=allowed_output_entries,
    )
    _validate_evidence_directory(evidence)
    _validate_contract(contract)

    freeze_sha256 = _expected_sha256(expected_freeze_evidence_sha256, label="freeze evidence")
    dependency_sha256 = _expected_sha256(
        expected_dependency_evidence_sha256, label="dependency evidence"
    )
    sbom_sha256 = _expected_sha256(expected_sbom_sha256, label="SBOM")
    bundle_manifest = verify_desktop_freeze_evidence(bundle)
    bundle_freeze_path = bundle / FREEZE_EVIDENCE_NAME
    evidence_freeze_path = evidence / FREEZE_EVIDENCE_NAME
    if _sha256_file(bundle_freeze_path) != freeze_sha256:
        raise DesktopInstallerPlanError(
            "Frozen bundle manifest differs from the externally expected SHA-256"
        )
    if bundle_freeze_path.read_bytes() != evidence_freeze_path.read_bytes():
        raise DesktopInstallerPlanError(
            "Downloaded freeze evidence differs from the fully verified bundle manifest"
        )
    dependency_path = evidence / DEPENDENCY_EVIDENCE_NAME
    sbom_path = evidence / SBOM_NAME
    sbom = verify_desktop_cyclonedx_sbom(
        sbom_path,
        freeze_evidence_path=evidence_freeze_path,
        dependency_evidence_path=dependency_path,
        expected_freeze_evidence_sha256=freeze_sha256,
        expected_dependency_evidence_sha256=dependency_sha256,
        expected_sbom_sha256=sbom_sha256,
    )
    dependency = json.loads(dependency_path.read_text(encoding="utf-8"))
    source_commit = bundle_manifest["source"]["commit_sha"]
    if _COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise DesktopInstallerPlanError("Freeze source commit is invalid")
    version = _project_version(project_path)
    runtime_version = bundle_manifest["runtime_packages"].get("diffeoforge")
    if runtime_version != version:
        raise DesktopInstallerPlanError(
            "Project version differs from the fully verified frozen runtime"
        )
    development = _development_version(version)
    if release_candidate and (development or "+" in version):
        raise DesktopInstallerPlanError(
            "A development or local application version cannot be planned as a release candidate"
        )
    output_basename = f"DiffeoForge-{_output_version(version)}-Windows-CPU-x86_64-Setup"
    setup_filename = f"{output_basename}.exe"
    setup_path = output / setup_filename

    arguments = _compiler_arguments(
        version=version,
        source_commit=source_commit,
        bundle=bundle,
        evidence=evidence,
        license_file=license_file,
        output=output,
        output_basename=output_basename,
        script=script,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "target": TARGET,
        "source": {
            "commit_sha": source_commit,
            "application_version": version,
            "development_version": development,
            "release_candidate": release_candidate,
        },
        "toolchain": {
            "name": TOOLCHAIN_NAME,
            "version": TOOLCHAIN_VERSION,
            "edition": TOOLCHAIN_EDITION,
            "release_repository": TOOLCHAIN_RELEASE_REPOSITORY,
            "release_tag": TOOLCHAIN_RELEASE_TAG,
            "asset": TOOLCHAIN_ASSET,
            "asset_bytes": TOOLCHAIN_ASSET_BYTES,
            "asset_sha256": TOOLCHAIN_ASSET_SHA256,
            "compiler": COMPILER,
            "execution_authorized": False,
        },
        "inputs": {
            "bundle": {
                "directory": str(bundle),
                "freeze_evidence_sha256": freeze_sha256,
                "inventory_sha256": bundle_manifest["bundle"]["inventory_sha256"],
                "file_count": bundle_manifest["bundle"]["file_count"],
                "total_bytes": bundle_manifest["bundle"]["total_bytes"],
            },
            "evidence": {
                "directory": str(evidence),
                "exact_file_count": 6,
                "freeze_evidence_sha256": freeze_sha256,
                "dependency_evidence_sha256": dependency_sha256,
                "sbom_sha256": sbom_sha256,
                "package_set_sha256": dependency["package_set_sha256"],
                "sbom_serial_number": sbom["serialNumber"],
                "sbom_component_count": len(sbom["components"]),
                "sbom_composition": sbom["compositions"][0]["aggregate"],
            },
            "installer_script": _file_record(script),
            "installer_contract": _file_record(contract),
            "project": _file_record(project_path),
            "license": _file_record(license_file),
        },
        "output": {
            "directory": str(output),
            "setup_filename": setup_filename,
            "setup_path": str(setup_path),
            "plan_filename": PLAN_NAME,
            "sidecar_filename": SIDECAR_NAME,
            "overwrite": False,
        },
        "compiler": {
            "program": COMPILER,
            "arguments": arguments,
            "shell": False,
            "execution_authorized": False,
        },
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def create_desktop_installer_build_plan(
    bundle_directory: Path | str,
    evidence_directory: Path | str,
    *,
    project_file: Path | str,
    output_directory: Path | str,
    expected_freeze_evidence_sha256: str,
    expected_dependency_evidence_sha256: str,
    expected_sbom_sha256: str,
    release_candidate: bool = False,
) -> Path:
    """Create a canonical plan pair without downloading or executing a compiler."""

    if not isinstance(release_candidate, bool):
        raise TypeError("release_candidate must be a boolean")
    plan = _compose_plan(
        bundle_directory=bundle_directory,
        evidence_directory=evidence_directory,
        project_file=project_file,
        output_directory=output_directory,
        expected_freeze_evidence_sha256=expected_freeze_evidence_sha256,
        expected_dependency_evidence_sha256=expected_dependency_evidence_sha256,
        expected_sbom_sha256=expected_sbom_sha256,
        release_candidate=release_candidate,
        allowed_output_entries=frozenset(),
    )
    _validate_schema(plan)
    payload = _json_bytes(plan)
    output = Path(output_directory).expanduser().absolute().resolve()
    plan_path = output / PLAN_NAME
    sidecar_path = output / SIDECAR_NAME
    written: list[Path] = []
    try:
        written.append(
            write_new_exact_file(payload, plan_path, artifact_label="Installer build plan")
        )
        digest = hashlib.sha256(payload).hexdigest()
        written.append(
            write_new_exact_file(
                f"{digest}  {PLAN_NAME}\n".encode("ascii"),
                sidecar_path,
                artifact_label="Installer build plan sidecar",
            )
        )
        verify_desktop_installer_build_plan(plan_path, expected_plan_sha256=digest)
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise
    return plan_path


def verify_desktop_installer_build_plan(
    plan_path: Path | str,
    *,
    expected_plan_sha256: str,
) -> dict[str, object]:
    """Verify the exact plan pair and reconstruct every available source binding."""

    return _verify_desktop_installer_build_plan(
        plan_path,
        expected_plan_sha256=expected_plan_sha256,
        include_setup_output=False,
    )


def verify_desktop_installer_build_plan_after_build(
    plan_path: Path | str,
    *,
    expected_plan_sha256: str,
) -> dict[str, object]:
    """Reconstruct a plan whose exact expected setup output now exists."""

    return _verify_desktop_installer_build_plan(
        plan_path,
        expected_plan_sha256=expected_plan_sha256,
        include_setup_output=True,
    )


def _verify_desktop_installer_build_plan(
    plan_path: Path | str,
    *,
    expected_plan_sha256: str,
    include_setup_output: bool,
) -> dict[str, object]:
    if not isinstance(include_setup_output, bool):
        raise TypeError("include_setup_output must be a boolean")

    expected = _expected_sha256(expected_plan_sha256, label="installer build plan")
    path = _real_file(plan_path, label="Installer build plan", expected_name=PLAN_NAME)
    sidecar = _real_file(
        path.with_name(SIDECAR_NAME),
        label="Installer build plan sidecar",
        expected_name=SIDECAR_NAME,
    )
    try:
        payload = path.read_bytes()
        plan = json.loads(payload.decode("utf-8"))
        sidecar_payload = sidecar.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopInstallerPlanError("Installer build plan is not readable") from error
    _validate_schema(plan)
    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected:
        raise DesktopInstallerPlanError(
            "Installer build plan differs from the externally expected SHA-256"
        )
    if sidecar_payload != f"{observed}  {PLAN_NAME}\n".encode("ascii"):
        raise DesktopInstallerPlanError("Installer build plan sidecar is malformed")
    if payload != _json_bytes(plan):
        raise DesktopInstallerPlanError("Installer build plan is not canonical JSON")
    if Path(plan["output"]["directory"]).resolve() != path.parent:
        raise DesktopInstallerPlanError("Installer build plan output directory differs")
    allowed_output_entries = {PLAN_NAME, SIDECAR_NAME}
    if include_setup_output:
        setup_filename = plan["output"]["setup_filename"]
        allowed_output_entries.update((setup_filename, f"{setup_filename}.sha256"))
    rebuilt = _compose_plan(
        bundle_directory=plan["inputs"]["bundle"]["directory"],
        evidence_directory=plan["inputs"]["evidence"]["directory"],
        project_file=plan["inputs"]["project"]["path"],
        output_directory=plan["output"]["directory"],
        expected_freeze_evidence_sha256=(plan["inputs"]["evidence"]["freeze_evidence_sha256"]),
        expected_dependency_evidence_sha256=(
            plan["inputs"]["evidence"]["dependency_evidence_sha256"]
        ),
        expected_sbom_sha256=plan["inputs"]["evidence"]["sbom_sha256"],
        release_candidate=plan["source"]["release_candidate"],
        allowed_output_entries=frozenset(allowed_output_entries),
    )
    if plan != rebuilt or payload != _json_bytes(rebuilt):
        raise DesktopInstallerPlanError(
            "Installer build plan differs from reconstructed exact inputs"
        )
    return plan

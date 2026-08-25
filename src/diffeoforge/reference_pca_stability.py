"""Immutable paired stability evidence for verified Deformetrica PCA bundles."""

from __future__ import annotations

import json
import math
import shutil
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from diffeoforge.analysis.pca import PCAResult
from diffeoforge.analysis.pca_stability import (
    PCAStabilityEvidence,
    compare_pca_stability,
)
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import (
    REFERENCE_PCA_MANIFEST,
    ReferencePCABundle,
    verify_reference_pca_bundle,
)
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

REFERENCE_PCA_STABILITY_VERSION = "0.1"
REFERENCE_PCA_STABILITY_MANIFEST = "reference-pca-stability.json"
REFERENCE_PCA_STABILITY_SIDECAR = "reference-pca-stability.sha256"
SCIENTIFIC_BOUNDARY = (
    "This artifact measures paired numerical PCA stability. It does not establish "
    "biological meaning, taxonomic separation, registration validity, or an automatic "
    "parameter winner."
)
VERIFICATION_CONTRACT = (
    "Both source PCA bundles, their complete inventories, raw parameters, PCA tables, "
    "source manifest hashes, and this stability calculation are reverified."
)


class ReferencePCAStabilityError(RuntimeError):
    """Raised when paired PCA stability evidence is invalid or changed."""


@dataclass(frozen=True)
class ReferencePCAStabilityArtifact:
    artifact_directory: Path
    manifest: dict[str, Any]
    evidence: PCAStabilityEvidence


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _bundle_record(bundle: ReferencePCABundle) -> dict[str, object]:
    manifest_path = bundle.bundle_directory / REFERENCE_PCA_MANIFEST
    inputs = bundle.manifest["inputs"]
    return {
        "bundle_directory": str(bundle.bundle_directory),
        "bundle_version": str(bundle.manifest["bundle_version"]),
        "manifest_sha256": sha256_file(manifest_path),
        "momenta_sha256": str(inputs["momenta"]["sha256"]),
        "control_points_sha256": str(inputs["control_points"]["sha256"]),
        "subjects": int(inputs["subjects"]),
        "control_point_count": int(inputs["control_point_count"]),
        "subject_labels": list(bundle.pca.sample_labels),
    }


def _identity_bound_pca(bundle: ReferencePCABundle) -> PCAResult:
    control_hash = str(bundle.manifest["inputs"]["control_points"]["sha256"])
    return replace(
        bundle.pca,
        feature_space=(
            f"{bundle.pca.feature_space}:control-points-sha256={control_hash}"
        ),
    )


def _verified_bundle(path: Path | str) -> ReferencePCABundle:
    try:
        return verify_reference_pca_bundle(path)
    except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise ReferencePCAStabilityError(str(error)) from error


def _compute(
    reference: ReferencePCABundle,
    comparison: ReferencePCABundle,
    *,
    variance_target: float,
    component_count: int | None,
) -> PCAStabilityEvidence:
    try:
        return compare_pca_stability(
            _identity_bound_pca(reference),
            _identity_bound_pca(comparison),
            variance_target=variance_target,
            component_count=component_count,
        )
    except (TypeError, ValueError) as error:
        raise ReferencePCAStabilityError(
            f"Could not compare the verified PCA bundles: {error}"
        ) from error


def write_reference_pca_stability(
    reference_bundle: Path | str,
    comparison_bundle: Path | str,
    destination: Path | str,
    *,
    variance_target: float = 0.90,
    component_count: int | None = None,
    created_at: str | None = None,
) -> Path:
    """Atomically publish source-bound paired PCA stability evidence."""

    reference = _verified_bundle(reference_bundle)
    comparison = _verified_bundle(comparison_bundle)
    if reference.bundle_directory == comparison.bundle_directory:
        raise ReferencePCAStabilityError("PCA stability requires two distinct bundles")
    evidence = _compute(
        reference,
        comparison,
        variance_target=variance_target,
        component_count=component_count,
    )
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(
            f"Reference PCA stability destination already exists: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ReferencePCAStabilityError(
                "created_at must be an ISO-8601 timestamp"
            ) from error
        if parsed.tzinfo is None:
            raise ReferencePCAStabilityError("created_at must include a timezone offset")
        manifest = {
            "artifact_version": REFERENCE_PCA_STABILITY_VERSION,
            "created_at": timestamp,
            "reference": _bundle_record(reference),
            "comparison": _bundle_record(comparison),
            "selection": {
                "variance_target": float(variance_target),
                "component_count": component_count,
            },
            "evidence": evidence.as_manifest(),
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
            "verification_contract": VERIFICATION_CONTRACT,
        }
        manifest_path = temporary / REFERENCE_PCA_STABILITY_MANIFEST
        write_text_safely(
            manifest_path,
            _canonical_json(manifest),
            overwrite=False,
        )
        write_text_safely(
            temporary / REFERENCE_PCA_STABILITY_SIDECAR,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
        )
        verify_reference_pca_stability(temporary)
        publish_directory_exclusive(temporary, target)
        return verify_reference_pca_stability(target).artifact_directory
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def _source_bundle(record: object, *, label: str) -> ReferencePCABundle:
    if not isinstance(record, dict):
        raise ReferencePCAStabilityError(f"{label} source record must be an object")
    required = {
        "bundle_directory",
        "bundle_version",
        "manifest_sha256",
        "momenta_sha256",
        "control_points_sha256",
        "subjects",
        "control_point_count",
        "subject_labels",
    }
    if set(record) != required:
        raise ReferencePCAStabilityError(f"{label} source record fields differ")
    bundle = _verified_bundle(str(record["bundle_directory"]))
    expected = _bundle_record(bundle)
    if record != expected:
        raise ReferencePCAStabilityError(
            f"{label} PCA bundle identity or source hashes changed"
        )
    return bundle


def verify_reference_pca_stability(
    artifact_directory: Path | str,
) -> ReferencePCAStabilityArtifact:
    """Reverify both PCA bundles and exactly recompute paired stability evidence."""

    root = Path(artifact_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ReferencePCAStabilityError(
            f"Reference PCA stability artifact is missing or symbolic: {root}"
        )
    manifest_path = root / REFERENCE_PCA_STABILITY_MANIFEST
    sidecar_path = root / REFERENCE_PCA_STABILITY_SIDECAR
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise ReferencePCAStabilityError(
            "Reference PCA stability manifest or SHA-256 sidecar is missing"
        )
    actual_files = {path.name for path in root.iterdir() if path.is_file()}
    expected_files = {
        REFERENCE_PCA_STABILITY_MANIFEST,
        REFERENCE_PCA_STABILITY_SIDECAR,
    }
    if actual_files != expected_files or any(path.is_dir() for path in root.iterdir()):
        raise ReferencePCAStabilityError(
            "Reference PCA stability artifact contains an unexpected file or directory"
        )
    try:
        expected_hash = sidecar_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise ReferencePCAStabilityError(
            "Could not read the PCA stability SHA-256 sidecar"
        ) from error
    if expected_hash != sha256_file(manifest_path):
        raise ReferencePCAStabilityError(
            "Reference PCA stability manifest SHA-256 differs"
        )
    try:
        manifest = load_strict_json_object(
            manifest_path.read_bytes(),
            manifest_path,
            label="Reference PCA stability manifest",
        )
    except (ConfigurationError, OSError) as error:
        raise ReferencePCAStabilityError(str(error)) from error
    required = {
        "artifact_version",
        "created_at",
        "reference",
        "comparison",
        "selection",
        "evidence",
        "scientific_boundary",
        "verification_contract",
    }
    if set(manifest) != required:
        raise ReferencePCAStabilityError("PCA stability manifest fields differ")
    if manifest["artifact_version"] != REFERENCE_PCA_STABILITY_VERSION:
        raise ReferencePCAStabilityError(
            f"Unsupported PCA stability version: {manifest['artifact_version']}"
        )
    if (
        manifest["scientific_boundary"] != SCIENTIFIC_BOUNDARY
        or manifest["verification_contract"] != VERIFICATION_CONTRACT
    ):
        raise ReferencePCAStabilityError(
            "PCA stability claim boundary or verification contract differs"
        )
    try:
        parsed = datetime.fromisoformat(
            str(manifest["created_at"]).replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ReferencePCAStabilityError(
            "PCA stability created_at is not ISO-8601"
        ) from error
    if parsed.tzinfo is None:
        raise ReferencePCAStabilityError(
            "PCA stability created_at has no timezone offset"
        )
    reference = _source_bundle(manifest["reference"], label="Reference")
    comparison = _source_bundle(manifest["comparison"], label="Comparison")
    if reference.bundle_directory == comparison.bundle_directory:
        raise ReferencePCAStabilityError("PCA stability sources are not distinct")
    selection = manifest["selection"]
    if not isinstance(selection, dict) or set(selection) != {
        "variance_target",
        "component_count",
    }:
        raise ReferencePCAStabilityError("PCA stability selection fields differ")
    variance_target = selection["variance_target"]
    component_count = selection["component_count"]
    if isinstance(variance_target, bool) or not isinstance(variance_target, (int, float)):
        raise ReferencePCAStabilityError("variance_target must be numeric")
    normalized_target = float(variance_target)
    if not math.isfinite(normalized_target):
        raise ReferencePCAStabilityError("variance_target must be finite")
    evidence = _compute(
        reference,
        comparison,
        variance_target=normalized_target,
        component_count=component_count,
    )
    if manifest["evidence"] != evidence.as_manifest():
        raise ReferencePCAStabilityError(
            "Recorded PCA stability evidence differs from exact recomputation"
        )
    return ReferencePCAStabilityArtifact(root, dict(manifest), evidence)

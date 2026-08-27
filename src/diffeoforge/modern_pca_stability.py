"""Immutable paired PCA stability evidence for verified Modern atlas bundles."""

from __future__ import annotations

import csv
import json
import math
import shutil
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from diffeoforge.analysis.pca import PCAResult, momenta_pca
from diffeoforge.analysis.pca_artifacts import (
    pca_loading_rows,
    pca_mean_rows,
    pca_score_rows,
    pca_summary_document,
)
from diffeoforge.analysis.pca_stability import (
    PCAStabilityEvidence,
    compare_pca_stability,
)
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.modern_bundle import MANIFEST_NAME, verify_modern_atlas_bundle
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

MODERN_PCA_STABILITY_VERSION = "0.1"
MODERN_PCA_STABILITY_MANIFEST = "modern-pca-stability.json"
MODERN_PCA_STABILITY_SIDECAR = "modern-pca-stability.sha256"
PCA_RECOMPUTATION_RTOL = 1e-12
PCA_RECOMPUTATION_ATOL = 1e-13
SCIENTIFIC_BOUNDARY = (
    "This artifact measures paired numerical stability of two Modern Engine momenta "
    "PCA results. It does not establish biological meaning, taxonomic separation, "
    "registration validity, optimizer equivalence, or an automatic engine winner."
)
VERIFICATION_CONTRACT = (
    "Both complete Modern atlas bundles, their raw momenta, control-point identities, "
    "stored PCA tables, source manifest hashes, and this stability calculation are "
    "reverified. Loading-subspace angles are withheld unless control-point bytes match."
)


class ModernPCAStabilityError(RuntimeError):
    """Raised when Modern paired PCA evidence is invalid or changed."""


@dataclass(frozen=True)
class VerifiedModernPCABundle:
    """One fully verified Modern bundle plus PCA recomputed from raw momenta."""

    bundle_directory: Path
    manifest: dict[str, Any]
    pca: PCAResult
    manifest_sha256: str
    momenta_sha256: str
    control_points_sha256: str


@dataclass(frozen=True)
class ModernPCAStabilityArtifact:
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


def _safe_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernPCAStabilityError(f"{label} path must be a non-empty POSIX path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ModernPCAStabilityError(f"{label} escapes the Modern bundle")
    candidate = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    try:
        candidate.resolve().relative_to(resolved_root)
    except ValueError as error:
        raise ModernPCAStabilityError(
            f"{label} does not resolve inside the Modern bundle"
        ) from error
    return candidate


def _read_csv(path: Path, label: str) -> list[list[str]]:
    try:
        with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
            return list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernPCAStabilityError(f"Could not read {label}: {path}") from error


def _csv_label(value: str) -> str:
    return f"'{value}" if value[0] in "=+-@\t\r" else value


def _artifact_sha256(manifest: dict[str, Any], relative_path: str) -> str:
    matches = [
        record
        for record in manifest["artifacts"]
        if record["path"] == relative_path
    ]
    if len(matches) != 1:
        raise ModernPCAStabilityError(
            f"Modern bundle has no unique artifact record for {relative_path}"
        )
    return str(matches[0]["sha256"])


def _read_momenta(
    root: Path,
    manifest: dict[str, Any],
) -> tuple[np.ndarray, tuple[str, ...]]:
    subjects = manifest["subjects"]
    labels = tuple(str(record["label"]) for record in subjects)
    if [record["index"] for record in subjects] != list(range(len(subjects))):
        raise ModernPCAStabilityError("Modern bundle subject indices are not contiguous")
    if len(set(labels)) != len(labels):
        raise ModernPCAStabilityError("Modern bundle subject labels are not unique")
    subject_count = int(manifest["parameters"]["subjects"])
    control_count = int(manifest["parameters"]["control_points"])
    if len(labels) != subject_count:
        raise ModernPCAStabilityError("Modern bundle subject count differs from its manifest")
    path = _safe_path(
        root,
        manifest["parameters"]["momenta_path"],
        "Modern momenta",
    )
    rows = _read_csv(path, "Modern momenta")
    if not rows or rows[0] != ["subject_label", "control_point", "x", "y", "z"]:
        raise ModernPCAStabilityError("Modern momenta CSV header differs")
    if len(rows) != 1 + subject_count * control_count:
        raise ModernPCAStabilityError("Modern momenta CSV row count differs")
    values = np.empty((subject_count, control_count, 3), dtype=np.float64)
    row_index = 1
    for subject_index, label in enumerate(labels):
        expected_label = _csv_label(label)
        for control_index in range(control_count):
            row = rows[row_index]
            row_index += 1
            if len(row) != 5 or row[0] != expected_label or row[1] != str(control_index):
                raise ModernPCAStabilityError(
                    f"Modern momenta identity differs at CSV line {row_index}"
                )
            try:
                values[subject_index, control_index] = np.asarray(
                    row[2:], dtype=np.float64
                )
            except ValueError as error:
                raise ModernPCAStabilityError(
                    f"Modern momenta contain a non-number at CSV line {row_index}"
                ) from error
    if not bool(np.isfinite(values).all()):
        raise ModernPCAStabilityError("Modern momenta contain a non-finite value")
    return values, labels


def _assert_numeric_rows_close(
    observed: Sequence[Sequence[str]],
    expected: Sequence[Sequence[str]],
    *,
    label: str,
) -> None:
    if len(observed) != len(expected) or not observed or observed[0] != list(expected[0]):
        raise ModernPCAStabilityError(f"{label} structure differs from recomputed PCA")
    for line, (actual, wanted) in enumerate(
        zip(observed[1:], expected[1:], strict=True), start=2
    ):
        if len(actual) != len(wanted) or actual[0] != wanted[0]:
            raise ModernPCAStabilityError(f"{label} identity differs at CSV line {line}")
        try:
            actual_values = np.asarray(actual[1:], dtype=np.float64)
            wanted_values = np.asarray(wanted[1:], dtype=np.float64)
        except ValueError as error:
            raise ModernPCAStabilityError(
                f"{label} contains a non-number at CSV line {line}"
            ) from error
        if not bool(
            np.allclose(
                actual_values,
                wanted_values,
                rtol=PCA_RECOMPUTATION_RTOL,
                atol=PCA_RECOMPUTATION_ATOL,
                equal_nan=False,
            )
        ):
            raise ModernPCAStabilityError(f"{label} values differ at CSV line {line}")


def _verify_summary(path: Path, pca: PCAResult) -> None:
    try:
        observed = load_strict_json_object(path.read_bytes(), path, label="PCA summary")
    except (ConfigurationError, OSError) as error:
        raise ModernPCAStabilityError(str(error)) from error
    expected = pca_summary_document(pca)
    scalar_keys = (
        "feature_space",
        "sample_labels",
        "feature_labels",
        "number_of_components",
        "numerical_rank",
        "tied_component_groups",
        "zero_variance_components",
        "sign_convention",
    )
    if any(observed.get(key) != expected[key] for key in scalar_keys):
        raise ModernPCAStabilityError("PCA summary identity or structural evidence differs")
    for key in (
        "total_variance",
        "singular_values",
        "explained_variance",
        "explained_variance_ratio",
    ):
        try:
            actual = np.asarray(observed[key], dtype=np.float64)
            wanted = np.asarray(expected[key], dtype=np.float64)
        except (KeyError, TypeError, ValueError) as error:
            raise ModernPCAStabilityError(f"PCA summary {key} is invalid") from error
        if actual.shape != wanted.shape or not bool(
            np.allclose(
                actual,
                wanted,
                rtol=PCA_RECOMPUTATION_RTOL,
                atol=PCA_RECOMPUTATION_ATOL,
                equal_nan=False,
            )
        ):
            raise ModernPCAStabilityError(
                f"PCA summary {key} differs from recomputation"
            )


def verify_modern_pca_bundle(directory: Path | str) -> VerifiedModernPCABundle:
    """Verify one complete Modern bundle and recompute its PCA from raw momenta."""

    root = Path(directory).expanduser().resolve()
    try:
        manifest = verify_modern_atlas_bundle(root)
        momenta, labels = _read_momenta(root, manifest)
        pca = momenta_pca(
            momenta,
            n_components=int(manifest["pca"]["components"]),
            subject_labels=labels,
        )
    except ModernPCAStabilityError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, np.linalg.LinAlgError) as error:
        raise ModernPCAStabilityError(str(error)) from error
    if pca.numerical_rank != int(manifest["pca"]["numerical_rank"]) or not math.isclose(
        pca.total_variance,
        float(manifest["pca"]["total_variance"]),
        rel_tol=PCA_RECOMPUTATION_RTOL,
        abs_tol=PCA_RECOMPUTATION_ATOL,
    ):
        raise ModernPCAStabilityError("Modern PCA manifest statistics differ")
    _verify_summary(
        _safe_path(root, manifest["pca"]["summary_path"], "Modern PCA summary"),
        pca,
    )
    for relative_path, expected_rows, label in (
        (manifest["pca"]["scores_path"], pca_score_rows(pca), "Modern PCA scores"),
        (
            manifest["pca"]["loadings_path"],
            pca_loading_rows(pca),
            "Modern PCA loadings",
        ),
        (manifest["pca"]["mean_path"], pca_mean_rows(pca), "Modern PCA mean"),
    ):
        _assert_numeric_rows_close(
            _read_csv(_safe_path(root, relative_path, label), label),
            expected_rows,
            label=label,
        )
    manifest_path = root / MANIFEST_NAME
    momenta_path = str(manifest["parameters"]["momenta_path"])
    control_path = str(manifest["parameters"]["control_points_path"])
    return VerifiedModernPCABundle(
        bundle_directory=root,
        manifest=manifest,
        pca=pca,
        manifest_sha256=sha256_file(manifest_path),
        momenta_sha256=_artifact_sha256(manifest, momenta_path),
        control_points_sha256=_artifact_sha256(manifest, control_path),
    )


def _bundle_record(bundle: VerifiedModernPCABundle) -> dict[str, object]:
    return {
        "bundle_directory": str(bundle.bundle_directory),
        "bundle_version": str(bundle.manifest["bundle_version"]),
        "manifest_sha256": bundle.manifest_sha256,
        "engine_implementation_version": str(
            bundle.manifest["engine"]["implementation_version"]
        ),
        "momenta_sha256": bundle.momenta_sha256,
        "control_points_sha256": bundle.control_points_sha256,
        "subjects": int(bundle.manifest["parameters"]["subjects"]),
        "control_point_count": int(bundle.manifest["parameters"]["control_points"]),
        "subject_labels": list(bundle.pca.sample_labels),
    }


def _identity_bound_pca(bundle: VerifiedModernPCABundle) -> PCAResult:
    return replace(
        bundle.pca,
        feature_space=(
            f"{bundle.pca.feature_space}:control-points-sha256="
            f"{bundle.control_points_sha256}"
        ),
    )


def _compute(
    reference: VerifiedModernPCABundle,
    comparison: VerifiedModernPCABundle,
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
        raise ModernPCAStabilityError(
            f"Could not compare the verified Modern PCA results: {error}"
        ) from error


def write_modern_pca_stability(
    reference_bundle: Path | str,
    comparison_bundle: Path | str,
    destination: Path | str,
    *,
    variance_target: float = 0.90,
    component_count: int | None = None,
    created_at: str | None = None,
) -> Path:
    """Atomically publish source-bound paired Modern PCA stability evidence."""

    reference = verify_modern_pca_bundle(reference_bundle)
    comparison = verify_modern_pca_bundle(comparison_bundle)
    if reference.bundle_directory == comparison.bundle_directory:
        raise ModernPCAStabilityError("PCA stability requires two distinct bundles")
    evidence = _compute(
        reference,
        comparison,
        variance_target=variance_target,
        component_count=component_count,
    )
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(
            f"Modern PCA stability destination already exists: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ModernPCAStabilityError(
                "created_at must be an ISO-8601 timestamp"
            ) from error
        if parsed.tzinfo is None:
            raise ModernPCAStabilityError("created_at must include a timezone offset")
        manifest = {
            "artifact_version": MODERN_PCA_STABILITY_VERSION,
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
        manifest_path = temporary / MODERN_PCA_STABILITY_MANIFEST
        write_text_safely(manifest_path, _canonical_json(manifest), overwrite=False)
        write_text_safely(
            temporary / MODERN_PCA_STABILITY_SIDECAR,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
        )
        verify_modern_pca_stability(temporary)
        publish_directory_exclusive(temporary, target)
        return verify_modern_pca_stability(target).artifact_directory
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def _source_bundle(record: object, *, label: str) -> VerifiedModernPCABundle:
    if not isinstance(record, dict):
        raise ModernPCAStabilityError(f"{label} source record must be an object")
    required = {
        "bundle_directory",
        "bundle_version",
        "manifest_sha256",
        "engine_implementation_version",
        "momenta_sha256",
        "control_points_sha256",
        "subjects",
        "control_point_count",
        "subject_labels",
    }
    if set(record) != required:
        raise ModernPCAStabilityError(f"{label} source record fields differ")
    bundle = verify_modern_pca_bundle(str(record["bundle_directory"]))
    if record != _bundle_record(bundle):
        raise ModernPCAStabilityError(
            f"{label} Modern bundle identity or source hashes changed"
        )
    return bundle


def verify_modern_pca_stability(
    artifact_directory: Path | str,
) -> ModernPCAStabilityArtifact:
    """Reverify both Modern bundles and exactly recompute paired PCA stability."""

    root = Path(artifact_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ModernPCAStabilityError(
            f"Modern PCA stability artifact is missing or symbolic: {root}"
        )
    manifest_path = root / MODERN_PCA_STABILITY_MANIFEST
    sidecar_path = root / MODERN_PCA_STABILITY_SIDECAR
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise ModernPCAStabilityError(
            "Modern PCA stability manifest or SHA-256 sidecar is missing"
        )
    actual_files = {path.name for path in root.iterdir() if path.is_file()}
    expected_files = {MODERN_PCA_STABILITY_MANIFEST, MODERN_PCA_STABILITY_SIDECAR}
    if actual_files != expected_files or any(path.is_dir() for path in root.iterdir()):
        raise ModernPCAStabilityError(
            "Modern PCA stability artifact contains an unexpected file or directory"
        )
    try:
        expected_hash = sidecar_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise ModernPCAStabilityError(
            "Could not read the Modern PCA stability SHA-256 sidecar"
        ) from error
    if expected_hash != sha256_file(manifest_path):
        raise ModernPCAStabilityError(
            "Modern PCA stability manifest SHA-256 differs"
        )
    try:
        manifest = load_strict_json_object(
            manifest_path.read_bytes(),
            manifest_path,
            label="Modern PCA stability manifest",
        )
    except (ConfigurationError, OSError) as error:
        raise ModernPCAStabilityError(str(error)) from error
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
        raise ModernPCAStabilityError("Modern PCA stability manifest fields differ")
    if manifest["artifact_version"] != MODERN_PCA_STABILITY_VERSION:
        raise ModernPCAStabilityError(
            f"Unsupported Modern PCA stability version: {manifest['artifact_version']}"
        )
    if (
        manifest["scientific_boundary"] != SCIENTIFIC_BOUNDARY
        or manifest["verification_contract"] != VERIFICATION_CONTRACT
    ):
        raise ModernPCAStabilityError(
            "Modern PCA stability claim boundary or verification contract differs"
        )
    try:
        parsed = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ModernPCAStabilityError(
            "Modern PCA stability created_at is not ISO-8601"
        ) from error
    if parsed.tzinfo is None:
        raise ModernPCAStabilityError(
            "Modern PCA stability created_at has no timezone offset"
        )
    reference = _source_bundle(manifest["reference"], label="Reference")
    comparison = _source_bundle(manifest["comparison"], label="Comparison")
    if reference.bundle_directory == comparison.bundle_directory:
        raise ModernPCAStabilityError("PCA stability sources are not distinct")
    selection = manifest["selection"]
    if not isinstance(selection, dict) or set(selection) != {
        "variance_target",
        "component_count",
    }:
        raise ModernPCAStabilityError("Modern PCA stability selection fields differ")
    variance_target = selection["variance_target"]
    component_count = selection["component_count"]
    if isinstance(variance_target, bool) or not isinstance(variance_target, (int, float)):
        raise ModernPCAStabilityError("variance_target must be numeric")
    normalized_target = float(variance_target)
    if not math.isfinite(normalized_target):
        raise ModernPCAStabilityError("variance_target must be finite")
    evidence = _compute(
        reference,
        comparison,
        variance_target=normalized_target,
        component_count=component_count,
    )
    if manifest["evidence"] != evidence.as_manifest():
        raise ModernPCAStabilityError(
            "Recorded Modern PCA stability evidence differs from exact recomputation"
        )
    return ModernPCAStabilityArtifact(root, dict(manifest), evidence)

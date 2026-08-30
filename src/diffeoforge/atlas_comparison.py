"""Direct quantitative comparison of two verified atlas/PCA results."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import shutil
import uuid
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np

from diffeoforge.analysis.pca_stability import compare_pca_stability
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.reference_result_review import review_reference_result
from diffeoforge.desktop.result_review import (
    ModernResultReview,
    ModernResultReviewError,
    review_modern_result,
    verify_result_artifact,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.modern_pca_stability import verify_modern_pca_bundle
from diffeoforge.reference_pca import verify_reference_pca_bundle
from diffeoforge.reference_sensitivity_assessment import (
    compare_ordered_atlas_templates,
)
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

ATLAS_COMPARISON_VERSION = "0.1"
ATLAS_COMPARISON_MANIFEST = "atlas-comparison-manifest.json"
ATLAS_COMPARISON_SIDECAR = "atlas-comparison-manifest.sha256"
ATLAS_COMPARISON_JSON = "atlas-comparison.json"
ATLAS_COMPARISON_HTML = "atlas-comparison.html"
ATLAS_COMPARISON_SUBJECTS = "subject-residual-comparison.csv"
SCIENTIFIC_BOUNDARY = (
    "This is a paired descriptive comparison of verified numerical atlas outputs. It "
    "does not select a universally superior engine or parameter set, establish biological "
    "meaning, or make automatic specimen-exclusion decisions."
)


class AtlasComparisonError(RuntimeError):
    """Raised when source runs cannot be compared or an artifact changed."""


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _review(directory: Path | str) -> ModernResultReview:
    try:
        return review_modern_result(directory)
    except (ModernResultReviewError, OSError, RuntimeError, TypeError, ValueError):
        try:
            return review_reference_result(directory)
        except (ModernResultReviewError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise AtlasComparisonError(
                f"Could not verify atlas/PCA result {Path(directory)}: {error}"
            ) from error


def _pca(review: ModernResultReview):
    try:
        if review.engine_route == "deformetrica_reference":
            return verify_reference_pca_bundle(review.bundle_directory).pca
        return verify_modern_pca_bundle(review.bundle_directory).pca
    except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise AtlasComparisonError(f"Could not reverify PCA source: {error}") from error


def _source(review: ModernResultReview) -> dict[str, object]:
    return {
        "run_directory": str(review.run_directory),
        "project": review.project_name,
        "engine_route": review.engine_route,
        "workflow_manifest_path": str(review.workflow_manifest_path),
        "workflow_manifest_sha256": review.workflow_manifest_sha256,
        "pca_bundle_directory": str(review.bundle_directory),
        "pca_manifest_path": str(review.bundle_manifest_path),
        "pca_manifest_sha256": review.bundle_manifest_sha256,
    }


def _residuals(review: ModernResultReview) -> dict[str, float]:
    return {item.subject_name: float(item.residual_p95) for item in review.registration_qc}


def _residual_summary(values: dict[str, float]) -> dict[str, float | int | None]:
    if not values:
        return {"subject_count": 0, "median": None, "p95": None, "maximum": None}
    observed = np.asarray(tuple(values.values()), dtype=np.float64)
    return {
        "subject_count": len(observed),
        "median": float(np.median(observed)),
        "p95": float(np.quantile(observed, 0.95, method="linear")),
        "maximum": float(np.max(observed)),
    }


def _top_fraction(values: dict[str, float], fraction: float = 0.10) -> tuple[str, ...]:
    count = max(1, int(math.ceil(len(values) * fraction)))
    ranked = sorted(values.items(), key=lambda item: (-item[1], item[0].casefold()))
    return tuple(name for name, _ in ranked[:count])


def _comparison_payload(
    first_directory: Path | str,
    second_directory: Path | str,
    *,
    first_label: str,
    second_label: str,
    variance_target: float,
    created_at: str,
) -> tuple[dict[str, Any], ModernResultReview, ModernResultReview]:
    if not first_label.strip() or not second_label.strip() or first_label == second_label:
        raise AtlasComparisonError("Comparison labels must be nonempty and distinct")
    if not 0.0 < float(variance_target) <= 1.0:
        raise AtlasComparisonError("variance_target must be in (0, 1]")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise AtlasComparisonError("created_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise AtlasComparisonError("created_at must include a timezone offset")
    first = _review(first_directory)
    second = _review(second_directory)
    if first.run_directory == second.run_directory:
        raise AtlasComparisonError("Atlas comparison requires two distinct results")
    first_residuals = _residuals(first)
    second_residuals = _residuals(second)
    shared_subjects = tuple(sorted(set(first_residuals) & set(second_residuals), key=str.casefold))
    paired_residuals = None
    outlier_overlap = None
    if set(first_residuals) == set(second_residuals) and first_residuals:
        differences = np.asarray(
            [first_residuals[name] - second_residuals[name] for name in shared_subjects],
            dtype=np.float64,
        )
        first_high = set(_top_fraction(first_residuals))
        second_high = set(_top_fraction(second_residuals))
        paired_residuals = {
            "subject_count": len(shared_subjects),
            "median_first_minus_second": float(np.median(differences)),
            "first_lower_count": int(np.sum(differences < 0.0)),
            "equal_count": int(np.sum(np.isclose(differences, 0.0, rtol=1e-12, atol=1e-15))),
            "second_lower_count": int(np.sum(differences > 0.0)),
        }
        outlier_overlap = {
            "selection_fraction": 0.10,
            "first": sorted(first_high, key=str.casefold),
            "second": sorted(second_high, key=str.casefold),
            "jaccard": len(first_high & second_high) / len(first_high | second_high),
            "boundary": "High residual means visual-inspection priority, not exclusion.",
        }

    try:
        template = compare_ordered_atlas_templates(
            verify_result_artifact(first, "estimated-template"),
            verify_result_artifact(second, "estimated-template"),
        )
        template_evidence: dict[str, object] = {
            "available": True,
            **template,
            "metric": "corresponding ordered-vertex displacement",
        }
    except (KeyError, ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
        template_evidence = {
            "available": False,
            "unavailable_reason": str(error),
        }

    first_pca = _pca(first)
    second_pca = _pca(second)
    if set(first_pca.sample_labels) == set(second_pca.sample_labels):
        try:
            stability = compare_pca_stability(
                first_pca,
                second_pca,
                variance_target=variance_target,
            )
            pca_evidence: dict[str, object] = {
                "available": True,
                **stability.as_manifest(),
            }
        except (TypeError, ValueError) as error:
            pca_evidence = {"available": False, "unavailable_reason": str(error)}
    else:
        pca_evidence = {
            "available": False,
            "unavailable_reason": "PCA specimen identities differ; paired stability is undefined.",
        }
    payload = {
        "comparison_version": ATLAS_COMPARISON_VERSION,
        "created_at": created_at,
        "labels": {"first": first_label, "second": second_label},
        "sources": {"first": _source(first), "second": _source(second)},
        "technical_status": {
            "first": {
                "optimizer_converged": first.optimizer_converged,
                "termination_reason": first.optimizer_termination_reason,
                "completed_cycles_or_iterations": first.optimizer_cycles_completed,
                "configured_maximum": first.optimizer_max_cycles,
                "duration_seconds": first.execution_duration_seconds,
            },
            "second": {
                "optimizer_converged": second.optimizer_converged,
                "termination_reason": second.optimizer_termination_reason,
                "completed_cycles_or_iterations": second.optimizer_cycles_completed,
                "configured_maximum": second.optimizer_max_cycles,
                "duration_seconds": second.execution_duration_seconds,
            },
        },
        "registration_residuals": {
            "metric_boundary": (
                "Residuals are compared directly only for named metrics in each verified "
                "result. Cross-engine objective scales are not assumed equivalent."
            ),
            "first": _residual_summary(first_residuals),
            "second": _residual_summary(second_residuals),
            "paired": paired_residuals,
        },
        "high_residual_subject_overlap": outlier_overlap,
        "estimated_template_distance": template_evidence,
        "pca_stability": pca_evidence,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    return payload, first, second


def _csv_safe(value: object) -> str:
    text = str(value)
    return f"'{text}" if text and text[0] in "=+-@\t\r" else text


def _subject_csv(
    first: ModernResultReview,
    second: ModernResultReview,
    first_label: str,
    second_label: str,
) -> str:
    left = _residuals(first)
    right = _residuals(second)
    subjects = sorted(set(left) | set(right), key=str.casefold)
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("subject", first_label, second_label, "first_minus_second"))
    for subject in subjects:
        first_value = left.get(subject)
        second_value = right.get(subject)
        difference = (
            ""
            if first_value is None or second_value is None
            else format(first_value - second_value, ".17g")
        )
        writer.writerow(
            tuple(
                _csv_safe(value)
                for value in (
                    subject,
                    "" if first_value is None else format(first_value, ".17g"),
                    "" if second_value is None else format(second_value, ".17g"),
                    difference,
                )
            )
        )
    return buffer.getvalue()


def _html_report(payload: dict[str, Any]) -> str:
    labels = payload["labels"]
    residuals = payload["registration_residuals"]
    template = payload["estimated_template_distance"]
    pca = payload["pca_stability"]
    template_text = (
        f"ordered-vertex p95 {template['ordered_vertex_p95']:.6g}; "
        f"RMS {template['ordered_vertex_rms']:.6g}"
        if template["available"]
        else f"unavailable: {html.escape(template['unavailable_reason'])}"
    )
    pca_text = (
        f"linear CKA {pca['score_linear_cka']:.4f}; distance-rank correlation "
        f"{pca['score_distance_rank_correlation']:.4f}"
        if pca["available"]
        else f"unavailable: {html.escape(pca['unavailable_reason'])}"
    )
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(label)}</td><td>{value['subject_count']}</td>"
        f"<td>{html.escape(str(value['median']))}</td>"
        f"<td>{html.escape(str(value['p95']))}</td>"
        f"<td>{html.escape(str(payload['technical_status'][key]['optimizer_converged']))}</td>"
        "</tr>"
        for key, label, value in (
            ("first", labels["first"], residuals["first"]),
            ("second", labels["second"], residuals["second"]),
        )
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DiffeoForge atlas comparison</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1050px;margin:36px auto;padding:0 24px;
color:#103b3b;line-height:1.45}}.notice{{background:#e3f6ef;border-left:5px solid #13856f;
padding:14px 18px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd;
padding:9px;text-align:left}}th{{background:#eef5f4}}</style></head><body>
<h1>Direct atlas comparison</h1><p class="notice">{html.escape(SCIENTIFIC_BOUNDARY)}</p>
<table><thead><tr><th>Run</th><th>Subjects</th><th>Residual median</th><th>Residual p95</th>
<th>Optimizer converged</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Estimated-template distance</h2><p>{template_text}</p>
<h2>Paired PCA stability</h2><p>{pca_text}</p></body></html>"""


def write_atlas_comparison(
    first_directory: Path | str,
    second_directory: Path | str,
    destination: Path | str,
    *,
    first_label: str = "first",
    second_label: str = "second",
    variance_target: float = 0.90,
    created_at: str | None = None,
) -> Path:
    """Atomically publish a no-winner quantitative atlas comparison."""

    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    payload, first, second = _comparison_payload(
        first_directory,
        second_directory,
        first_label=first_label,
        second_label=second_label,
        variance_target=variance_target,
        created_at=timestamp,
    )
    files = {
        ATLAS_COMPARISON_JSON: _canonical_json(payload),
        ATLAS_COMPARISON_HTML: _html_report(payload),
        ATLAS_COMPARISON_SUBJECTS: _subject_csv(
            first, second, first_label, second_label
        ),
    }
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"Atlas comparison destination exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        for name, content in files.items():
            write_text_safely(temporary / name, content, overwrite=False)
        artifacts = [
            {
                "path": name,
                "bytes": len(content.encode("utf-8")),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            for name, content in sorted(files.items())
        ]
        manifest = {
            "artifact_version": ATLAS_COMPARISON_VERSION,
            "created_at": timestamp,
            "first_source": payload["sources"]["first"],
            "second_source": payload["sources"]["second"],
            "settings": {
                "first_label": first_label,
                "second_label": second_label,
                "variance_target": float(variance_target),
            },
            "artifacts": artifacts,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        manifest_path = temporary / ATLAS_COMPARISON_MANIFEST
        write_text_safely(manifest_path, _canonical_json(manifest), overwrite=False)
        write_text_safely(
            temporary / ATLAS_COMPARISON_SIDECAR,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
        )
        verify_atlas_comparison(temporary)
        publish_directory_exclusive(temporary, target)
        verify_atlas_comparison(target)
        return target
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def verify_atlas_comparison(directory: Path | str) -> dict[str, Any]:
    """Reverify both source runs and exactly recompute comparison outputs."""

    root = Path(directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise AtlasComparisonError(f"Atlas comparison is missing or symbolic: {root}")
    if any(path.is_symlink() or path.is_dir() for path in root.iterdir()):
        raise AtlasComparisonError("Atlas comparison contains a symbolic path or directory")
    manifest_path = root / ATLAS_COMPARISON_MANIFEST
    sidecar_path = root / ATLAS_COMPARISON_SIDECAR
    try:
        expected = sidecar_path.read_text(encoding="ascii").strip()
        manifest = load_strict_json_object(
            manifest_path.read_bytes(), manifest_path, label="Atlas comparison manifest"
        )
    except (ConfigurationError, OSError, UnicodeError) as error:
        raise AtlasComparisonError(f"Could not read atlas comparison manifest: {error}") from error
    if expected != sha256_file(manifest_path):
        raise AtlasComparisonError("Atlas comparison manifest SHA-256 differs")
    if manifest.get("artifact_version") != ATLAS_COMPARISON_VERSION:
        raise AtlasComparisonError("Atlas comparison version is unsupported")
    settings = manifest["settings"]
    payload, first, second = _comparison_payload(
        manifest["first_source"]["run_directory"],
        manifest["second_source"]["run_directory"],
        first_label=settings["first_label"],
        second_label=settings["second_label"],
        variance_target=float(settings["variance_target"]),
        created_at=manifest["created_at"],
    )
    if payload["sources"]["first"] != manifest["first_source"] or payload["sources"][
        "second"
    ] != manifest["second_source"]:
        raise AtlasComparisonError("Atlas comparison source identity changed")
    files = {
        ATLAS_COMPARISON_JSON: _canonical_json(payload),
        ATLAS_COMPARISON_HTML: _html_report(payload),
        ATLAS_COMPARISON_SUBJECTS: _subject_csv(
            first, second, settings["first_label"], settings["second_label"]
        ),
    }
    expected_records = [
        {
            "path": name,
            "bytes": len(content.encode("utf-8")),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
        for name, content in sorted(files.items())
    ]
    if manifest["artifacts"] != expected_records:
        raise AtlasComparisonError("Atlas comparison inventory differs from recomputation")
    expected_files = {
        ATLAS_COMPARISON_MANIFEST,
        ATLAS_COMPARISON_SIDECAR,
        *files,
    }
    if {path.name for path in root.iterdir()} != expected_files:
        raise AtlasComparisonError("Atlas comparison exact file inventory differs")
    for record in expected_records:
        path = root / record["path"]
        if (
            path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            raise AtlasComparisonError(f"Atlas comparison artifact changed: {path.name}")
    return payload

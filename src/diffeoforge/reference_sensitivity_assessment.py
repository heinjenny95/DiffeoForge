"""Recomputable neighboring-parameter sensitivity evidence for Validation Lab.

This module consumes only completed full-training runs that already belong to
one frozen Validation Lab study.  It never launches atlas optimization.
"""

from __future__ import annotations

import html
import json
import math
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from diffeoforge.analysis.pca import principal_component_analysis
from diffeoforge.analysis.pca_stability import compare_pca_stability
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.reference_pca import ReferenceMomentaInput, load_reference_momenta
from diffeoforge.reference_validation_study import (
    VALIDATION_EVENTS,
    VALIDATION_MANIFEST,
    ReferenceValidationStudySnapshot,
    load_reference_validation_study,
)
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

SENSITIVITY_ASSESSMENT_VERSION = "0.1"
SENSITIVITY_ASSESSMENT_JSON = "sensitivity-assessment.json"
SENSITIVITY_ASSESSMENT_SIDECAR = "sensitivity-assessment.sha256"
SENSITIVITY_ASSESSMENT_HTML = "sensitivity-assessment.html"
SCIENTIFIC_BOUNDARY = (
    "This assessment measures numerical stability across the frozen neighboring "
    "parameter finalists on the same training cohort. It does not establish a universal "
    "parameter optimum, biological meaning, taxonomic separation, or anatomical validity."
)
VERIFICATION_CONTRACT = (
    "The Validation Lab study, every selected full-training run, atlas template, momenta, "
    "control points, thresholds, and all reported comparisons are reverified and exactly "
    "recomputed. No atlas process is started."
)


class ReferenceSensitivityAssessmentError(RuntimeError):
    """Raised when a sensitivity assessment is incomplete or has changed."""


@dataclass(frozen=True)
class ReferenceSensitivityAssessmentArtifact:
    """One verified immutable sensitivity assessment."""

    artifact_directory: Path
    manifest: dict[str, Any]


def default_reference_sensitivity_directory(study_directory: Path | str) -> Path:
    """Return a sibling destination, leaving the Validation Lab study immutable."""

    study = Path(study_directory).expanduser().resolve()
    return study.parent / f"{study.name}-sensitivity"


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


def _unit_interval(name: str, value: float, *, inclusive_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReferenceSensitivityAssessmentError(f"{name} must be numeric")
    normalized = float(value)
    lower_ok = normalized >= 0.0 if inclusive_zero else normalized > 0.0
    if not math.isfinite(normalized) or not lower_ok or normalized > 1.0:
        interval = "[0, 1]" if inclusive_zero else "(0, 1]"
        raise ReferenceSensitivityAssessmentError(f"{name} must be finite and in {interval}")
    return normalized


def _full_training_runs(snapshot: ReferenceValidationStudySnapshot):
    runs = tuple(run for run in snapshot.runs if run.cohort_id == "training-confirmation")
    if len(runs) != len(snapshot.plan.finalists):
        raise ReferenceSensitivityAssessmentError(
            "Validation Lab does not contain exactly one full-training run per finalist"
        )
    if any(
        run.status != "completed"
        or run.run_directory is None
        or run.evidence is None
        or run.evidence.atlas_path is None
        or not run.evidence.subject_residual_p95
        for run in runs
    ):
        raise ReferenceSensitivityAssessmentError(
            "Every full-training finalist requires a completed run, atlas, and per-subject "
            "surface residuals"
        )
    return tuple(sorted(runs, key=lambda run: run.finalist_id))


def verified_atlas_from_momenta_input(
    inputs: ReferenceMomentaInput,
    atlas_path: str,
) -> tuple[Path, dict[str, Any]]:
    """Resolve an atlas only when it matches the run's verified output inventory."""

    atlas = Path(atlas_path).expanduser().resolve()
    output = (inputs.run_directory / "output").resolve()
    if atlas.is_symlink() or not atlas.is_file() or not atlas.is_relative_to(output):
        raise ReferenceSensitivityAssessmentError(
            f"Recorded estimated template is missing or outside the verified output: {atlas}"
        )
    relative = atlas.relative_to(output).as_posix()
    matches = [record for record in inputs.run_report.inventory if record["path"] == relative]
    if len(matches) != 1 or sha256_file(atlas) != matches[0]["sha256"]:
        raise ReferenceSensitivityAssessmentError(
            "Recorded estimated template does not match the verified output inventory"
        )
    return atlas, dict(matches[0])


def _run_source(run, inputs: ReferenceMomentaInput, atlas: Path, atlas_record) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "finalist_id": run.finalist_id,
        "run_directory": str(inputs.run_directory),
        "manifest_sha256": sha256_file(inputs.run_directory / "manifest.json"),
        "result_sha256": sha256_file(inputs.run_directory / "result.json"),
        "output_inventory_sha256": sha256_file(
            inputs.run_directory / "output-inventory.json"
        ),
        "atlas": {
            "path": str(atlas),
            "relative_output_path": PurePosixPath(str(atlas_record["path"])).as_posix(),
            "sha256": str(atlas_record["sha256"]),
        },
        "momenta_sha256": str(inputs.momenta_record["sha256"]),
        "control_points_sha256": str(inputs.control_points_record["sha256"]),
        "subject_count": len(inputs.subject_labels),
        "control_point_count": int(inputs.momenta.shape[1]),
        "subject_labels": list(inputs.subject_labels),
    }


def compare_ordered_atlas_templates(first: Path, second: Path) -> dict[str, float]:
    """Compare corresponding vertices of two verified same-topology atlas templates."""

    left = read_vtk_polydata(first)
    right = read_vtk_polydata(second)
    if left.triangles != right.triangles or len(left.vertices) != len(right.vertices):
        raise ReferenceSensitivityAssessmentError(
            "Neighboring estimated templates do not share ordered topology; direct "
            "template displacement is undefined"
        )
    displacement = np.linalg.norm(
        np.asarray(left.vertices, dtype=np.float64)
        - np.asarray(right.vertices, dtype=np.float64),
        axis=1,
    )
    return {
        "ordered_vertex_rms": float(np.sqrt(np.mean(displacement**2))),
        "ordered_vertex_p95": float(np.quantile(displacement, 0.95, method="linear")),
        "ordered_vertex_maximum": float(np.max(displacement)),
    }


def _outlier_names(run, fraction: float) -> tuple[str, ...]:
    values = tuple(run.evidence.subject_residual_p95)
    count = max(1, int(math.ceil(len(values) * fraction)))
    ranked = sorted(values, key=lambda item: (-item[1], item[0].casefold()))
    return tuple(name for name, _ in ranked[:count])


def _jaccard(first: tuple[str, ...], second: tuple[str, ...]) -> float:
    left = set(first)
    right = set(second)
    return float(len(left & right) / len(left | right))


def identity_bound_momenta_pca(inputs: ReferenceMomentaInput):
    """Fit momenta PCA while binding feature identity to exact control-point bytes."""

    control_hash = str(inputs.control_points_record["sha256"])
    feature_labels = tuple(
        f"momenta:control_point_{point:06d}:{axis}"
        for point in range(inputs.momenta.shape[1])
        for axis in ("x", "y", "z")
    )
    return principal_component_analysis(
        inputs.momenta.reshape(inputs.momenta.shape[0], -1),
        feature_space=f"subject_initial_momenta:control-points-sha256={control_hash}",
        feature_labels=feature_labels,
        sample_labels=inputs.subject_labels,
    )


def _search_boundary(snapshot: ReferenceValidationStudySnapshot) -> dict[str, object]:
    selected_id = snapshot.assessment.recommended_finalist_id
    if selected_id is None:
        return {
            "recommended_finalist_id": None,
            "at_tested_boundary": None,
            "parameters": [],
        }
    finalist_values = {item.finalist_id: item.values for item in snapshot.plan.finalists}
    selected = finalist_values[selected_id]
    parameters: list[dict[str, object]] = []
    for name in sorted(set.intersection(*(set(values) for values in finalist_values.values()))):
        observed = [float(values[name]) for values in finalist_values.values()]
        minimum = min(observed)
        maximum = max(observed)
        if math.isclose(minimum, maximum, rel_tol=1e-12, abs_tol=1e-15):
            continue
        value = float(selected[name])
        at_minimum = math.isclose(value, minimum, rel_tol=1e-12, abs_tol=1e-15)
        at_maximum = math.isclose(value, maximum, rel_tol=1e-12, abs_tol=1e-15)
        parameters.append(
            {
                "parameter": name,
                "selected": value,
                "tested_minimum": minimum,
                "tested_maximum": maximum,
                "location": (
                    "minimum" if at_minimum else "maximum" if at_maximum else "interior"
                ),
            }
        )
    return {
        "recommended_finalist_id": selected_id,
        "at_tested_boundary": any(
            item["location"] in {"minimum", "maximum"} for item in parameters
        ),
        "parameters": parameters,
    }


def _assessment_payload(
    study_directory: Path | str,
    *,
    template_margin_multiplier: float,
    outlier_fraction: float,
    minimum_outlier_jaccard: float,
    variance_target: float,
    minimum_pca_similarity: float,
    created_at: str,
) -> dict[str, object]:
    snapshot = load_reference_validation_study(study_directory)
    if snapshot.status != "completed" or snapshot.assessment is None:
        raise ReferenceSensitivityAssessmentError(
            "Sensitivity assessment requires a completed Validation Lab study"
        )
    if snapshot.report_json_path is None:
        raise ReferenceSensitivityAssessmentError("Validation Lab report is missing")
    if (
        isinstance(template_margin_multiplier, bool)
        or not isinstance(template_margin_multiplier, (int, float))
        or not math.isfinite(float(template_margin_multiplier))
        or float(template_margin_multiplier) <= 0.0
    ):
        raise ReferenceSensitivityAssessmentError(
            "template_margin_multiplier must be finite and positive"
        )
    outlier_fraction = _unit_interval("outlier_fraction", outlier_fraction)
    minimum_outlier_jaccard = _unit_interval(
        "minimum_outlier_jaccard", minimum_outlier_jaccard, inclusive_zero=True
    )
    variance_target = _unit_interval("variance_target", variance_target)
    minimum_pca_similarity = _unit_interval(
        "minimum_pca_similarity", minimum_pca_similarity, inclusive_zero=True
    )
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReferenceSensitivityAssessmentError(
            "created_at must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise ReferenceSensitivityAssessmentError("created_at must include a timezone offset")

    runs = _full_training_runs(snapshot)
    loaded: dict[str, ReferenceMomentaInput] = {}
    atlases: dict[str, Path] = {}
    sources: list[dict[str, object]] = []
    pcas = {}
    outliers = {}
    for run in runs:
        try:
            inputs = load_reference_momenta(run.run_directory)
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise ReferenceSensitivityAssessmentError(
                f"Could not verify full-training run {run.run_id}: {error}"
            ) from error
        if set(inputs.subject_labels) != set(snapshot.plan.training_subjects):
            raise ReferenceSensitivityAssessmentError(
                f"Full-training run {run.run_id} subjects differ from the frozen cohort"
            )
        atlas, atlas_record = verified_atlas_from_momenta_input(
            inputs, run.evidence.atlas_path
        )
        loaded[run.finalist_id] = inputs
        atlases[run.finalist_id] = atlas
        sources.append(_run_source(run, inputs, atlas, atlas_record))
        pcas[run.finalist_id] = identity_bound_momenta_pca(inputs)
        outliers[run.finalist_id] = _outlier_names(run, outlier_fraction)

    margin = float(snapshot.assessment.practical_error_margin) * float(
        template_margin_multiplier
    )
    diagonal = float(snapshot.plan.template_diagonal)
    pairwise: list[dict[str, object]] = []
    finalist_ids = sorted(loaded)
    for index, first_id in enumerate(finalist_ids):
        for second_id in finalist_ids[index + 1 :]:
            template = compare_ordered_atlas_templates(
                atlases[first_id], atlases[second_id]
            )
            pca = compare_pca_stability(
                pcas[first_id],
                pcas[second_id],
                variance_target=variance_target,
            )
            outlier_jaccard = _jaccard(outliers[first_id], outliers[second_id])
            template_p95 = float(template["ordered_vertex_p95"])
            pairwise.append(
                {
                    "first_finalist_id": first_id,
                    "second_finalist_id": second_id,
                    "template": {
                        **template,
                        "p95_fraction_of_template_diagonal": template_p95 / diagonal,
                        "within_declared_margin": template_p95 <= margin,
                    },
                    "high_residual_subjects": {
                        "selection_fraction": outlier_fraction,
                        "first": list(outliers[first_id]),
                        "second": list(outliers[second_id]),
                        "jaccard": outlier_jaccard,
                        "passes_engineering_gate": (
                            outlier_jaccard >= minimum_outlier_jaccard
                        ),
                    },
                    "pca_structure": {
                        **pca.as_manifest(),
                        "passes_engineering_gate": (
                            pca.score_linear_cka >= minimum_pca_similarity
                            and pca.score_distance_rank_correlation
                            >= minimum_pca_similarity
                        ),
                    },
                }
            )
    if not pairwise:
        raise ReferenceSensitivityAssessmentError(
            "Sensitivity assessment requires at least two distinct finalists"
        )

    template_pass = all(item["template"]["within_declared_margin"] for item in pairwise)
    outlier_pass = all(
        item["high_residual_subjects"]["passes_engineering_gate"] for item in pairwise
    )
    pca_pass = all(item["pca_structure"]["passes_engineering_gate"] for item in pairwise)
    boundary = _search_boundary(snapshot)
    robust_preference = snapshot.assessment.status == "robust_within_search_space"
    if not robust_preference:
        status = "inconclusive_parameter_preference"
    elif boundary["at_tested_boundary"]:
        status = "search_boundary_reached"
    elif template_pass and outlier_pass and pca_pass:
        status = "stable_within_tested_neighborhood"
    else:
        status = "sensitivity_detected"

    warnings: list[str] = []
    if not robust_preference:
        warnings.append(
            "The parent Validation Lab did not establish a unique robust finalist; "
            "pairwise stability metrics do not resolve that preference automatically."
        )
    if boundary["at_tested_boundary"]:
        warnings.append(
            "The preferred finalist lies on at least one tested parameter boundary; "
            "the search should be extended in that direction before claiming an interior optimum."
        )
    if not template_pass:
        warnings.append("At least one estimated-template difference exceeds the declared margin.")
    if not outlier_pass:
        warnings.append(
            "The high-residual inspection set changes materially between finalists."
        )
    if not pca_pass:
        warnings.append("At least one paired PCA structure comparison misses the engineering gate.")

    return {
        "artifact_version": SENSITIVITY_ASSESSMENT_VERSION,
        "created_at": created_at,
        "source": {
            "validation_study_directory": str(snapshot.study_directory),
            "study_id": snapshot.study_id,
            "plan_fingerprint": snapshot.plan.fingerprint,
            "validation_manifest_sha256": sha256_file(
                snapshot.study_directory / VALIDATION_MANIFEST
            ),
            "validation_events_sha256": sha256_file(
                snapshot.study_directory / VALIDATION_EVENTS
            ),
            "validation_report_sha256": sha256_file(snapshot.report_json_path),
            "parent_assessment_status": snapshot.assessment.status,
            "parent_recommended_finalist_id": (
                snapshot.assessment.recommended_finalist_id
            ),
            "training_subject_count": len(snapshot.plan.training_subjects),
            "runs": sources,
        },
        "thresholds": {
            "template_ordered_vertex_p95_margin": margin,
            "template_margin_multiplier": float(template_margin_multiplier),
            "template_margin_basis": snapshot.assessment.practical_error_margin_basis,
            "outlier_fraction": outlier_fraction,
            "minimum_outlier_jaccard": minimum_outlier_jaccard,
            "pca_variance_target": variance_target,
            "minimum_pca_score_similarity": minimum_pca_similarity,
            "threshold_scope": (
                "Predeclared numerical engineering gates; they are not biological effect-size "
                "thresholds or automatic specimen-exclusion rules."
            ),
        },
        "status": status,
        "gates": {
            "templates_stable": template_pass,
            "high_residual_subjects_stable": outlier_pass,
            "pca_structure_stable": pca_pass,
            "robust_parent_parameter_preference": robust_preference,
            "preferred_parameter_at_tested_boundary": boundary["at_tested_boundary"],
        },
        "search_boundary": boundary,
        "pairwise_comparisons": pairwise,
        "warnings": warnings,
        "next_step": (
            "Extend the frozen parameter search beyond the selected boundary, then repeat "
            "the same assessment."
            if boundary["at_tested_boundary"]
            else "Retain these metrics with the final atlas report and proceed to the next "
            "independent validation gate."
        ),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "verification_contract": VERIFICATION_CONTRACT,
    }


def _render_html(report: dict[str, Any]) -> str:
    gate_rows = "".join(
        "<tr>"
        f"<td>{html.escape(name.replace('_', ' '))}</td>"
        f"<td>{html.escape(str(value))}</td>"
        "</tr>"
        for name, value in report["gates"].items()
    )
    comparison_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['first_finalist_id'])} vs "
        f"{html.escape(item['second_finalist_id'])}</td>"
        f"<td>{item['template']['ordered_vertex_p95']:.6g}</td>"
        f"<td>{item['high_residual_subjects']['jaccard']:.3f}</td>"
        f"<td>{item['pca_structure']['score_linear_cka']:.3f}</td>"
        f"<td>{item['pca_structure']['score_distance_rank_correlation']:.3f}</td>"
        "</tr>"
        for item in report["pairwise_comparisons"]
    )
    warning_items = "".join(
        f"<li>{html.escape(item)}</li>" for item in report["warnings"]
    ) or "<li>No additional numerical warning was triggered.</li>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DiffeoForge sensitivity assessment</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:36px auto;
padding:0 24px;color:#103b3b;line-height:1.45}}h1,h2{{color:#073c3b}}
.notice{{background:#e3f6ef;border-left:5px solid #13856f;padding:14px 18px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #c8d9d7;
padding:10px;text-align:left;vertical-align:top}}th{{background:#eef5f4}}</style></head><body>
<h1>DiffeoForge neighboring-parameter sensitivity</h1>
<p class="notice"><strong>Status:</strong> {html.escape(report['status'])}<br>
{html.escape(report['scientific_boundary'])}</p>
<h2>Decision gates</h2><table><tbody>{gate_rows}</tbody></table>
<h2>Full-training pairwise comparisons</h2><table><thead><tr><th>Finalists</th>
<th>Template p95</th><th>High-residual Jaccard</th><th>PCA CKA</th>
<th>PCA distance rank correlation</th></tr></thead><tbody>{comparison_rows}</tbody></table>
<h2>Warnings</h2><ul>{warning_items}</ul>
<h2>Next step</h2><p>{html.escape(report['next_step'])}</p></body></html>"""


def write_reference_sensitivity_assessment(
    study_directory: Path | str,
    destination: Path | str | None = None,
    *,
    template_margin_multiplier: float = 1.0,
    outlier_fraction: float = 0.10,
    minimum_outlier_jaccard: float = 0.50,
    variance_target: float = 0.90,
    minimum_pca_similarity: float = 0.95,
    created_at: str | None = None,
) -> ReferenceSensitivityAssessmentArtifact:
    """Atomically assess existing runs without launching new atlas work."""

    target = (
        default_reference_sensitivity_directory(study_directory)
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    if target.exists():
        raise FileExistsError(f"Sensitivity assessment destination exists: {target}")
    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    report = _assessment_payload(
        study_directory,
        template_margin_multiplier=template_margin_multiplier,
        outlier_fraction=outlier_fraction,
        minimum_outlier_jaccard=minimum_outlier_jaccard,
        variance_target=variance_target,
        minimum_pca_similarity=minimum_pca_similarity,
        created_at=timestamp,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        manifest_path = temporary / SENSITIVITY_ASSESSMENT_JSON
        write_text_safely(manifest_path, _canonical_json(report), overwrite=False)
        write_text_safely(
            temporary / SENSITIVITY_ASSESSMENT_SIDECAR,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
        )
        write_text_safely(
            temporary / SENSITIVITY_ASSESSMENT_HTML,
            _render_html(report),
            overwrite=False,
        )
        verify_reference_sensitivity_assessment(temporary)
        publish_directory_exclusive(temporary, target)
        return verify_reference_sensitivity_assessment(target)
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def verify_reference_sensitivity_assessment(
    artifact_directory: Path | str,
) -> ReferenceSensitivityAssessmentArtifact:
    """Reverify source studies and exactly recompute every sensitivity metric."""

    root = Path(artifact_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ReferenceSensitivityAssessmentError(
            f"Sensitivity assessment is missing or symbolic: {root}"
        )
    expected_files = {
        SENSITIVITY_ASSESSMENT_JSON,
        SENSITIVITY_ASSESSMENT_SIDECAR,
        SENSITIVITY_ASSESSMENT_HTML,
    }
    if {path.name for path in root.iterdir()} != expected_files or any(
        not path.is_file() or path.is_symlink() for path in root.iterdir()
    ):
        raise ReferenceSensitivityAssessmentError(
            "Sensitivity assessment contains an unexpected or symbolic artifact"
        )
    manifest_path = root / SENSITIVITY_ASSESSMENT_JSON
    sidecar_path = root / SENSITIVITY_ASSESSMENT_SIDECAR
    try:
        expected_digest = sidecar_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise ReferenceSensitivityAssessmentError(
            "Could not read sensitivity assessment sidecar"
        ) from error
    if expected_digest != sha256_file(manifest_path):
        raise ReferenceSensitivityAssessmentError("Sensitivity assessment SHA-256 differs")
    try:
        manifest = load_strict_json_object(
            manifest_path.read_bytes(),
            manifest_path,
            label="Sensitivity assessment",
        )
    except (ConfigurationError, OSError) as error:
        raise ReferenceSensitivityAssessmentError(str(error)) from error
    required = {
        "artifact_version",
        "created_at",
        "source",
        "thresholds",
        "status",
        "gates",
        "search_boundary",
        "pairwise_comparisons",
        "warnings",
        "next_step",
        "scientific_boundary",
        "verification_contract",
    }
    if set(manifest) != required:
        raise ReferenceSensitivityAssessmentError("Sensitivity assessment fields differ")
    if manifest["artifact_version"] != SENSITIVITY_ASSESSMENT_VERSION:
        raise ReferenceSensitivityAssessmentError(
            f"Unsupported sensitivity assessment version: {manifest['artifact_version']}"
        )
    if (
        manifest["scientific_boundary"] != SCIENTIFIC_BOUNDARY
        or manifest["verification_contract"] != VERIFICATION_CONTRACT
    ):
        raise ReferenceSensitivityAssessmentError(
            "Sensitivity claim boundary or verification contract differs"
        )
    source = manifest["source"]
    thresholds = manifest["thresholds"]
    if not isinstance(source, dict) or not isinstance(thresholds, dict):
        raise ReferenceSensitivityAssessmentError(
            "Sensitivity source and thresholds must be objects"
        )
    recomputed = _assessment_payload(
        str(source["validation_study_directory"]),
        template_margin_multiplier=float(thresholds["template_margin_multiplier"]),
        outlier_fraction=float(thresholds["outlier_fraction"]),
        minimum_outlier_jaccard=float(thresholds["minimum_outlier_jaccard"]),
        variance_target=float(thresholds["pca_variance_target"]),
        minimum_pca_similarity=float(thresholds["minimum_pca_score_similarity"]),
        created_at=str(manifest["created_at"]),
    )
    if manifest != recomputed:
        raise ReferenceSensitivityAssessmentError(
            "Sensitivity assessment differs from exact source recomputation"
        )
    expected_html = _render_html(recomputed)
    try:
        actual_html = (root / SENSITIVITY_ASSESSMENT_HTML).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ReferenceSensitivityAssessmentError(
            "Could not read sensitivity assessment HTML"
        ) from error
    if actual_html != expected_html:
        raise ReferenceSensitivityAssessmentError("Sensitivity assessment HTML differs")
    return ReferenceSensitivityAssessmentArtifact(root, dict(manifest))

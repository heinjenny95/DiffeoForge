"""Evidence-bound scientific completion reports for verified atlas results.

The report composes existing DiffeoForge evidence.  It never turns a completed
optimizer, a low residual, or a stable PCA into an automatic biological claim.
"""

from __future__ import annotations

import base64
import csv
import html
import json
import math
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any, Literal

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.desktop.reference_result_review import (
    load_finalized_registration_qc_review,
    review_reference_result,
)
from diffeoforge.desktop.result_review import (
    ModernResultReview,
    ModernResultReviewError,
    review_modern_result,
    verify_result_artifact,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_holdout_study import load_reference_holdout_study
from diffeoforge.reference_pca_stability import (
    REFERENCE_PCA_STABILITY_MANIFEST,
    verify_reference_pca_stability,
)
from diffeoforge.reference_sensitivity_assessment import (
    SENSITIVITY_ASSESSMENT_JSON,
    verify_reference_sensitivity_assessment,
)
from diffeoforge.reference_template_robustness import (
    load_reference_template_robustness_study,
)
from diffeoforge.reference_validation_study import load_reference_validation_study
from diffeoforge.registration_screening import inspection_threshold as _inspection_threshold
from diffeoforge.runs import publish_directory_exclusive

SCIENTIFIC_REPORT_VERSION = "0.1"
SCIENTIFIC_REPORT_MANIFEST = "scientific-report-manifest.json"
SCIENTIFIC_REPORT_SIDECAR = "scientific-report-manifest.sha256"
SCIENTIFIC_REPORT_JSON = "scientific-report.json"
SCIENTIFIC_REPORT_HTML = "scientific-report.html"
SCIENTIFIC_METHODS_TEXT = "methods.txt"
SCIENTIFIC_SUBJECTS_CSV = "subject-qc.csv"
SCIENTIFIC_CLAIMS_CSV = "claim-matrix.csv"
SCIENTIFIC_DECISIONS_CSV = "user-decisions.csv"

ClaimStatus = Literal["supported", "partial", "not_assessed", "not_supported"]


class ScientificReportError(RuntimeError):
    """Raised when source evidence is missing, inconsistent, or unsafe."""


@dataclass(frozen=True)
class SubjectQC:
    """Descriptive registration evidence for one subject."""

    rank: int
    subject: str
    residual: float
    inspection_priority: bool
    threshold: float | None
    researcher_decision: str

    def as_manifest(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "subject": self.subject,
            "residual": self.residual,
            "inspection_priority": self.inspection_priority,
            "threshold": self.threshold,
            "researcher_decision": self.researcher_decision,
        }


@dataclass(frozen=True)
class ScientificClaim:
    """One bounded statement and the evidence that does or does not support it."""

    claim_id: str
    label: str
    status: ClaimStatus
    evidence: str
    boundary: str

    def as_manifest(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "label": self.label,
            "status": self.status,
            "evidence": self.evidence,
            "boundary": self.boundary,
        }


@dataclass(frozen=True)
class ScientificAtlasReport:
    """Complete in-memory report derived from already verified evidence."""

    created_at: str
    review: ModernResultReview
    effective_config: Mapping[str, Any]
    subjects: tuple[SubjectQC, ...]
    decisions: tuple[tuple[str, str], ...]
    claims: tuple[ScientificClaim, ...]
    sensitivity: Mapping[str, Any] | None
    template_robustness: Mapping[str, Any] | None
    holdout: Mapping[str, Any] | None
    pca_stability: Mapping[str, Any] | None
    evidence_sources: tuple[tuple[str, Path, str], ...]
    methods_text: str

    @property
    def engine_label(self) -> str:
        return (
            "Deformetrica reference"
            if self.review.engine_route == "deformetrica_reference"
            else "DiffeoForge Modern Engine"
        )

    @property
    def residual_metric(self) -> str:
        return (
            "symmetric nearest-vertex residual p95"
            if self.review.engine_route == "deformetrica_reference"
            else "final manifested subject residual"
        )

    def as_manifest(self) -> dict[str, object]:
        return {
            "report_version": SCIENTIFIC_REPORT_VERSION,
            "created_at": self.created_at,
            "project": self.review.project_name,
            "engine": {
                "route": self.review.engine_route,
                "label": self.engine_label,
            },
            "source_run": {
                "directory": str(self.review.run_directory),
                "workflow_manifest": str(self.review.workflow_manifest_path),
                "workflow_manifest_sha256": self.review.workflow_manifest_sha256,
                "analysis_manifest": str(self.review.bundle_manifest_path),
                "analysis_manifest_sha256": self.review.bundle_manifest_sha256,
            },
            "technical_summary": {
                "optimizer_converged": self.review.optimizer_converged,
                "termination_reason": self.review.optimizer_termination_reason,
                "completed_cycles_or_iterations": self.review.optimizer_cycles_completed,
                "configured_maximum": self.review.optimizer_max_cycles,
                "execution_duration_seconds": self.review.execution_duration_seconds,
                "stop_interpretation": self.review.optimizer_stop_interpretation,
            },
            "shape_space_method": {
                "method_id": self.review.pca_method_id,
                "label": self.review.pca_method_label,
                "generic_rbf_kernel_pca": False,
            },
            "registration_qc": {
                "metric": self.residual_metric,
                "subject_count": len(self.subjects),
                "inspection_priority_count": sum(
                    item.inspection_priority for item in self.subjects
                ),
                "researcher_reviewed_count": sum(
                    item.researcher_decision != "unreviewed" for item in self.subjects
                ),
                "unreviewed_count": sum(
                    item.researcher_decision == "unreviewed" for item in self.subjects
                ),
                "scientific_boundary": (
                    "The robust upper-tail rule prioritizes visual inspection. It is not an "
                    "automatic biological outlier or exclusion rule. Residual values from "
                    "different engine objectives are not assumed to share a scale. Unflagged, "
                    "unreviewed specimens are not counted as visually approved. A relative "
                    "screen can miss uniformly poor fits."
                ),
                "subjects": [item.as_manifest() for item in self.subjects],
            },
            "user_decisions": dict(self.decisions),
            "sensitivity": self.sensitivity,
            "template_robustness": self.template_robustness,
            "fixed_template_holdout": self.holdout,
            "pca_stability": self.pca_stability,
            "claim_matrix": [claim.as_manifest() for claim in self.claims],
            "methods_text": self.methods_text,
            "scientific_boundaries": list(self.review.scientific_boundaries),
            "evidence_sources": [
                {"role": role, "path": str(path), "sha256": digest}
                for role, path, digest in self.evidence_sources
            ],
        }


@dataclass(frozen=True)
class ScientificReportArtifact:
    """One written report directory and its verified manifest."""

    directory: Path
    manifest: Mapping[str, Any]


def default_scientific_report_directory(run_directory: Path | str) -> Path:
    """Return a sibling destination so immutable Modern runs remain untouched."""

    run = Path(run_directory).expanduser().resolve()
    return run.parent / f"{run.name}-scientific-report"


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


def _review_atlas(run_directory: Path | str) -> ModernResultReview:
    run = Path(run_directory).expanduser().resolve()
    try:
        from diffeoforge.modern_workflow import MANIFEST_NAME as modern_manifest

        if (run / modern_manifest).is_file():
            return review_modern_result(run)
        return review_reference_result(run, create_pca_if_missing=False)
    except (OSError, RuntimeError, TypeError, ValueError, ModernResultReviewError) as error:
        raise ScientificReportError(f"Atlas result did not verify: {error}") from error


def _safe_run_file(review: ModernResultReview, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ScientificReportError(f"{label} path is not a safe POSIX-style path")
    relative = Path(value)
    if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
        raise ScientificReportError(f"{label} path is unsafe")
    path = review.run_directory.joinpath(*relative.parts)
    try:
        path.resolve().relative_to(review.run_directory)
    except ValueError as error:
        raise ScientificReportError(f"{label} escapes the verified run") from error
    if path.is_symlink() or not path.is_file():
        raise ScientificReportError(f"{label} is absent or symbolic")
    return path


def _effective_config(review: ModernResultReview) -> dict[str, Any]:
    try:
        workflow = json.loads(review.workflow_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScientificReportError("Could not reread the verified workflow manifest") from error
    if review.engine_route == "deformetrica_reference":
        config = workflow.get("effective_config")
    else:
        config_record = workflow.get("config")
        if not isinstance(config_record, Mapping):
            raise ScientificReportError("Modern workflow has no configuration record")
        config_path = _safe_run_file(
            review,
            config_record.get("effective_path"),
            label="Effective configuration",
        )
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ScientificReportError("Effective Modern configuration is unreadable") from error
    if not isinstance(config, dict):
        raise ScientificReportError("Verified run does not expose an effective configuration")
    return config


def _residuals(review: ModernResultReview) -> tuple[tuple[str, float], ...]:
    if review.registration_qc:
        return tuple((item.subject_name, item.residual_p95) for item in review.registration_qc)
    try:
        bundle = json.loads(review.bundle_manifest_path.read_text(encoding="utf-8"))
        values = tuple((str(item["label"]), float(item["residual"])) for item in bundle["subjects"])
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ScientificReportError("Subject residual evidence is unreadable") from error
    if not values or any(not math.isfinite(value) or value < 0 for _, value in values):
        raise ScientificReportError("Subject residual evidence is empty or non-finite")
    return values


def _load_decisions(
    review: ModernResultReview,
    decision_review: Path | str | None,
) -> tuple[dict[str, str], tuple[str, Path, str] | None]:
    if decision_review is None:
        try:
            finalized = load_finalized_registration_qc_review(review)
        except ModernResultReviewError as error:
            raise ScientificReportError(str(error)) from error
        if finalized is None:
            return {}, None
        source = finalized.path
    else:
        source = Path(decision_review).expanduser().resolve()
    if source.is_symlink() or not source.is_file():
        raise ScientificReportError(f"Decision review is missing or symbolic: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        bound = payload["source"]
        subjects = payload["subjects"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise ScientificReportError("Decision review is unreadable or incomplete") from error
    if not isinstance(bound, Mapping) or (
        bound.get("run_manifest_sha256") != review.workflow_manifest_sha256
        or bound.get("analysis_manifest_sha256") != review.bundle_manifest_sha256
    ):
        raise ScientificReportError("Decision review belongs to different atlas evidence")
    if not isinstance(subjects, list):
        raise ScientificReportError("Decision review subject records are invalid")
    decisions: dict[str, str] = {}
    for item in subjects:
        if not isinstance(item, Mapping):
            raise ScientificReportError("Decision review subject record is invalid")
        name = item.get("subject_name")
        decision = item.get("decision")
        if not isinstance(name, str) or decision not in {"pass", "uncertain", "fail", "unreviewed"}:
            raise ScientificReportError("Decision review contains an invalid decision")
        if name in decisions:
            raise ScientificReportError("Decision review contains a duplicate subject")
        decisions[name] = str(decision)
    return decisions, ("registration_qc_review", source, sha256_file(source))


def _parameter_values(config: Mapping[str, Any]) -> dict[str, float]:
    try:
        model = config["model"]
        attachment = model["attachment"]
        deformation = model["deformation"]
        values = {
            "attachment_kernel_width": float(attachment["kernel_width"]),
            "deformation_kernel_width": float(deformation["kernel_width"]),
            "timepoints": float(deformation["timepoints"]),
        }
        if "initial_control_point_spacing" in deformation:
            values["initial_control_point_spacing"] = float(
                deformation["initial_control_point_spacing"]
            )
        if "noise_std" in model:
            values["noise_std"] = float(model["noise_std"])
        elif "noise_variance" in model:
            values["noise_variance"] = float(model["noise_variance"])
    except (KeyError, TypeError, ValueError) as error:
        raise ScientificReportError("Effective model parameters are incomplete") from error
    return values


def _matches_finalist(config: Mapping[str, Any], expected: Mapping[str, float]) -> bool:
    actual = _parameter_values(config)
    return all(
        key in actual and math.isclose(actual[key], float(value), rel_tol=1e-12, abs_tol=1e-15)
        for key, value in expected.items()
    )


def _validation_evidence(
    directory: Path | str | None,
    config: Mapping[str, Any],
    sensitivity_assessment: Path | str | None = None,
) -> tuple[dict[str, Any] | None, tuple[tuple[str, Path, str], ...]]:
    detailed = None
    detailed_source = None
    if sensitivity_assessment is not None:
        artifact = verify_reference_sensitivity_assessment(sensitivity_assessment)
        detailed = artifact.manifest
        detailed_source = artifact.artifact_directory / SENSITIVITY_ASSESSMENT_JSON
        detailed_study = Path(
            str(detailed["source"]["validation_study_directory"])
        ).resolve()
        if directory is None:
            directory = detailed_study
        elif Path(directory).expanduser().resolve() != detailed_study:
            raise ScientificReportError(
                "Sensitivity assessment is not bound to the supplied Validation Lab study"
            )
    if directory is None:
        return None, ()
    snapshot = load_reference_validation_study(directory)
    assessment = snapshot.assessment
    if snapshot.status != "completed" or assessment is None or snapshot.report_json_path is None:
        raise ScientificReportError("Sensitivity study is not complete")
    selected = next(
        (
            item
            for item in snapshot.plan.finalists
            if item.finalist_id == assessment.recommended_finalist_id
        ),
        None,
    )
    matches = selected is not None and _matches_finalist(config, selected.values)
    if detailed is not None and detailed["source"]["study_id"] != snapshot.study_id:
        raise ScientificReportError(
            "Sensitivity assessment study identity differs from the Validation Lab"
        )
    value = {
        "study_id": snapshot.study_id,
        "status": assessment.status,
        "recommended_finalist_id": assessment.recommended_finalist_id,
        "winner_support": assessment.winner_support,
        "confidence": assessment.confidence,
        "final_atlas_matches_recommendation": matches,
        "warnings": list(assessment.warnings),
        "remaining_gates": list(assessment.next_gates),
        "automatic_assessment": (
            None
            if detailed is None
            else {
                "status": detailed["status"],
                "gates": detailed["gates"],
                "search_boundary": detailed["search_boundary"],
                "pairwise_comparison_count": len(detailed["pairwise_comparisons"]),
                "warnings": detailed["warnings"],
                "next_step": detailed["next_step"],
            }
        ),
        "claim_boundary": (
            "Stability is limited to the frozen finalist search space and cohorts. "
            "It is not a universal parameter optimum."
        ),
    }
    source = snapshot.report_json_path
    sources = [("sensitivity_study", source, sha256_file(source))]
    if detailed_source is not None:
        sources.append(
            (
                "automatic_sensitivity_assessment",
                detailed_source,
                sha256_file(detailed_source),
            )
        )
    return value, tuple(sources)


def _holdout_evidence(
    directory: Path | str | None,
    sensitivity: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, tuple[str, Path, str] | None]:
    if directory is None:
        return None, None
    snapshot = load_reference_holdout_study(directory)
    assessment = snapshot.assessment
    if snapshot.status != "completed" or assessment is None or snapshot.report_json_path is None:
        raise ScientificReportError("Fixed-template holdout study is not complete")
    if sensitivity is not None and snapshot.parent_study_id != sensitivity["study_id"]:
        raise ScientificReportError("Holdout study is not bound to the supplied sensitivity study")
    value = {
        "study_id": snapshot.study_id,
        "parent_study_id": snapshot.parent_study_id,
        "status": assessment.status,
        "preferred_finalist_id": assessment.preferred_finalist_id,
        "subject_support": assessment.subject_support,
        "subject_count": assessment.subject_count,
        "agrees_with_training_preference": assessment.agrees_with_training_preference,
        "warnings": list(assessment.warnings),
        "remaining_gates": list(assessment.next_gates),
        "claim_boundary": (
            "Fixed-template heldout registration is out-of-sample geometric evidence. "
            "It is not proof of biological validity or a universal optimum."
        ),
    }
    source = snapshot.report_json_path
    return value, ("fixed_template_holdout", source, sha256_file(source))


def _template_robustness_evidence(
    directory: Path | str | None,
) -> tuple[dict[str, Any] | None, tuple[str, Path, str] | None]:
    if directory is None:
        return None, None
    snapshot = load_reference_template_robustness_study(directory)
    if (
        snapshot.status != "completed"
        or snapshot.assessment is None
        or snapshot.report_json_path is None
    ):
        raise ScientificReportError("Multi-start template-robustness study is not complete")
    assessment = snapshot.assessment
    value = {
        "study_id": snapshot.study_id,
        "status": assessment["status"],
        "arm_count": assessment["arm_count"],
        "subject_count": assessment["subject_count"],
        "gates": assessment["gates"],
        "warnings": assessment["warnings"],
        "next_step": assessment["next_step"],
        "claim_boundary": assessment["claim_scope"],
    }
    source = snapshot.report_json_path
    return value, ("template_robustness", source, sha256_file(source))


def _pca_stability_evidence(
    directory: Path | str | None,
) -> tuple[dict[str, Any] | None, tuple[str, Path, str] | None]:
    if directory is None:
        return None, None
    root = Path(directory).expanduser().resolve()
    if (root / REFERENCE_PCA_STABILITY_MANIFEST).is_file():
        artifact = verify_reference_pca_stability(root)
    else:
        from diffeoforge.modern_pca_stability import (  # local optional-heavy import
            MODERN_PCA_STABILITY_MANIFEST,
            verify_modern_pca_stability,
        )

        if not (root / MODERN_PCA_STABILITY_MANIFEST).is_file():
            raise ScientificReportError("PCA stability artifact type is not recognized")
        artifact = verify_modern_pca_stability(root)
    evidence = artifact.evidence
    value = {
        "score_linear_cka": evidence.score_linear_cka,
        "score_distance_rank_correlation": evidence.score_distance_rank_correlation,
        "reference_component_count": evidence.reference_component_count,
        "comparison_component_count": evidence.comparison_component_count,
        "variance_target": evidence.variance_target,
        "feature_subspace_available": evidence.feature_subspace_available,
        "minimum_principal_cosine": evidence.minimum_principal_cosine,
        "rms_principal_sine": evidence.rms_principal_sine,
        "limitations": list(evidence.limitations),
        "claim_boundary": (
            "PCA stability describes reproducibility of fitted numerical shape structure, "
            "not biological meaning or group separation."
        ),
    }
    manifest_path = next(root.glob("*pca-stability.json"))
    return value, ("pca_stability", manifest_path, sha256_file(manifest_path))


def _methods(review: ModernResultReview, config: Mapping[str, Any]) -> str:
    model = config["model"]
    attachment = model["attachment"]
    deformation = model["deformation"]
    optimization = config["optimization"]
    preprocessing = config.get("preprocessing", {})
    procrustes = preprocessing.get("procrustes", {}) if isinstance(preprocessing, Mapping) else {}
    dataset = next((item.value for item in review.overview if item.label == "Dataset"), "unknown")
    engine = next(
        (item.value for item in review.overview if item.label == "Engine"),
        review.engine_route,
    )
    optimizer_method = optimization.get("method", "block-coordinate optimization")
    pca_method = review.pca_method_label
    noise = (
        f"noise standard deviation {float(model['noise_std']):g}"
        if "noise_std" in model
        else f"noise variance {float(model['noise_variance']):g}"
    )
    if "procrustes" not in preprocessing:
        gpa_text = (
            "Pre-alignment provenance was not represented in this atlas-run configuration; "
            "any landmarks used upstream were not used as an atlas attachment term."
        )
    elif bool(procrustes.get("enabled", False)):
        scaling_mode = procrustes.get("scaling_mode")
        if isinstance(scaling_mode, str):
            scaling_descriptions = {
                "pams_surface_area_weighted_rms": (
                    "specimen size was removed from each complete surface using its "
                    "area-weighted RMS radius"
                ),
                "pams_surface_vertex_centroid_size": (
                    "specimen size was removed using complete-surface vertex centroid "
                    "size, matching the published PAMS definition"
                ),
                "preserve_size": "complete-surface specimen size was preserved",
                "landmark_centroid_size_legacy": (
                    "specimen size was removed using landmark centroid size (legacy mode)"
                ),
                "landmark_rigid_gpa_legacy": (
                    "specimen size was preserved using the legacy rigid-GPA route"
                ),
            }
            scaling_text = scaling_descriptions.get(
                scaling_mode, f"the declared scaling mode was {scaling_mode}"
            )
            gpa_text = (
                "Homologous landmarks determined translation and orientation during "
                f"pre-alignment; {scaling_text}. Landmarks were not used as an atlas "
                "attachment term."
            )
        else:
            gpa_text = (
                "Generalized Procrustes pre-alignment was enabled; its landmarks were "
                "used only for pre-alignment and not as an atlas attachment term."
            )
    else:
        gpa_text = (
            "Generalized Procrustes pre-alignment was disabled, and no landmark atlas "
            "attachment term was used."
        )
    return (
        f"A deterministic surface atlas was fitted in DiffeoForge using {engine} to {dataset}. "
        f"The attachment was {attachment['type']} with kernel width "
        f"{float(attachment['kernel_width']):g}; deformation kernel width was "
        f"{float(deformation['kernel_width']):g} with {int(deformation['timepoints'])} "
        f"time points and {noise}. {gpa_text} Optimization used {optimizer_method}. "
        "Subject shape variation was summarized using "
        f"{pca_method} of subject-specific initial momenta. "
        "Registration quality was assessed from verified surface reconstructions; residual "
        "ranking was used only to prioritize visual inspection."
    )


def _claim_matrix(
    review: ModernResultReview,
    subjects: tuple[SubjectQC, ...],
    decisions: Mapping[str, str],
    sensitivity: Mapping[str, Any] | None,
    template_robustness: Mapping[str, Any] | None,
    holdout: Mapping[str, Any] | None,
    pca_stability: Mapping[str, Any] | None,
) -> tuple[ScientificClaim, ...]:
    if review.optimizer_converged is True:
        optimizer_status: ClaimStatus = "supported"
        optimizer_evidence = "The Modern optimizer recorded its convergence criterion."
    elif review.optimizer_converged is False:
        optimizer_status = "not_supported"
        optimizer_evidence = "The atlas completed but the Modern convergence criterion was not met."
    else:
        optimizer_status = "partial"
        optimizer_evidence = (
            review.optimizer_stop_interpretation
            or "The external engine completed; exact optimizer convergence is not established."
        )
    reviewed = sum(value != "unreviewed" for value in decisions.values())
    registration_status: ClaimStatus = (
        "supported" if subjects and reviewed == len(subjects) else "partial"
    )
    sensitivity_status: ClaimStatus = "not_assessed"
    sensitivity_evidence = "No verified neighboring-parameter study was supplied."
    if sensitivity is not None:
        automatic = sensitivity["automatic_assessment"]
        sensitivity_status = "partial"
        if (
            sensitivity["status"] == "robust_within_search_space"
            and sensitivity["final_atlas_matches_recommendation"]
            and automatic is not None
            and automatic["status"] == "stable_within_tested_neighborhood"
        ):
            sensitivity_status = "supported"
        sensitivity_evidence = (
            f"Validation Lab status {sensitivity['status']}; winner support "
            f"{sensitivity['winner_support']}; final-atlas parameter match="
            f"{sensitivity['final_atlas_matches_recommendation']}; automatic assessment="
            f"{None if automatic is None else automatic['status']}."
        )
    holdout_status: ClaimStatus = "not_assessed"
    holdout_evidence = "No verified fixed-template heldout study was supplied."
    if holdout is not None:
        holdout_status = "supported" if holdout["status"] == "confirmed_on_holdout" else "partial"
        holdout_evidence = (
            f"Holdout status {holdout['status']} on {holdout['subject_count']} subjects; "
            f"paired support {holdout['subject_support']}."
        )
    pca_status: ClaimStatus = "not_assessed" if pca_stability is None else "partial"
    pca_evidence = (
        "No verified paired PCA stability artifact was supplied."
        if pca_stability is None
        else (
            f"Score linear CKA {pca_stability['score_linear_cka']:.6g}; score-distance "
            f"rank correlation {pca_stability['score_distance_rank_correlation']:.6g}. "
            "No universal pass threshold was imposed."
        )
    )
    return (
        ScientificClaim(
            "execution_integrity",
            "Run execution and artifact integrity",
            "supported",
            "The atlas and analysis manifests were independently reverified.",
            "Integrity does not establish scientific validity.",
        ),
        ScientificClaim(
            "optimizer_convergence",
            "Optimizer convergence",
            optimizer_status,
            optimizer_evidence,
            "Convergence of the numerical objective is not biological validation.",
        ),
        ScientificClaim(
            "registration_quality",
            "Full-cohort registration plausibility",
            registration_status,
            f"{len(subjects)} subject residuals; {reviewed} explicit researcher decisions.",
            "Residual rank is an inspection aid, not an exclusion rule.",
        ),
        ScientificClaim(
            "parameter_sensitivity",
            "Robustness to neighboring parameters",
            sensitivity_status,
            sensitivity_evidence,
            "Any support is limited to the predeclared tested search space.",
        ),
        ScientificClaim(
            "heldout_generalization",
            "Fixed-template heldout generalization",
            holdout_status,
            holdout_evidence,
            "Heldout geometric fit is not anatomy-specific biological validation.",
        ),
        ScientificClaim(
            "pca_stability",
            "PCA structure stability",
            pca_status,
            pca_evidence,
            "Stable numerical axes do not acquire biological meaning automatically.",
        ),
        ScientificClaim(
            "template_robustness",
            "Robustness to starting template or bootstrap atlas",
            (
                "not_assessed"
                if template_robustness is None
                else (
                    "supported"
                    if template_robustness["status"]
                    == "stable_across_tested_start_templates"
                    else "partial"
                )
            ),
            (
                "No verified multi-start or bootstrap-template study was supplied."
                if template_robustness is None
                else (
                    f"Multi-start status {template_robustness['status']} across "
                    f"{template_robustness['arm_count']} initial templates."
                )
            ),
            "This report does not infer template independence from parameter sensitivity.",
        ),
        ScientificClaim(
            "biological_validity",
            "Independent study-specific validity",
            "not_assessed",
            "No independent study-specific evidence is part of this numerical atlas report.",
            "GPA landmarks and downstream measurements are not atlas validation data unless "
            "a separate validation design establishes that role.",
        ),
    )


def collect_scientific_atlas_report(
    run_directory: Path | str,
    *,
    validation_study: Path | str | None = None,
    sensitivity_assessment: Path | str | None = None,
    template_robustness: Path | str | None = None,
    holdout_study: Path | str | None = None,
    pca_stability: Path | str | None = None,
    decision_review: Path | str | None = None,
    created_at: str | None = None,
) -> ScientificAtlasReport:
    """Reverify and compose all supplied evidence without changing any source."""

    review = _review_atlas(run_directory)
    config = _effective_config(review)
    decisions, decision_source = _load_decisions(review, decision_review)
    residuals = _residuals(review)
    threshold = _inspection_threshold(tuple(value for _, value in residuals))
    ranked = sorted(residuals, key=lambda item: (-item[1], item[0].casefold()))
    subjects = tuple(
        SubjectQC(
            rank=index,
            subject=name,
            residual=float(value),
            inspection_priority=threshold is not None and value > threshold,
            threshold=threshold,
            researcher_decision=decisions.get(name, "unreviewed"),
        )
        for index, (name, value) in enumerate(ranked, start=1)
    )
    sensitivity, sensitivity_sources = _validation_evidence(
        validation_study,
        config,
        sensitivity_assessment,
    )
    holdout, holdout_source = _holdout_evidence(holdout_study, sensitivity)
    template_evidence, template_source = _template_robustness_evidence(
        template_robustness
    )
    stability, stability_source = _pca_stability_evidence(pca_stability)
    sources = [
        ("workflow_manifest", review.workflow_manifest_path, review.workflow_manifest_sha256),
        ("analysis_manifest", review.bundle_manifest_path, review.bundle_manifest_sha256),
    ]
    sources.extend(sensitivity_sources)
    sources.extend(
        source
        for source in (
            decision_source,
            holdout_source,
            template_source,
            stability_source,
        )
        if source is not None
    )
    claims = _claim_matrix(
        review,
        subjects,
        decisions,
        sensitivity,
        template_evidence,
        holdout,
        stability,
    )
    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ScientificReportError("created_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ScientificReportError("created_at must include a timezone offset")
    return ScientificAtlasReport(
        created_at=timestamp,
        review=review,
        effective_config=config,
        subjects=subjects,
        decisions=tuple(sorted(decisions.items())),
        claims=claims,
        sensitivity=sensitivity,
        template_robustness=template_evidence,
        holdout=holdout,
        pca_stability=stability,
        evidence_sources=tuple(sources),
        methods_text=_methods(review, config),
    )


def _csv_text(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def _residual_svg(report: ScientificAtlasReport) -> str:
    shown = report.subjects[: min(25, len(report.subjects))]
    width = 980
    row_height = 27
    height = 90 + row_height * len(shown)
    maximum = max((item.residual for item in shown), default=1.0) or 1.0
    bars = []
    for index, item in enumerate(shown):
        y = 56 + index * row_height
        bar_width = 590 * item.residual / maximum
        colour = "#b64a45" if item.inspection_priority else "#167d72"
        bars.append(
            f'<text x="8" y="{y + 15}" font-size="12">{html.escape(item.subject)}</text>'
            f'<rect x="300" y="{y}" width="{bar_width:.3f}" height="18" fill="{colour}"/>'
            f'<text x="{310 + bar_width:.3f}" y="{y + 14}" font-size="12">'
            f"{item.residual:.6g}</text>"
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Ranked subject residuals">'
        '<rect width="100%" height="100%" fill="white"/>'
        '<text x="8" y="24" font-size="17" font-weight="600" fill="#083d3a">'
        "Highest subject residuals — inspection priority only</text>" + "".join(bars) + "</svg>"
    )


def _data_uri_svg(value: str) -> str:
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _embedded_artifact_svg(report: ScientificAtlasReport, key: str) -> str | None:
    try:
        path = verify_result_artifact(report.review, key)
    except (KeyError, OSError, RuntimeError, ValueError, ModernResultReviewError):
        return None
    if path.suffix.casefold() != ".svg":
        return None
    try:
        value = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError):
        return None
    if "<script" in value.casefold() or "http:" in value.casefold() or "https:" in value.casefold():
        return None
    return _data_uri_svg(value)


def render_scientific_report_html(report: ScientificAtlasReport) -> str:
    """Render a self-contained, script-free scientific review report."""

    payload = report.as_manifest()
    status_labels = {
        "supported": "Supported",
        "partial": "Partial evidence",
        "not_assessed": "Not assessed",
        "not_supported": "Not supported",
    }
    claim_rows = "".join(
        "<tr>"
        f"<td><strong>{html.escape(claim.label)}</strong></td>"
        f'<td><span class="status {claim.status}">{status_labels[claim.status]}</span></td>'
        f"<td>{html.escape(claim.evidence)}</td>"
        f"<td>{html.escape(claim.boundary)}</td>"
        "</tr>"
        for claim in report.claims
    )
    subject_rows = "".join(
        "<tr>"
        f"<td>{item.rank}</td><td>{html.escape(item.subject)}</td>"
        f"<td>{item.residual:.8g}</td>"
        f"<td>{'review first' if item.inspection_priority else 'routine'}</td>"
        f"<td>{html.escape(item.researcher_decision)}</td>"
        "</tr>"
        for item in report.subjects
    )
    decisions = dict(report.decisions)
    decision_summary = (
        ", ".join(
            f"{value}: {sum(item == value for item in decisions.values())}"
            for value in ("pass", "uncertain", "fail", "unreviewed")
        )
        or "No explicit researcher registration-QC decisions were supplied."
    )
    optimizer_plot = _embedded_artifact_svg(report, "optimizer-convergence-plot")
    pca_plot = _embedded_artifact_svg(report, "pca-scree")
    figures = [
        f'<figure><img src="{_data_uri_svg(_residual_svg(report))}" alt="Ranked subject residuals">'
        "<figcaption>Descriptive ranking only; highlighted cases require visual "
        "review.</figcaption>"
        "</figure>"
    ]
    if optimizer_plot is not None:
        figures.append(
            f'<figure><img src="{optimizer_plot}" alt="Verified optimizer history">'
            "<figcaption>Verified optimizer history from the source result.</figcaption></figure>"
        )
    if pca_plot is not None:
        method = html.escape(report.review.pca_method_label)
        figures.append(
            f'<figure><img src="{pca_plot}" alt="Verified {method} scree plot">'
            f"<figcaption>Verified explained-variance plot for {method}; component axes "
            "are descriptive.</figcaption>"
            "</figure>"
        )
    evidence_cards = []
    if report.sensitivity is not None:
        automatic = report.sensitivity["automatic_assessment"]
        automatic_text = (
            "not supplied"
            if automatic is None
            else str(automatic["status"])
        )
        evidence_cards.append(
            "<div class='card'><h3>Neighboring-parameter sensitivity</h3>"
            f"<p>Status: <strong>{html.escape(str(report.sensitivity['status']))}</strong>; "
            f"winner support: {html.escape(str(report.sensitivity['winner_support']))}; "
            "final atlas matches recommendation: "
            f"{html.escape(str(report.sensitivity['final_atlas_matches_recommendation']))}; "
            f"automatic template/outlier/PCA assessment: "
            f"<strong>{html.escape(automatic_text)}</strong>.</p></div>"
        )
    if report.holdout is not None:
        evidence_cards.append(
            "<div class='card'><h3>Fixed-template holdout</h3>"
            f"<p>Status: <strong>{html.escape(str(report.holdout['status']))}</strong>; "
            f"{report.holdout['subject_count']} subjects; paired support "
            f"{html.escape(str(report.holdout['subject_support']))}.</p></div>"
        )
    if report.template_robustness is not None:
        evidence_cards.append(
            "<div class='card'><h3>Initial-template robustness</h3>"
            f"<p>Status: <strong>"
            f"{html.escape(str(report.template_robustness['status']))}</strong>; "
            f"{report.template_robustness['arm_count']} tested starts; "
            f"{report.template_robustness['subject_count']} subjects per arm.</p></div>"
        )
    if report.pca_stability is not None:
        evidence_cards.append(
            "<div class='card'><h3>PCA stability</h3>"
            f"<p>Linear CKA: {report.pca_stability['score_linear_cka']:.6g}; "
            "score-distance rank correlation: "
            f"{report.pca_stability['score_distance_rank_correlation']:.6g}.</p></div>"
        )
    if not evidence_cards:
        evidence_cards.append(
            "<div class='card'><h3>Additional robustness evidence</h3>"
            "<p>No sensitivity, fixed-template holdout, or paired PCA-stability artifact "
            "was supplied. The report marks these claims as not assessed.</p></div>"
        )
    boundaries = "".join(
        f"<li>{html.escape(value)}</li>" for value in report.review.scientific_boundaries
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="generator" content="DiffeoForge scientific atlas report {SCIENTIFIC_REPORT_VERSION}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DiffeoForge scientific atlas report — {html.escape(report.review.project_name)}</title>
<style>
:root{{--ink:#123b39;--muted:#5d7472;--line:#cadbd8;--paper:#fff;--wash:#eef7f5;
--ok:#167d72;--partial:#9b6a16;--no:#a1443f}}*{{box-sizing:border-box}}
body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f8f7;
color:var(--ink);line-height:1.5}}
main{{max-width:1180px;margin:32px auto;background:var(--paper);padding:38px 44px;
box-shadow:0 8px 30px #173b3920}}
h1,h2,h3{{line-height:1.2}}h1{{margin-bottom:4px}}.subtitle{{color:var(--muted);margin-top:0}}
.summary,.card{{border:1px solid var(--line);border-radius:10px;padding:16px 18px;
background:var(--wash)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{border:1px solid var(--line);padding:9px;text-align:left;vertical-align:top}}
th{{background:var(--wash)}}
.status{{font-weight:650}}.supported{{color:var(--ok)}}.partial{{color:var(--partial)}}
.not_assessed,.not_supported{{color:var(--no)}}
figure{{margin:20px 0;border:1px solid var(--line);padding:12px}}
img{{max-width:100%;height:auto}}figcaption{{color:var(--muted);font-size:13px}}
code{{word-break:break-all}}
@media print{{body{{background:white}}main{{box-shadow:none;margin:0;max-width:none}}}}
</style></head><body><main>
<h1>Scientific atlas report</h1>
<p class="subtitle">{html.escape(report.review.project_name)} ·
{html.escape(report.engine_label)} · generated {html.escape(report.created_at)}</p>
<div class="summary"><strong>Interpretation:</strong> This report separates verified technical
evidence from scientific claims. A completed run, low residual, or stable PCA is never treated
as automatic biological validation.</div>
<h2>Claim matrix</h2><table><thead><tr><th>Question</th><th>Status</th>
<th>Evidence</th><th>Boundary</th></tr></thead><tbody>{claim_rows}</tbody></table>
<h2>Robustness evidence</h2><div class="grid">{"".join(evidence_cards)}</div>
<h2>Subject registration review</h2><p>Metric: {html.escape(report.residual_metric)}.
Researcher decisions: {html.escape(decision_summary)}</p>
<table><thead><tr><th>Rank</th><th>Subject</th><th>Residual</th><th>Inspection</th><th>Decision</th></tr></thead><tbody>{subject_rows}</tbody></table>
<h2>Figures</h2>{"".join(figures)}
<h2>Paper-ready methods draft</h2><p>{html.escape(report.methods_text)}</p>
<h2>Scientific boundaries</h2><ul>{boundaries}</ul>
<h2>Reproducibility</h2><p>The adjacent JSON, CSV, methods text, and report manifest bind this
view to the exact source manifests and supplied evidence hashes. Project payload version:
<code>{html.escape(str(payload["report_version"]))}</code>.</p>
</main></body></html>"""


def _artifact_record(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_scientific_atlas_report(
    report: ScientificAtlasReport,
    destination: Path | str | None = None,
) -> ScientificReportArtifact:
    """Atomically publish an immutable report directory and verify it."""

    target = (
        default_scientific_report_directory(report.review.run_directory)
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    if target.exists() or target.is_symlink():
        raise ScientificReportError(f"Scientific report destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        payload = report.as_manifest()
        write_text_safely(
            temporary / SCIENTIFIC_REPORT_JSON,
            _canonical_json(payload),
            overwrite=False,
        )
        write_text_safely(
            temporary / SCIENTIFIC_REPORT_HTML,
            render_scientific_report_html(report),
            overwrite=False,
        )
        write_text_safely(
            temporary / SCIENTIFIC_METHODS_TEXT,
            report.methods_text + "\n",
            overwrite=False,
        )
        write_text_safely(
            temporary / SCIENTIFIC_SUBJECTS_CSV,
            _csv_text(
                (
                    "rank",
                    "subject",
                    "residual",
                    "inspection_priority",
                    "threshold",
                    "researcher_decision",
                ),
                [
                    (
                        item.rank,
                        item.subject,
                        format(item.residual, ".17g"),
                        str(item.inspection_priority).lower(),
                        "" if item.threshold is None else format(item.threshold, ".17g"),
                        item.researcher_decision,
                    )
                    for item in report.subjects
                ],
            ),
            overwrite=False,
        )
        write_text_safely(
            temporary / SCIENTIFIC_CLAIMS_CSV,
            _csv_text(
                ("claim_id", "label", "status", "evidence", "boundary"),
                [
                    (claim.claim_id, claim.label, claim.status, claim.evidence, claim.boundary)
                    for claim in report.claims
                ],
            ),
            overwrite=False,
        )
        write_text_safely(
            temporary / SCIENTIFIC_DECISIONS_CSV,
            _csv_text(
                ("subject", "decision"),
                [(subject, decision) for subject, decision in report.decisions],
            ),
            overwrite=False,
        )
        artifacts = [
            _artifact_record(temporary, path)
            for path in sorted(temporary.iterdir(), key=lambda item: item.name)
            if path.is_file()
        ]
        manifest = {
            "artifact_version": SCIENTIFIC_REPORT_VERSION,
            "created_at": report.created_at,
            "source": {
                "run_directory": str(report.review.run_directory),
                "validation_study": (
                    None
                    if report.sensitivity is None
                    else str(
                        next(
                            path.parent.parent
                            for role, path, _ in report.evidence_sources
                            if role == "sensitivity_study"
                        )
                    )
                ),
                "sensitivity_assessment": (
                    None
                    if report.sensitivity is None
                    or report.sensitivity["automatic_assessment"] is None
                    else str(
                        next(
                            path.parent
                            for role, path, _ in report.evidence_sources
                            if role == "automatic_sensitivity_assessment"
                        )
                    )
                ),
                "template_robustness": (
                    None
                    if report.template_robustness is None
                    else str(
                        next(
                            path.parent.parent
                            for role, path, _ in report.evidence_sources
                            if role == "template_robustness"
                        )
                    )
                ),
                "holdout_study": (
                    None
                    if report.holdout is None
                    else str(
                        next(
                            path.parent.parent
                            for role, path, _ in report.evidence_sources
                            if role == "fixed_template_holdout"
                        )
                    )
                ),
                "pca_stability": (
                    None
                    if report.pca_stability is None
                    else str(
                        next(
                            path.parent
                            for role, path, _ in report.evidence_sources
                            if role == "pca_stability"
                        )
                    )
                ),
                "decision_review": (
                    None
                    if not report.decisions
                    else str(
                        next(
                            path
                            for role, path, _ in report.evidence_sources
                            if role == "registration_qc_review"
                        )
                    )
                ),
                "evidence": [
                    {"role": role, "path": str(path), "sha256": digest}
                    for role, path, digest in report.evidence_sources
                ],
            },
            "artifacts": artifacts,
            "verification_contract": (
                "Every output byte and every supplied source artifact is SHA-256 bound; "
                "the source atlas is independently reverified."
            ),
        }
        manifest_path = temporary / SCIENTIFIC_REPORT_MANIFEST
        write_text_safely(manifest_path, _canonical_json(manifest), overwrite=False)
        write_text_safely(
            temporary / SCIENTIFIC_REPORT_SIDECAR,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
            encoding="ascii",
        )
        publish_directory_exclusive(temporary, target)
        return _verify_scientific_atlas_report(target, reverify_source=False)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _verify_scientific_atlas_report(
    directory: Path | str,
    *,
    reverify_source: bool,
) -> ScientificReportArtifact:

    root = Path(directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ScientificReportError(f"Scientific report directory is missing or symbolic: {root}")
    if any(path.is_symlink() or path.is_dir() for path in root.iterdir()):
        raise ScientificReportError("Scientific report contains a symbolic path or subdirectory")
    manifest_path = root / SCIENTIFIC_REPORT_MANIFEST
    sidecar_path = root / SCIENTIFIC_REPORT_SIDECAR
    try:
        expected = sidecar_path.read_text(encoding="ascii").strip()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScientificReportError("Scientific report manifest is unreadable") from error
    if expected != sha256_file(manifest_path):
        raise ScientificReportError("Scientific report manifest SHA-256 differs")
    if (
        not isinstance(manifest, dict)
        or manifest.get("artifact_version") != SCIENTIFIC_REPORT_VERSION
    ):
        raise ScientificReportError("Scientific report manifest version is unsupported")
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise ScientificReportError("Scientific report source binding is invalid")
    if reverify_source:
        _review_atlas(str(source["run_directory"]))
    evidence = source.get("evidence")
    if not isinstance(evidence, list):
        raise ScientificReportError("Scientific report evidence inventory is invalid")
    for record in evidence:
        if not isinstance(record, Mapping):
            raise ScientificReportError("Scientific report evidence record is invalid")
        path = Path(str(record["path"]))
        if path.is_symlink() or not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ScientificReportError(f"Scientific report source evidence changed: {path}")
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise ScientificReportError("Scientific report artifact inventory is invalid")
    expected_files = {
        SCIENTIFIC_REPORT_MANIFEST,
        SCIENTIFIC_REPORT_SIDECAR,
        *(str(record["path"]) for record in records if isinstance(record, Mapping)),
    }
    actual_files = {path.name for path in root.iterdir() if path.is_file()}
    if expected_files != actual_files:
        raise ScientificReportError("Scientific report exact file inventory differs")
    for record in records:
        if not isinstance(record, Mapping):
            raise ScientificReportError("Scientific report artifact record is invalid")
        path = root / str(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            raise ScientificReportError(f"Scientific report artifact changed: {path.name}")
    return ScientificReportArtifact(root, manifest)


def verify_scientific_atlas_report(directory: Path | str) -> ScientificReportArtifact:
    """Reverify source manifests, evidence hashes, and the exact report inventory."""

    return _verify_scientific_atlas_report(directory, reverify_source=True)

"""Source-bound visual review gate; never filters specimens or modifies an atlas."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.desktop.reference_result_review import (
    finalize_registration_qc_review,
    load_finalized_registration_qc_review,
    load_registration_qc_draft,
    registration_qc_directory,
)
from diffeoforge.desktop.result_review import ModernResultReview, ModernResultReviewError
from diffeoforge.mesh import sha256_file
from diffeoforge.registration_screening import inspection_threshold

RELEASE_NAME = "registration-results-release.json"
POLICY = "flagged-registration-visual-approval-v1"


def registration_inspection_plan(review: ModernResultReview) -> dict:
    """Freeze a relative residual screen across the entire verified cohort."""
    items = review.registration_qc
    names = {item.subject_name for item in items}
    if not names or len(names) != len(items):
        raise ModernResultReviewError("A complete, unique registration review cohort is required")
    try:
        threshold = inspection_threshold(tuple(item.residual_p95 for item in items))
    except ValueError as error:
        raise ModernResultReviewError(str(error)) from error
    reasons = {}
    for item in items:
        if threshold is None:
            reasons[item.subject_name] = (
                "Fewer than 4 specimens: residual screening is unavailable; visual review required."
            )
        elif item.residual_p95 > threshold:
            reasons[item.subject_name] = (
                f"{review.registration_qc_metric_label} {item.residual_p95:.6g} exceeds "
                f"the cohort upper fence {threshold:.6g} (Q3 + 1.5 x IQR)."
            )
    return {
        "rule": "upper-tukey-fence-linear-quartiles-v1",
        "metric": review.registration_qc_metric_label,
        "subject_count": len(items),
        "threshold": threshold,
        "flagged_subjects": dict(sorted(reasons.items())),
        "residuals": dict(sorted((item.subject_name, item.residual_p95) for item in items)),
        "boundary": (
            "Relative residual screening can miss uniformly poor fits. Not flagged does not "
            "mean visually reviewed, anatomically correct or biologically validated."
        ),
    }


def required_registration_inspections(
    review: ModernResultReview, decisions: Mapping[str, str]
) -> dict[str, str]:
    """Also keep any researcher-recorded concern in the mandatory queue."""
    reasons = dict(registration_inspection_plan(review)["flagged_subjects"])
    for name, decision in decisions.items():
        if decision in {"uncertain", "fail"}:
            reasons.setdefault(name, f"Researcher decision is {decision}; resolve before release.")
    return reasons


def _visual_review_scope(review, decisions, inspections) -> dict:
    return {
        "policy": POLICY,
        "screening": registration_inspection_plan(review),
        "required_subjects": sorted(required_registration_inspections(review, decisions)),
        "required_review_complete": True,
        "visually_inspected_subjects": sorted(inspections),
        "unreviewed_subjects": sorted(
            item.subject_name for item in review.registration_qc
            if item.subject_name not in inspections
        ),
    }


def inspection_binding(review: ModernResultReview, subject: str) -> dict[str, str]:
    """Identify both mesh bytes shown to the researcher, in atlas coordinates."""
    item = review.registration_qc_item(subject)
    return {
        "original_sha256": review.artifact(item.original_artifact_key).sha256,
        "reconstruction_sha256": review.artifact(item.reconstruction_artifact_key).sha256,
    }


def _source(review: ModernResultReview) -> dict[str, str]:
    return {
        "run_manifest_sha256": review.workflow_manifest_sha256,
        "analysis_manifest_sha256": review.bundle_manifest_sha256,
    }


def load_visual_inspections(review: ModernResultReview) -> dict[str, dict[str, str]]:
    """Resume acknowledged overlays; legacy decisions alone are not visual approval."""
    decisions = load_registration_qc_draft(review)
    path = registration_qc_directory(review) / "registration-qc-draft.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        inspections = payload.get("visual_inspections", {})
        if not isinstance(inspections, dict) or set(inspections) - set(decisions):
            raise ValueError("Visual inspections do not match the saved decisions")
        for subject, binding in inspections.items():
            if binding != inspection_binding(review, subject):
                raise ValueError(f"Visual inspection mesh binding changed: {subject}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ModernResultReviewError(f"Visual review draft did not verify: {error}") from error
    return inspections


def require_visual_approvals(
    review: ModernResultReview,
    decisions: Mapping[str, str],
    inspections: Mapping[str, Mapping[str, str]],
) -> None:
    """Only flagged cases require approval; other specimens remain unreviewed."""
    names = {item.subject_name for item in review.registration_qc}
    required = required_registration_inspections(review, decisions)
    if set(decisions) - names or any(
        value not in {"pass", "uncertain", "fail"} for value in decisions.values()
    ):
        raise ModernResultReviewError("Visual review decisions contain unknown subjects or values")
    if any(decisions.get(name) != "pass" for name in required):
        raise ModernResultReviewError(
            "Results remain locked: inspect the flagged registrations and resolve all uncertain "
            "or implausible decisions. Unflagged specimens do not require visual approval."
        )
    if set(inspections) != set(decisions) or any(
        binding != inspection_binding(review, name) for name, binding in inspections.items()
    ) or any(name not in inspections for name in required):
        raise ModernResultReviewError(
            "Results remain locked: each recorded approval needs an explicit visual-inspection "
            "acknowledgement. Unflagged cases can remain unreviewed; do not mark them as passed "
            "without inspection. Older QC decisions alone do not release results."
        )


def release_registration_results(
    review: ModernResultReview,
    decisions: Mapping[str, str],
    inspections: Mapping[str, Mapping[str, str]],
) -> None:
    """Finalize an immutable review and atomically record explicit result release."""
    require_visual_approvals(review, decisions, inspections)
    for path, expected in (
        (review.workflow_manifest_path, review.workflow_manifest_sha256),
        (review.bundle_manifest_path, review.bundle_manifest_sha256),
        *review.additional_manifest_bindings,
    ):
        if sha256_file(path) != expected:
            raise ModernResultReviewError("Atlas evidence changed; reload before visual approval")
    scope = _visual_review_scope(review, decisions, inspections)
    finalized = finalize_registration_qc_review(
        review, decisions, allow_incomplete=True, visual_review_scope=scope
    )
    payload = {
        "schema_version": "0.2",
        "policy": POLICY,
        "released_at": datetime.now(UTC).isoformat(),
        "source": _source(review),
        "finalized_review_sha256": finalized.sha256,
        "visual_inspections": dict(inspections),
        "visual_review_scope": scope,
        "scientific_boundary": (
            "Flagged cases have researcher visual plausibility approval, "
            "not biological validation. "
            "Unflagged, uninspected cases remain explicitly unreviewed. "
            "All atlas/PCA specimens and source evidence remain unchanged."
        ),
    }
    write_text_safely(
        registration_qc_directory(review) / RELEASE_NAME,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        overwrite=True,
    )


def require_registration_release(
    review: ModernResultReview,
    decisions: Mapping[str, str],
    inspections: Mapping[str, Mapping[str, str]],
) -> None:
    """Fail closed for missing, legacy, changed or superseded approvals."""
    require_visual_approvals(review, decisions, inspections)
    path = registration_qc_directory(review) / RELEASE_NAME
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Use Approve review & release results in Step 5 first")
        payload = json.loads(path.read_text(encoding="utf-8"))
        finalized = load_finalized_registration_qc_review(review)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "0.2"
            or payload.get("policy") != POLICY
            or payload.get("source") != _source(review)
            or payload.get("visual_inspections") != dict(inspections)
            or finalized is None
            or payload.get("visual_review_scope")
            != _visual_review_scope(review, decisions, inspections)
            or dict(finalized.decisions) != {
                item.subject_name: decisions.get(item.subject_name, "unreviewed")
                for item in review.registration_qc
            }
            or payload.get("finalized_review_sha256") != finalized.sha256
        ):
            raise ValueError("The saved release no longer matches the current visual review")
        # Also catch manifest edits after the result snapshot was loaded.
        for manifest, expected in (
            (review.workflow_manifest_path, review.workflow_manifest_sha256),
            (review.bundle_manifest_path, review.bundle_manifest_sha256),
            *review.additional_manifest_bindings,
        ):
            if sha256_file(manifest) != expected:
                raise ValueError("The reviewed atlas evidence changed; reload the run")
    except (OSError, ValueError, TypeError) as error:
        raise ModernResultReviewError(f"Results remain locked: {error}") from error

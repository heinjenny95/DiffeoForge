"""Qt-independent review of verified Deformetrica momenta PCA results."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.desktop.result_review import (
    ModernResultArtifact,
    ModernResultReview,
    ModernResultReviewError,
    RegistrationQCItem,
    ResultArtifactKind,
    ResultReviewItem,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration_metrics import (
    ReferenceCalibrationRunMetrics,
    collect_reference_calibration_run_metrics,
)
from diffeoforge.reference_pca import (
    DEFAULT_REFERENCE_PCA_DIRECTORY,
    REFERENCE_PCA_MANIFEST,
    ReferencePCAError,
    verify_reference_pca_bundle,
    write_reference_pca_bundle,
)
from diffeoforge.reference_pca_deformations import (
    DEFAULT_RESULT_DIRECTORY as DEFAULT_PCA_DEFORMATION_RESULT_DIRECTORY,
)
from diffeoforge.reference_pca_deformations import (
    RESULT_NAME as PCA_DEFORMATION_RESULT_NAME,
)
from diffeoforge.reference_pca_deformations import (
    ReferencePCADeformationError,
    verify_reference_pca_deformation_result,
)
from diffeoforge.result_report import collect_run_report

_PCA_DISPLAY_LIMIT = 10
_ESTIMATED_TEMPLATE_MARKER = "__EstimatedParameters__Template_"
_RECONSTRUCTION_MARKER = "__Reconstruction__"
_REGISTRATION_QC_DRAFT = "registration-qc-draft.json"
_REGISTRATION_QC_FINALIZED = "registration-qc-finalized.json"


@dataclass(frozen=True)
class RegistrationQCReviewExport:
    """One non-overwriting researcher review record and its digest sidecar."""

    path: Path
    sha256_path: Path
    sha256: str
    binding_path: Path | None = None
    complete: bool = False


@dataclass(frozen=True)
class FinalizedRegistrationQCReview:
    """One verified final review selected for downstream scientific reports."""

    path: Path
    sha256: str
    complete: bool
    decisions: Mapping[str, str]


def registration_qc_directory(review: ModernResultReview) -> Path:
    """Keep Modern's exact-inventory workflow tree immutable as well."""
    if review.engine_route == "modern":
        return review.run_directory.with_name(review.run_directory.name + "-reviews")
    return review.run_directory / "reviews"


def _validated_registration_qc_decisions(
    review: ModernResultReview,
    decisions: Mapping[str, str],
) -> dict[str, str]:
    if not review.registration_qc:
        raise ModernResultReviewError(
            "A full-cohort registration-QC ranking is required"
        )
    allowed_subjects = {item.subject_name for item in review.registration_qc}
    normalized = dict(decisions)
    unexpected = set(normalized) - allowed_subjects
    if unexpected:
        raise ModernResultReviewError(
            "Registration-QC decisions contain unknown subjects: "
            + ", ".join(sorted(unexpected))
        )
    allowed_decisions = {"pass", "uncertain", "fail"}
    if any(decision not in allowed_decisions for decision in normalized.values()):
        raise ModernResultReviewError(
            "Registration-QC decisions must be pass, uncertain, or fail"
        )
    return normalized


def save_registration_qc_draft(
    review: ModernResultReview,
    decisions: Mapping[str, str],
    *,
    visual_inspections: Mapping[str, Mapping[str, str]] | None = None,
) -> Path:
    """Atomically persist the current QC session outside immutable run evidence."""

    normalized = _validated_registration_qc_decisions(review, decisions)
    payload = {
        "schema_version": "0.1",
        "updated_at": datetime.now(UTC).isoformat(),
        "source": {
            "run_manifest_sha256": review.workflow_manifest_sha256,
            "analysis_manifest_sha256": review.bundle_manifest_sha256,
        },
        "decisions": dict(sorted(normalized.items())),
        "visual_inspections": dict(visual_inspections or {}),
    }
    path = registration_qc_directory(review) / _REGISTRATION_QC_DRAFT
    write_text_safely(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        overwrite=True,
    )
    return path


def load_registration_qc_draft(review: ModernResultReview) -> dict[str, str]:
    """Load a source-bound autosave draft, returning an empty mapping when absent."""

    path = registration_qc_directory(review) / _REGISTRATION_QC_DRAFT
    if not path.exists():
        return {}
    if not path.is_file() or path.is_symlink():
        raise ModernResultReviewError("Registration-QC draft is not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernResultReviewError(f"Registration-QC draft is unreadable: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != "0.1":
        raise ModernResultReviewError("Registration-QC draft has an unsupported schema")
    source = payload.get("source")
    if not isinstance(source, dict) or source != {
        "run_manifest_sha256": review.workflow_manifest_sha256,
        "analysis_manifest_sha256": review.bundle_manifest_sha256,
    }:
        raise ModernResultReviewError(
            "Registration-QC draft belongs to different verified run evidence"
        )
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict) or not all(
        isinstance(subject, str) and isinstance(decision, str)
        for subject, decision in decisions.items()
    ):
        raise ModernResultReviewError("Registration-QC draft decisions are invalid")
    return _validated_registration_qc_decisions(review, decisions)


def _reconstruction_subject_name(value: str) -> str:
    name = PurePosixPath(value).name
    marker = "__subject_"
    if marker not in name:
        raise ModernResultReviewError(
            f"Could not identify the subject in reconstruction output: {name}"
        )
    subject = name.split(marker, 1)[1]
    if not subject.casefold().endswith(".vtk"):
        raise ModernResultReviewError(f"Unexpected reconstruction filename: {name}")
    return subject[:-4]


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.3g} {unit}"


def _format_duration(value: float) -> str:
    minutes, seconds = divmod(float(value), 60.0)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours} h {minutes} min {seconds:.1f} s"
    if minutes:
        return f"{minutes} min {seconds:.1f} s"
    return f"{seconds:.1f} s"


def export_registration_qc_review(
    review: ModernResultReview,
    decisions: Mapping[str, str],
) -> RegistrationQCReviewExport:
    """Export explicit full-cohort QC decisions without mutating run evidence."""

    decisions = _validated_registration_qc_decisions(review, decisions)
    created_at = datetime.now(UTC)
    payload = {
        "schema_version": "0.1",
        "created_at": created_at.isoformat(),
        "scientific_boundary": (
            "Residual rank prioritizes inspection and is not an automatic biological "
            "exclusion rule. Decisions are researcher-recorded plausibility evidence."
        ),
        "source": {
            "run_directory": str(review.run_directory),
            "run_manifest_sha256": review.workflow_manifest_sha256,
            "analysis_manifest_sha256": review.bundle_manifest_sha256,
        },
        "summary": {
            "subject_count": len(review.registration_qc),
            "reviewed_count": len(decisions),
            "unreviewed_count": len(review.registration_qc) - len(decisions),
        },
        "subjects": [
            {
                "rank": item.rank,
                "subject_name": item.subject_name,
                "residual_p95": item.residual_p95,
                "decision": decisions.get(item.subject_name, "unreviewed"),
            }
            for item in review.registration_qc
        ],
    }
    directory = registration_qc_directory(review)
    directory.mkdir(parents=True, exist_ok=True)
    stem = (
        "registration-qc-review-"
        + created_at.strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    path = directory / f"{stem}.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    digest = sha256_file(path)
    sidecar = directory / f"{stem}.sha256"
    with sidecar.open("x", encoding="ascii", newline="\n") as handle:
        handle.write(f"{digest}  {path.name}\n")
    return RegistrationQCReviewExport(path, sidecar, digest)


def _registration_qc_counts(
    review: ModernResultReview,
    decisions: Mapping[str, str],
) -> dict[str, int]:
    counts = {"pass": 0, "uncertain": 0, "fail": 0, "unreviewed": 0}
    for item in review.registration_qc:
        counts[decisions.get(item.subject_name, "unreviewed")] += 1
    return counts


def finalize_registration_qc_review(
    review: ModernResultReview,
    decisions: Mapping[str, str],
    *,
    allow_incomplete: bool = False,
    visual_review_scope: Mapping[str, Any] | None = None,
) -> RegistrationQCReviewExport:
    """Finalize one explicit QC review and atomically bind downstream reports to it.

    The immutable review is never overwritten.  A small source-bound pointer records
    which finalized review scientific reports should use by default.  Incomplete
    finalization requires an explicit caller declaration.
    """

    normalized = _validated_registration_qc_decisions(review, decisions)
    counts = _registration_qc_counts(review, normalized)
    complete = counts["unreviewed"] == 0
    if not complete and not allow_incomplete:
        raise ModernResultReviewError(
            "Registration QC is incomplete: "
            f"{counts['unreviewed']} of {len(review.registration_qc)} subjects remain "
            "unreviewed. Review every subject or explicitly finalize an incomplete review."
        )

    created_at = datetime.now(UTC)
    payload = {
        "schema_version": "0.2",
        "review_status": "finalized",
        "visual_review_scope": (
            dict(visual_review_scope) if visual_review_scope is not None else None
        ),
        "created_at": created_at.isoformat(),
        "scientific_boundary": (
            "Residual rank prioritizes inspection and is not an automatic biological "
            "exclusion rule. Finalized decisions are researcher-recorded plausibility "
            "evidence and do not mutate the atlas or PCA."
        ),
        "source": {
            "run_directory": str(review.run_directory),
            "run_manifest_sha256": review.workflow_manifest_sha256,
            "analysis_manifest_sha256": review.bundle_manifest_sha256,
        },
        "summary": {
            "subject_count": len(review.registration_qc),
            "reviewed_count": len(normalized),
            "unreviewed_count": counts["unreviewed"],
            "decision_counts": counts,
            "complete": complete,
            "incomplete_finalization_explicitly_confirmed": bool(
                not complete and allow_incomplete
            ),
        },
        "subjects": [
            {
                "rank": item.rank,
                "subject_name": item.subject_name,
                "residual_p95": item.residual_p95,
                "decision": normalized.get(item.subject_name, "unreviewed"),
            }
            for item in review.registration_qc
        ],
    }
    directory = registration_qc_directory(review)
    directory.mkdir(parents=True, exist_ok=True)
    stem = (
        "registration-qc-review-"
        + created_at.strftime("%Y%m%dT%H%M%SZ")
        + "-finalized-"
        + uuid.uuid4().hex[:8]
    )
    path = directory / f"{stem}.json"
    write_text_safely(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        overwrite=False,
    )
    digest = sha256_file(path)
    sidecar = directory / f"{stem}.sha256"
    write_text_safely(
        sidecar,
        f"{digest}  {path.name}\n",
        overwrite=False,
        encoding="ascii",
    )
    binding_path = directory / _REGISTRATION_QC_FINALIZED
    binding = {
        "schema_version": "0.1",
        "updated_at": created_at.isoformat(),
        "source": {
            "run_manifest_sha256": review.workflow_manifest_sha256,
            "analysis_manifest_sha256": review.bundle_manifest_sha256,
        },
        "review": {
            "filename": path.name,
            "sha256": digest,
            "complete": complete,
            "reviewed_count": len(normalized),
            "unreviewed_count": counts["unreviewed"],
        },
    }
    write_text_safely(
        binding_path,
        json.dumps(binding, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        overwrite=True,
    )
    return RegistrationQCReviewExport(
        path,
        sidecar,
        digest,
        binding_path=binding_path,
        complete=complete,
    )


def load_finalized_registration_qc_review(
    review: ModernResultReview,
) -> FinalizedRegistrationQCReview | None:
    """Verify and load the review explicitly bound for downstream reporting."""

    directory = registration_qc_directory(review)
    binding_path = directory / _REGISTRATION_QC_FINALIZED
    if not binding_path.exists():
        return None
    if not binding_path.is_file() or binding_path.is_symlink():
        raise ModernResultReviewError(
            "Finalized registration-QC binding is not a regular file"
        )
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8", errors="strict"))
        source = binding["source"]
        record = binding["review"]
    except (KeyError, OSError, UnicodeError, TypeError, json.JSONDecodeError) as error:
        raise ModernResultReviewError(
            "Finalized registration-QC binding is unreadable or incomplete"
        ) from error
    if binding.get("schema_version") != "0.1" or source != {
        "run_manifest_sha256": review.workflow_manifest_sha256,
        "analysis_manifest_sha256": review.bundle_manifest_sha256,
    }:
        raise ModernResultReviewError(
            "Finalized registration-QC binding belongs to different verified run evidence"
        )
    filename = record.get("filename") if isinstance(record, dict) else None
    expected_hash = record.get("sha256") if isinstance(record, dict) else None
    if (
        not isinstance(filename, str)
        or Path(filename).name != filename
        or not filename.startswith("registration-qc-review-")
        or not filename.endswith(".json")
        or not isinstance(expected_hash, str)
        or len(expected_hash) != 64
    ):
        raise ModernResultReviewError("Finalized registration-QC review identity is invalid")
    path = directory / filename
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected_hash:
        raise ModernResultReviewError(
            "Finalized registration-QC review is missing, symbolic, or changed"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        payload_source = payload["source"]
        subjects = payload["subjects"]
        summary = payload["summary"]
    except (KeyError, OSError, UnicodeError, TypeError, json.JSONDecodeError) as error:
        raise ModernResultReviewError(
            "Finalized registration-QC review is unreadable or incomplete"
        ) from error
    if payload.get("schema_version") != "0.2" or payload.get("review_status") != "finalized":
        raise ModernResultReviewError("Bound registration-QC review is not finalized")
    if not isinstance(payload_source, dict) or (
        payload_source.get("run_manifest_sha256") != review.workflow_manifest_sha256
        or payload_source.get("analysis_manifest_sha256") != review.bundle_manifest_sha256
    ):
        raise ModernResultReviewError(
            "Finalized registration-QC review belongs to different atlas evidence"
        )
    if not isinstance(subjects, list) or not isinstance(summary, dict):
        raise ModernResultReviewError("Finalized registration-QC subject records are invalid")
    decisions: dict[str, str] = {}
    for item in subjects:
        if not isinstance(item, dict):
            raise ModernResultReviewError(
                "Finalized registration-QC subject record is invalid"
            )
        name = item.get("subject_name")
        decision = item.get("decision")
        if not isinstance(name, str) or decision not in {
            "pass",
            "uncertain",
            "fail",
            "unreviewed",
        }:
            raise ModernResultReviewError(
                "Finalized registration-QC review contains an invalid decision"
            )
        if name in decisions:
            raise ModernResultReviewError(
                "Finalized registration-QC review contains a duplicate subject"
            )
        decisions[name] = decision
    expected_subjects = {item.subject_name for item in review.registration_qc}
    if set(decisions) != expected_subjects:
        raise ModernResultReviewError(
            "Finalized registration-QC review does not cover the verified cohort"
        )
    complete = all(value != "unreviewed" for value in decisions.values())
    if summary.get("complete") is not complete or record.get("complete") is not complete:
        raise ModernResultReviewError(
            "Finalized registration-QC completeness metadata differs from decisions"
        )
    return FinalizedRegistrationQCReview(
        path=path,
        sha256=expected_hash,
        complete=complete,
        decisions=dict(sorted(decisions.items())),
    )


def _pca_items(bundle_manifest: dict, ratios: tuple[float, ...]) -> tuple[ResultReviewItem, ...]:
    pca = bundle_manifest["pca"]
    method_label = str(pca["method"])
    if str(pca["method_id"]) == "lddmm_deformation_kernel_pca":
        method_label += " — default"
    items = [
        ResultReviewItem(
            method_label,
            f"{pca['components']} components · rank {pca['numerical_rank']}",
            f"{pca['method']} of Deformetrica subject initial momenta.",
        ),
        ResultReviewItem(
            "Total variance",
            f"{float(pca['total_variance']):.6g}",
            "Variance in the documented control-point/Cartesian momenta feature space.",
        ),
    ]
    cumulative = 0.0
    for index, ratio in enumerate(ratios[:_PCA_DISPLAY_LIMIT], start=1):
        cumulative += ratio
        items.append(
            ResultReviewItem(
                f"PC{index}",
                f"{ratio * 100:.3f}% · cumulative {cumulative * 100:.3f}%",
                "Explained-variance ratio; the component sign is conventional.",
            )
        )
    if len(ratios) > _PCA_DISPLAY_LIMIT:
        items.append(
            ResultReviewItem(
                "Additional components",
                str(len(ratios) - _PCA_DISPLAY_LIMIT),
                "Complete values remain available in the verified JSON and CSV files.",
            )
        )
    plots = pca["plots"]
    if plots["scores_pc2_pc3_path"] is None:
        items.append(
            ResultReviewItem(
                "PC2 vs PC3 plot",
                "unavailable",
                str(plots["scores_pc2_pc3_unavailable_reason"]),
            )
        )
    else:
        items.append(
            ResultReviewItem(
                "Standard score plots",
                "PC1 vs PC2 and PC2 vs PC3",
                "Both plots use the same verified score matrix and subject ordering.",
            )
        )
    return tuple(items)


def review_reference_result(
    run_directory: Path | str,
    *,
    create_pca_if_missing: bool = True,
) -> ModernResultReview:
    """Verify one Deformetrica run and its deterministic, source-bound PCA snapshot."""

    run = Path(run_directory).expanduser().resolve()
    bundle_directory = run / DEFAULT_REFERENCE_PCA_DIRECTORY
    try:
        if create_pca_if_missing and not bundle_directory.exists():
            write_reference_pca_bundle(run)
        verified = verify_reference_pca_bundle(bundle_directory, source_run=run)
        report = collect_run_report(run)
    except (OSError, RuntimeError, TypeError, ValueError, ReferencePCAError) as error:
        raise ModernResultReviewError(
            f"Deformetrica result and momenta PCA did not verify: {error}"
        ) from error

    deformation_result_directory = run / DEFAULT_PCA_DEFORMATION_RESULT_DIRECTORY
    deformation_result: Mapping[str, object] | None = None
    if deformation_result_directory.exists():
        try:
            deformation_result = verify_reference_pca_deformation_result(
                deformation_result_directory,
                source_run=run,
            )
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            ReferencePCADeformationError,
        ) as error:
            raise ModernResultReviewError(
                f"Reference PCA deformation result did not verify: {error}"
            ) from error

    qc_metrics: ReferenceCalibrationRunMetrics | None = None
    qc_unavailable_reason: str | None = None
    try:
        qc_metrics = collect_reference_calibration_run_metrics(run)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        qc_unavailable_reason = str(error)

    manifest = dict(verified.manifest)
    records = {str(record["path"]): record for record in manifest["artifacts"]}
    if len(records) != len(manifest["artifacts"]):
        raise ModernResultReviewError("Reference PCA contains duplicate artifact records")
    artifacts: list[ModernResultArtifact] = []

    def add_artifact(
        key: str,
        label: str,
        relative: object,
        kind: ResultArtifactKind,
        description: str,
    ) -> None:
        value = str(relative)
        record = records.get(value)
        if record is None:
            raise ModernResultReviewError(f"Displayed artifact is not inventoried: {value}")
        path = bundle_directory.joinpath(*Path(value).parts).resolve()
        try:
            path.relative_to(bundle_directory.resolve())
        except ValueError as error:
            raise ModernResultReviewError(
                f"Displayed artifact escapes the bundle: {value}"
            ) from error
        if path.is_symlink() or not path.is_file():
            raise ModernResultReviewError(f"Displayed artifact is missing or symbolic: {value}")
        size = int(record["bytes"])
        digest = str(record["sha256"])
        if path.stat().st_size != size or sha256_file(path) != digest:
            raise ModernResultReviewError(f"Displayed artifact changed: {value}")
        artifacts.append(
            ModernResultArtifact(key, label, path, kind, size, digest, description)
        )

    output_directory = run / "output"
    staged_input_directory = run / "input"

    def add_output_vtk_artifact(
        key: str,
        label: str,
        record: Mapping[str, Any],
        description: str,
    ) -> None:
        value = str(record["path"])
        relative = PurePosixPath(value)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or not relative.parts
        ):
            raise ModernResultReviewError(
                f"Displayed Deformetrica VTK has an unsafe inventory path: {value!r}"
            )
        path = output_directory.joinpath(*relative.parts)
        cursor = output_directory
        symbolic = cursor.is_symlink()
        for part in relative.parts:
            cursor = cursor / part
            symbolic = symbolic or cursor.is_symlink()
        if symbolic or not path.is_file():
            raise ModernResultReviewError(
                f"Displayed Deformetrica VTK is missing or symbolic: {value}"
            )
        size = int(record["bytes"])
        digest = str(record["sha256"])
        if path.stat().st_size != size or sha256_file(path) != digest:
            raise ModernResultReviewError(f"Displayed Deformetrica VTK changed: {value}")
        artifacts.append(
            ModernResultArtifact(key, label, path.resolve(), "vtk", size, digest, description)
        )

    def add_staged_input_artifact(
        key: str,
        label: str,
        record: Mapping[str, Any],
    ) -> None:
        relative = PurePosixPath(str(record.get("staged_path", "")))
        if (
            relative.is_absolute()
            or not relative.parts
            or "." in relative.parts
            or ".." in relative.parts
        ):
            raise ModernResultReviewError(
                f"Displayed staged input has an unsafe path: {relative}"
            )
        path = run.joinpath(*relative.parts).resolve()
        geometry = record.get("geometry")
        if not isinstance(geometry, Mapping):
            raise ModernResultReviewError(
                f"Displayed staged input lacks geometry evidence: {relative}"
            )
        size = int(geometry["bytes"])
        digest = str(geometry["sha256"])
        if (
            not path.is_relative_to(staged_input_directory.resolve())
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != size
            or sha256_file(path) != digest
        ):
            raise ModernResultReviewError(
                f"Displayed staged input changed or is unavailable: {relative}"
            )
        artifacts.append(
            ModernResultArtifact(
                key,
                label,
                path,
                "vtk",
                size,
                digest,
                "Immutable staged original used for original/reconstruction overlay QC.",
            )
        )

    def readable_output_name(value: str, marker: str) -> str:
        name = PurePosixPath(value).name.split(marker, 1)[-1]
        while name.lower().endswith(".vtk"):
            name = name[:-4]
        return name.replace("_", " ")

    estimated_templates = sorted(
        (
            record
            for record in report.inventory
            if str(record["path"]).lower().endswith(".vtk")
            and _ESTIMATED_TEMPLATE_MARKER in PurePosixPath(str(record["path"])).name
        ),
        key=lambda record: str(record["path"]),
    )
    for index, record in enumerate(estimated_templates):
        object_name = readable_output_name(
            str(record["path"]),
            _ESTIMATED_TEMPLATE_MARKER,
        )
        add_output_vtk_artifact(
            "estimated-template" if index == 0 else f"estimated-template-{index + 1}",
            f"Estimated atlas template: {object_name}",
            record,
            "Final Deformetrica atlas template from the immutable output inventory.",
        )

    reconstructions = sorted(
        (
            record
            for record in report.inventory
            if str(record["path"]).lower().endswith(".vtk")
            and _RECONSTRUCTION_MARKER in PurePosixPath(str(record["path"])).name
        ),
        key=lambda record: str(record["path"]),
    )
    reconstruction_keys: dict[str, str] = {}
    for index, record in enumerate(reconstructions, start=1):
        subject_filename = _reconstruction_subject_name(str(record["path"]))
        subject_name = subject_filename.removesuffix(".vtk").replace("_", " ")
        key = f"subject-reconstruction-{index}"
        add_output_vtk_artifact(
            key,
            f"Subject reconstruction: {subject_name}",
            record,
            "Final subject-specific reconstruction for visual registration quality control.",
        )
        reconstruction_keys[subject_filename] = key

    original_keys: dict[str, str] = {}
    subject_input_records = sorted(
        (
            record
            for record in report.manifest.get("inputs", [])
            if isinstance(record, Mapping) and record.get("role") == "subject"
        ),
        key=lambda record: str(record.get("staged_path", "")).casefold(),
    )
    for index, record in enumerate(subject_input_records, start=1):
        subject_filename = PurePosixPath(str(record["staged_path"])).name
        key = f"subject-original-{index}"
        add_staged_input_artifact(
            key,
            (
                "Subject original: "
                + subject_filename.removesuffix(".vtk").replace("_", " ")
            ),
            record,
        )
        original_keys[subject_filename] = key

    registration_qc: tuple[RegistrationQCItem, ...] = ()
    if qc_metrics is not None:
        ranked = sorted(
            qc_metrics.subject_residual_p95,
            key=lambda item: (-item[1], item[0].casefold()),
        )
        missing = [
            subject
            for subject, _residual in ranked
            if subject not in original_keys or subject not in reconstruction_keys
        ]
        if missing:
            raise ModernResultReviewError(
                "Registration QC could not bind originals and reconstructions for: "
                + ", ".join(missing)
            )
        registration_qc = tuple(
            RegistrationQCItem(
                rank=index,
                subject_name=subject,
                residual_p95=float(residual),
                original_artifact_key=original_keys[subject],
                reconstruction_artifact_key=reconstruction_keys[subject],
            )
            for index, (subject, residual) in enumerate(ranked, start=1)
        )

    inputs = manifest["inputs"]
    pca = manifest["pca"]
    optimization_evidence = manifest["optimization"]
    add_artifact(
        "reference-momenta",
        "Deformetrica momenta (raw TXT)",
        inputs["momenta"]["copied_path"],
        "txt",
        "Exact source parameter file, preserved byte-for-byte.",
    )
    add_artifact(
        "reference-control-points",
        "Deformetrica control points (raw TXT)",
        inputs["control_points"]["copied_path"],
        "txt",
        "Exact source control-point file, preserved byte-for-byte.",
    )
    for key, label, path, kind, description in (
        (
            "reference-momenta-table",
            "Momenta with subject identity (CSV)",
            "parameters/momenta.csv",
            "csv",
            "Open table preserving subject, control-point, and XYZ order.",
        ),
        (
            "reference-control-points-table",
            "Control points (CSV)",
            "parameters/control-points.csv",
            "csv",
            "Open indexed Cartesian control-point table.",
        ),
        (
            "reference-convergence",
            "Deformetrica objective history (CSV)",
            optimization_evidence["convergence"]["copied_path"],
            "csv",
            "Exact captured iteration, log-likelihood, attachment, and regularity table.",
        ),
        (
            "reference-terminal-log",
            "Deformetrica terminal log (TXT)",
            optimization_evidence["terminal_log"]["copied_path"],
            "txt",
            "Captured terminal log used to classify the reported optimizer stop signal.",
        ),
        (
            "optimizer-convergence-plot",
            "Deformetrica objective history (SVG)",
            optimization_evidence["plot_path"],
            "svg",
            "Deterministically regenerated view of the captured objective history.",
        ),
        (
            "pca-summary",
            f"{pca['method']} summary (JSON)",
            pca["summary_path"],
            "json",
            "Method, feature order, rank, variance, and sign convention.",
        ),
        (
            "pca-scores",
            f"{pca['method']} scores (CSV)",
            pca["scores_path"],
            "csv",
            "All subject scores in immutable manifest order.",
        ),
        (
            "pca-loadings",
            f"{pca['method']} loadings (CSV)",
            pca["loadings_path"],
            "csv",
            "Component loadings for every control-point/Cartesian feature.",
        ),
        (
            "pca-scree",
            f"{pca['method']} scree plot (SVG)",
            pca["plots"]["scree_path"],
            "svg",
            "Static explained-variance plot from the recomputed PCA.",
        ),
        (
            "pca-score-plot",
            f"{pca['method']}: PC1 vs PC2 (SVG)",
            pca["plots"]["scores_path"],
            "svg",
            "Static subject score plot with explained variance on both axes.",
        ),
    ):
        add_artifact(key, label, path, kind, description)
    secondary = pca["plots"]["scores_pc2_pc3_path"]
    if secondary is not None:
        add_artifact(
            "pca-score-plot-pc2-pc3",
            f"{pca['method']}: PC2 vs PC3 (SVG)",
            secondary,
            "svg",
            "Static secondary score plot from the same verified PCA matrix.",
        )
    if deformation_result is not None:
        deformation_inventory = {
            str(record["path"]): record
            for record in deformation_result["artifacts"]
            if isinstance(record, Mapping)
        }
        result_manifest_record = deformation_inventory.get(PCA_DEFORMATION_RESULT_NAME)
        if result_manifest_record is not None:
            raise ModernResultReviewError(
                "Reference PCA deformation result inventories its own manifest"
            )
        for endpoint in deformation_result["endpoints"]:
            if not isinstance(endpoint, Mapping):
                raise ModernResultReviewError(
                    "Reference PCA deformation endpoint record is invalid"
                )
            relative = str(endpoint["path"])
            record = deformation_inventory.get(relative)
            if record is None:
                raise ModernResultReviewError(
                    f"Reference PCA deformation endpoint is not inventoried: {relative}"
                )
            path = deformation_result_directory.joinpath(*PurePosixPath(relative).parts)
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != int(endpoint["bytes"])
                or sha256_file(path) != str(endpoint["sha256"])
            ):
                raise ModernResultReviewError(
                    f"Reference PCA deformation endpoint changed: {relative}"
                )
            role = str(endpoint["role"])
            if role == "mean":
                key = "pca-mean-shape"
                label = "PCA mean-momenta shape (Deformetrica VTK)"
            else:
                component = int(endpoint["component"])
                direction = str(endpoint["direction"])
                key = f"pc{component}-{direction}"
                sign = "−" if direction == "minus" else "+"
                result_shooting = deformation_result["shooting"]
                if not isinstance(result_shooting, Mapping):
                    raise ModernResultReviewError(
                        "Reference PCA deformation Shooting summary is invalid"
                    )
                rendered_distance = f"{float(result_shooting['standard_deviations']):g}"
                label = (
                    f"PC{component} {sign}{rendered_distance} SD "
                    "(Deformetrica VTK)"
                )
            artifacts.append(
                ModernResultArtifact(
                    key,
                    label,
                    path.resolve(),
                    "vtk",
                    int(endpoint["bytes"]),
                    str(endpoint["sha256"]),
                    "Verified final-timepoint surface from Deformetrica compute Shooting.",
                )
            )

    ratios = tuple(float(value) for value in verified.pca.explained_variance_ratio)
    backend = report.manifest["backend"]
    result = report.result
    configured_max = int(optimization_evidence["configured_maximum_iterations"])
    final_iteration = int(optimization_evidence["last_observed_iteration"])
    observations = int(optimization_evidence["observations"])
    duration_seconds = float(optimization_evidence["duration_seconds"])
    total_output_bytes = sum(int(record["bytes"]) for record in report.inventory)
    passed_checks = sum(check.status == "pass" for check in report.checks)
    project_name = str(report.manifest["project"]["name"])
    units = str(report.manifest["effective_config"]["input"]["units"])
    overview = (
        ResultReviewItem("Project", project_name, "Name stored in the immutable run manifest."),
        ResultReviewItem(
            "Engine",
            f"Deformetrica reference · contract {backend['contract_version']}",
            "External reference engine route that generated the atlas parameters.",
        ),
        ResultReviewItem(
            "Dataset",
            f"{inputs['subjects']} subjects · {units}",
            "Subject count and declared coordinate unit bound before execution.",
        ),
        ResultReviewItem(
            "Parameter space",
            f"{inputs['control_point_count']} control points · {inputs['dimension']}D",
            "Dimensions declared by the Deformetrica momenta header and cross-checked.",
        ),
        ResultReviewItem(
            "PCA method",
            str(manifest["pca"]["method"])
            + (
                " — default"
                if str(manifest["pca"]["method_id"])
                == "lddmm_deformation_kernel_pca"
                else ""
            ),
            (
                "The method and metric are stored in the verified PCA bundle; generic RBF "
                "KernelPCA is not substituted silently."
            ),
        ),
    )
    optimization = (
        ResultReviewItem(
            "Execution",
            f"completed · return code {result['return_code']}",
            "Terminal engine execution state independently verified by the parent.",
        ),
        ResultReviewItem(
            "Observed iterations",
            f"{observations} logged states · last iteration {final_iteration} "
            f"of maximum {configured_max}",
            "The maximum is an upper limit, not a convergence target.",
        ),
        ResultReviewItem(
            "Duration",
            _format_duration(duration_seconds),
            "Measured wall-clock duration stored in terminal run evidence.",
        ),
        ResultReviewItem(
            "Reported stop signal",
            str(optimization_evidence["reported_stop_signal"]).replace("_", " "),
            str(optimization_evidence["stop_interpretation"]),
        ),
        ResultReviewItem(
            "Final plotted state",
            f"last logged iteration {final_iteration}",
            str(optimization_evidence["final_state_visibility"]),
        ),
    )
    quality_items = [
        ResultReviewItem(
            "Run evidence",
            f"{passed_checks} of {len(report.checks)} checks passed",
            "Manifest, event, inventory, result, and actual output-file integrity checks.",
        ),
        ResultReviewItem(
            "Deformetrica outputs",
            f"{len(report.inventory)} files · {_format_bytes(total_output_bytes)}",
            "Exact terminal output inventory; unlisted files cause verification failure.",
        ),
        ResultReviewItem(
            "PCA snapshot",
            f"{len(manifest['artifacts'])} files",
            "Copied raw parameters, open tables, static plots, hashes, and recomputation contract.",
        ),
    ]
    quality_items.append(
        ResultReviewItem(
            "Reference PCA deformation meshes",
            (
                f"{len(deformation_result['endpoints'])} verified Shooting endpoints"
                if deformation_result is not None
                else "not generated"
            ),
            (
                "Mean and ±PC surfaces were generated by the source Deformetrica runtime."
                if deformation_result is not None
                else "Create and execute a prospective reference PCA Shooting design to add them."
            ),
        )
    )
    if qc_metrics is not None:
        quality_items.extend(
            (
                ResultReviewItem(
                    "Full-cohort registration QC",
                    (
                        f"{len(registration_qc)} subjects ranked · pooled p95 "
                        f"{qc_metrics.residual_p95:.6g} · median "
                        f"{qc_metrics.residual_median:.6g}"
                    ),
                    "Symmetric nearest-vertex distances are a geometric QC proxy, not "
                    "the configured Deformetrica attachment metric.",
                ),
                ResultReviewItem(
                    "Topology and area-change evidence",
                    (
                        f"{qc_metrics.invalid_face_count} invalid faces · area-change "
                        f"p95 {qc_metrics.distortion_p95:.6g}"
                    ),
                    "Large biologically necessary deformation is not a failure by itself; "
                    "invalid faces and implausible correspondence remain failure evidence.",
                ),
            )
        )
    else:
        quality_items.append(
            ResultReviewItem(
                "Full-cohort registration QC",
                "unavailable",
                qc_unavailable_reason or "No complete subject reconstruction set was found.",
            )
        )
    quality = tuple(quality_items)
    workflow_manifest = run / "manifest.json"
    bundle_manifest = bundle_directory / REFERENCE_PCA_MANIFEST
    return ModernResultReview(
        run_directory=run,
        bundle_directory=bundle_directory,
        project_name=project_name,
        created_at=str(manifest["created_at"]),
        workflow_manifest_path=workflow_manifest,
        workflow_manifest_sha256=sha256_file(workflow_manifest),
        bundle_manifest_path=bundle_manifest,
        bundle_manifest_sha256=sha256_file(bundle_manifest),
        optimizer_converged=None,
        optimizer_termination_reason=str(optimization_evidence["reported_stop_signal"]),
        optimizer_cycles_completed=final_iteration,
        optimizer_max_cycles=configured_max,
        overview=overview,
        optimization=optimization,
        pca=_pca_items(manifest, ratios),
        quality=quality,
        artifacts=tuple(artifacts),
        scientific_boundaries=(
            str(manifest["scientific_boundary"]),
            "A completed Deformetrica process and improving objective do not by themselves "
            "establish adequate registration or optimizer convergence.",
            "The linear momenta PCA is descriptive and does not establish taxonomic, "
            "biological, group-separation, or causal claims.",
            "Registration-QC ranking prioritizes inspection; a high residual may reflect "
            "a real biological extreme, underfit, or both and is not an exclusion rule.",
        ),
        pca_pc2_pc3_unavailable_reason=(
            None
            if secondary is not None
            else str(pca["plots"]["scores_pc2_pc3_unavailable_reason"])
        ),
        engine_route="deformetrica_reference",
        pca_method_id=str(pca["method_id"]),
        pca_method_label=(
            str(pca["method"])
            + (
                " — default"
                if str(pca["method_id"]) == "lddmm_deformation_kernel_pca"
                else ""
            )
        ),
        execution_duration_seconds=duration_seconds,
        optimizer_stop_interpretation=str(optimization_evidence["stop_interpretation"]),
        additional_artifact_roots=(
            output_directory.resolve(),
            staged_input_directory.resolve(),
            *(
                (deformation_result_directory.resolve(),)
                if deformation_result is not None
                else ()
            ),
        ),
        additional_manifest_bindings=(
            (
                (
                    deformation_result_directory / PCA_DEFORMATION_RESULT_NAME,
                    sha256_file(
                        deformation_result_directory / PCA_DEFORMATION_RESULT_NAME
                    ),
                ),
            )
            if deformation_result is not None
            else ()
        ),
        registration_qc=registration_qc,
    )

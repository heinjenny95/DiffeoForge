"""Immutable fixed-template registration of Validation Lab holdout subjects."""

from __future__ import annotations

import copy
import html
import json
import os
import shutil
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from uuid import uuid4

import numpy as np
import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import validate_input_paths, validate_schema
from diffeoforge.desktop.reference_execution_controller import (
    ReferenceExecutionController,
    ReferenceExecutionControllerResult,
)
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_validation import (
    ReferenceValidationError,
    ValidationRunEvidence,
)
from diffeoforge.reference_validation_metrics import (
    collect_reference_validation_run_evidence,
)
from diffeoforge.reference_validation_study import (
    ValidationStudyRunState,
    _append_event,
    _copy_bound,
    _evidence_from_manifest,
    _link_or_copy_bound,
    _load_events,
    _relative,
    _safe_path,
    load_reference_validation_study,
)
from diffeoforge.reference_validation_study import (
    _verify_manifest as _verify_parent_manifest,
)
from diffeoforge.result_report import collect_run_report

HOLDOUT_STUDY_VERSION = "0.1"
HOLDOUT_DIRECTORY_NAME = "heldout-confirmation"
HOLDOUT_MANIFEST = "holdout-study.json"
HOLDOUT_DIGEST = "holdout-study.sha256"
HOLDOUT_REPORT_JSON = "report/holdout-report.json"
HOLDOUT_REPORT_HTML = "report/holdout-report.html"
HoldoutEventCallback = Callable[[Mapping[str, object]], None]


class ReferenceHoldoutStudyError(ReferenceValidationError):
    """Raised when fixed-template holdout evidence is invalid."""


class _Controller(Protocol):
    def run(
        self,
        *,
        event_callback: Callable[[DesktopReferenceWorkerEvent], None] | None = None,
    ) -> ReferenceExecutionControllerResult: ...

    def request_cancel(self) -> bool: ...


ControllerFactory = Callable[[DesktopReferenceLaunchRequest], _Controller]


def _canonical_json(value: object, *, indent: int | None = None) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":") if indent is None else None,
        indent=indent,
        ensure_ascii=False,
        allow_nan=False,
    ) + ("\n" if indent is not None else "")


def _write_json(path: Path, value: object, *, overwrite: bool) -> None:
    write_text_safely(path, _canonical_json(value, indent=2), overwrite=overwrite)


def _write_yaml(path: Path, value: Mapping[str, Any]) -> None:
    write_text_safely(
        path,
        yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=True),
        overwrite=False,
    )


def _safe_output_artifact(run_directory: Path, record: Mapping[str, object]) -> Path:
    relative = PurePosixPath(str(record.get("path", "")))
    if (
        relative.is_absolute()
        or not relative.parts
        or "." in relative.parts
        or ".." in relative.parts
    ):
        raise ReferenceHoldoutStudyError(
            f"Training output inventory contains an unsafe path: {relative}"
        )
    output = (run_directory / "output").resolve()
    candidate = output.joinpath(*relative.parts).resolve()
    if not candidate.is_relative_to(output) or not candidate.is_file():
        raise ReferenceHoldoutStudyError(f"Training output artifact is missing: {relative}")
    if candidate.stat().st_size != int(record["bytes"]):
        raise ReferenceHoldoutStudyError(f"Training output artifact size differs: {candidate}")
    if sha256_file(candidate) != str(record["sha256"]):
        raise ReferenceHoldoutStudyError(f"Training output artifact checksum differs: {candidate}")
    return candidate


def _trained_model_artifacts(
    run_directory: Path,
) -> tuple[Path, str, Path, str, str, str]:
    report = collect_run_report(run_directory)
    templates = [
        record
        for record in report.inventory
        if "__EstimatedParameters__Template_" in PurePosixPath(str(record["path"])).name
        and str(record["path"]).casefold().endswith(".vtk")
    ]
    control_points = [
        record
        for record in report.inventory
        if "__estimatedparameters__controlpoints" in str(record["path"]).casefold()
        and str(record["path"]).casefold().endswith(".txt")
    ]
    if len(templates) != 1 or len(control_points) != 1:
        raise ReferenceHoldoutStudyError(
            "Each training-confirmation run must contain exactly one estimated "
            "template and one estimated control-points file"
        )
    template = _safe_output_artifact(run_directory, templates[0])
    points = _safe_output_artifact(run_directory, control_points[0])
    return (
        template,
        str(templates[0]["sha256"]),
        points,
        str(control_points[0]["sha256"]),
        str(templates[0]["path"]),
        str(control_points[0]["path"]),
    )


def _holdout_configuration(
    source: Mapping[str, Any],
    *,
    config_directory: Path,
    template_copy: Path,
    control_points_copy: Path,
    cohort_directory: Path,
    finalist_id: str,
    maximum_iterations: int,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(source))
    config["project"]["name"] = f"{source['project']['name']} fixed-template holdout {finalist_id}"
    config["input"]["directory"] = os.path.relpath(cohort_directory, config_directory).replace(
        "\\", "/"
    )
    config["input"]["template"] = os.path.relpath(template_copy, config_directory).replace(
        "\\", "/"
    )
    config["input"]["subject_pattern"] = "*.vtk"
    config["model"]["deformation"]["initial_control_points"] = os.path.relpath(
        control_points_copy, config_directory
    ).replace("\\", "/")
    config["optimization"]["freeze_template"] = True
    config["optimization"]["freeze_control_points"] = True
    config["optimization"]["max_iterations"] = maximum_iterations
    config["output"]["directory"] = "./runs"
    validate_schema(config)
    return config


@dataclass(frozen=True)
class HoldoutFinalistAssessment:
    finalist_id: str
    subject_win_count: int
    subject_win_fraction: float
    median_subject_residual_p95: float | None
    pooled_residual_p95: float | None
    distortion_p95: float | None
    rejection_reasons: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "finalist_id": self.finalist_id,
            "subject_win_count": self.subject_win_count,
            "subject_win_fraction": self.subject_win_fraction,
            "median_subject_residual_p95": self.median_subject_residual_p95,
            "pooled_residual_p95": self.pooled_residual_p95,
            "distortion_p95": self.distortion_p95,
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True)
class ReferenceHoldoutAssessment:
    status: str
    preferred_finalist_id: str | None
    subject_support: float | None
    training_preferred_finalist_id: str | None
    agrees_with_training_preference: bool | None
    practical_error_margin: float
    practical_error_margin_basis: str
    subject_count: int
    finalists: tuple[HoldoutFinalistAssessment, ...]
    warnings: tuple[str, ...]
    next_gates: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "status": self.status,
            "preferred_finalist_id": self.preferred_finalist_id,
            "subject_support": self.subject_support,
            "training_preferred_finalist_id": self.training_preferred_finalist_id,
            "agrees_with_training_preference": self.agrees_with_training_preference,
            "practical_error_margin": self.practical_error_margin,
            "practical_error_margin_basis": self.practical_error_margin_basis,
            "subject_count": self.subject_count,
            "finalists": [item.as_manifest() for item in self.finalists],
            "warnings": list(self.warnings),
            "next_gates": list(self.next_gates),
        }


@dataclass(frozen=True)
class ReferenceHoldoutStudySnapshot:
    study_directory: Path
    study_id: str
    parent_study_directory: Path
    parent_study_id: str
    heldout_subjects: tuple[str, ...]
    finalist_ids: tuple[str, ...]
    status: str
    runs: tuple[ValidationStudyRunState, ...]
    event_count: int
    assessment: ReferenceHoldoutAssessment | None
    report_json_path: Path | None
    report_html_path: Path | None

    @property
    def completed_run_count(self) -> int:
        return sum(run.status == "completed" for run in self.runs)


def _practical_margin(parent_snapshot: object) -> tuple[float, str]:
    plan = parent_snapshot.plan
    if plan.smallest_relevant_feature is not None:
        return (
            float(plan.smallest_relevant_feature) * 0.05,
            "5% of the researcher-declared smallest relevant feature",
        )
    return (
        float(plan.template_diagonal) * 0.005,
        "0.5% of template diagonal; a numerical fallback, not a biological threshold",
    )


def assess_reference_holdout(
    manifest: Mapping[str, Any],
    evidence: tuple[ValidationRunEvidence, ...],
) -> ReferenceHoldoutAssessment:
    finalist_records = tuple(manifest["finalists"])
    finalist_ids = tuple(str(item["finalist_id"]) for item in finalist_records)
    subjects = tuple(str(name) for name in manifest["heldout_subjects"])
    expected_runs = {
        str(record["run_id"]): str(record["finalist_id"]) for record in manifest["runs"]
    }
    supplied: dict[str, ValidationRunEvidence] = {}
    for item in evidence:
        if item.run_id not in expected_runs or item.finalist_id != expected_runs[item.run_id]:
            raise ReferenceHoldoutStudyError(
                f"Holdout evidence identity differs from the frozen design: {item.run_id}"
            )
        if item.run_id in supplied:
            raise ReferenceHoldoutStudyError(f"Duplicate holdout evidence: {item.run_id}")
        supplied[item.run_id] = item
    margin = float(manifest["practical_error_margin"])
    basis = str(manifest["practical_error_margin_basis"])
    valid: dict[str, ValidationRunEvidence] = {}
    reasons: dict[str, list[str]] = {item: [] for item in finalist_ids}
    for run_id, finalist_id in expected_runs.items():
        item = supplied.get(run_id)
        rejection = None
        if item is None:
            rejection = "run is missing"
        elif not item.completed:
            rejection = "run did not complete"
        elif not item.converged:
            rejection = "optimizer convergence was not evidenced"
        elif item.invalid_face_count:
            rejection = f"{item.invalid_face_count} invalid faces"
        elif item.external_residual_p95 is None or item.distortion_p95 is None:
            rejection = "external comparison metrics are incomplete"
        elif set(dict(item.subject_residual_p95)) != set(subjects):
            rejection = "per-subject residuals do not match the heldout cohort"
        if rejection is not None:
            reasons[finalist_id].append(rejection)
        else:
            valid[finalist_id] = item

    wins: Counter[str] = Counter()
    finalist_values = {
        str(item["finalist_id"]): item["parameter_values"] for item in finalist_records
    }
    if len(valid) == len(finalist_ids):
        residuals = {
            finalist_id: dict(item.subject_residual_p95) for finalist_id, item in valid.items()
        }
        for subject in subjects:
            best = min(float(residuals[item][subject]) for item in finalist_ids)
            equivalent = [
                item for item in finalist_ids if float(residuals[item][subject]) <= best + margin
            ]
            best_distortion = min(float(valid[item].distortion_p95) for item in equivalent)
            distortion_equivalent = [
                item
                for item in equivalent
                if float(valid[item].distortion_p95)
                <= best_distortion + max(best_distortion * 0.02, 1e-12)
            ]
            winner = max(
                distortion_equivalent,
                key=lambda item: (
                    float(finalist_values[item]["deformation_kernel_width"]),
                    item,
                ),
            )
            wins[winner] += 1

    assessments: list[HoldoutFinalistAssessment] = []
    for finalist_id in finalist_ids:
        item = valid.get(finalist_id)
        subject_values = (
            [float(value) for _, value in item.subject_residual_p95] if item is not None else []
        )
        assessments.append(
            HoldoutFinalistAssessment(
                finalist_id=finalist_id,
                subject_win_count=wins[finalist_id],
                subject_win_fraction=(wins[finalist_id] / len(subjects) if subjects else 0.0),
                median_subject_residual_p95=(
                    float(np.median(subject_values)) if subject_values else None
                ),
                pooled_residual_p95=(None if item is None else item.external_residual_p95),
                distortion_p95=None if item is None else item.distortion_p95,
                rejection_reasons=tuple(reasons[finalist_id]),
            )
        )
    ranked = sorted(
        assessments,
        key=lambda item: (-item.subject_win_count, item.finalist_id),
    )
    winner = ranked[0] if ranked and ranked[0].subject_win_count else None
    support = winner.subject_win_fraction if winner is not None else None
    training_winner = manifest["parent"]["training_preferred_finalist_id"]
    agrees = (
        None if winner is None or training_winner is None else winner.finalist_id == training_winner
    )
    all_valid = len(valid) == len(finalist_ids)
    warnings: list[str] = []
    if not all_valid:
        status = "failed_validity_gate"
        warnings.append(
            "At least one fixed-template registration failed a completeness, "
            "convergence, geometry, or common-metric gate."
        )
    elif winner is None or support is None or support < 0.60:
        status = "ambiguous_on_holdout"
        warnings.append("No finalist won at least 60% of the paired heldout-subject comparisons.")
    elif support < 0.80:
        status = "sensitive_on_holdout"
        warnings.append(
            "The heldout preference is present but below the predeclared 80% robust-support gate."
        )
    elif training_winner is None:
        status = "heldout_preference_identified"
        warnings.append(
            "The training comparison had no unique robust winner, so the heldout "
            "preference cannot be described as confirmation of a prior winner."
        )
    elif agrees:
        status = "confirmed_on_holdout"
    else:
        status = "training_preference_not_confirmed"
        warnings.append(
            "The fixed-template holdout preferred a different finalist than the "
            "training/resampling comparison."
        )
    if "numerical fallback" in basis:
        warnings.append(
            "No biological equivalence margin was supplied; the numerical fallback "
            "must not be described as an anatomical threshold."
        )
    return ReferenceHoldoutAssessment(
        status=status,
        preferred_finalist_id=None if winner is None else winner.finalist_id,
        subject_support=support,
        training_preferred_finalist_id=(None if training_winner is None else str(training_winner)),
        agrees_with_training_preference=agrees,
        practical_error_margin=margin,
        practical_error_margin_basis=basis,
        subject_count=len(subjects),
        finalists=tuple(assessments),
        warnings=tuple(warnings),
        next_gates=(
            "Independent anatomy-specific validation that was not used for GPA, "
            "pilot selection, or this geometric holdout comparison.",
            "A final full-cohort atlas using parameters locked after scientific review.",
        ),
    )


def create_reference_holdout_study(
    parent_study_directory: Path | str,
    *,
    maximum_iterations: int | None = None,
) -> ReferenceHoldoutStudySnapshot:
    """Freeze three fixed-template holdout runs without starting a process."""

    parent_root = Path(parent_study_directory).expanduser().resolve()
    parent_snapshot = load_reference_validation_study(parent_root)
    if parent_snapshot.status != "completed" or parent_snapshot.assessment is None:
        raise ReferenceHoldoutStudyError(
            "Fixed-template holdout requires a completed Validation Lab training study"
        )
    parent_manifest = _verify_parent_manifest(parent_root)
    root = parent_root / HOLDOUT_DIRECTORY_NAME
    if root.exists():
        raise ReferenceHoldoutStudyError(f"Holdout study destination already exists: {root}")
    iterations = (
        int(parent_manifest["maximum_iterations"])
        if maximum_iterations is None
        else maximum_iterations
    )
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ReferenceHoldoutStudyError("maximum_iterations must be positive")
    margin, margin_basis = _practical_margin(parent_snapshot)
    parent_report = parent_snapshot.report_json_path
    if parent_report is None:
        raise ReferenceHoldoutStudyError("Parent validation report is absent")

    root.mkdir(parents=True)
    try:
        parent_subjects = {
            str(record["filename"]): record for record in parent_manifest["inputs"]["subjects"]
        }
        cohort_directory = root / "inputs" / "heldout-subjects"
        subject_records: list[dict[str, object]] = []
        for name in parent_snapshot.plan.heldout_subjects:
            record = parent_subjects[name]
            source = _safe_path(parent_root, record["copy"])
            destination = cohort_directory / name
            _link_or_copy_bound(source, destination, str(record["sha256"]))
            subject_records.append(
                {
                    "filename": name,
                    "copy": _relative(root, destination),
                    "sha256": str(record["sha256"]),
                }
            )

        finalist_by_id = {
            finalist.finalist_id: finalist for finalist in parent_snapshot.plan.finalists
        }
        training_runs = {
            run.finalist_id: run
            for run in parent_snapshot.runs
            if run.cohort_id == "training-confirmation"
        }
        model_records: list[dict[str, object]] = []
        run_records: list[dict[str, object]] = []
        for finalist_id, _finalist in finalist_by_id.items():
            training = training_runs.get(finalist_id)
            if training is None or training.run_directory is None or training.status != "completed":
                raise ReferenceHoldoutStudyError(
                    f"Completed training-confirmation run is absent for {finalist_id}"
                )
            (
                template_source,
                template_hash,
                points_source,
                points_hash,
                template_output_path,
                points_output_path,
            ) = _trained_model_artifacts(training.run_directory)
            model_directory = root / "inputs" / "trained-models" / finalist_id
            template_copy = model_directory / "estimated-template.vtk"
            points_copy = model_directory / "estimated-control-points.txt"
            _copy_bound(template_source, template_copy, template_hash)
            _copy_bound(points_source, points_copy, points_hash)
            model_records.append(
                {
                    "finalist_id": finalist_id,
                    "training_run_id": training.run_id,
                    "training_run_directory": str(training.run_directory),
                    "training_result_sha256": sha256_file(training.run_directory / "result.json"),
                    "training_output_inventory_sha256": sha256_file(
                        training.run_directory / "output-inventory.json"
                    ),
                    "template": {
                        "source_output_path": template_output_path,
                        "copy": _relative(root, template_copy),
                        "sha256": template_hash,
                    },
                    "control_points": {
                        "source_output_path": points_output_path,
                        "copy": _relative(root, points_copy),
                        "sha256": points_hash,
                    },
                }
            )
            source_config = yaml.safe_load(training.config_path.read_text(encoding="utf-8"))
            run_id = f"fixed-template-holdout--{finalist_id}"
            config_directory = root / "run-specs" / run_id
            config_directory.mkdir(parents=True)
            config = _holdout_configuration(
                source_config,
                config_directory=config_directory,
                template_copy=template_copy,
                control_points_copy=points_copy,
                cohort_directory=cohort_directory,
                finalist_id=finalist_id,
                maximum_iterations=iterations,
            )
            config_path = config_directory / "atlas.yaml"
            _write_yaml(config_path, config)
            summary = validate_input_paths(config, config_path)
            if tuple(path.name for path in summary.subjects) != tuple(
                sorted(parent_snapshot.plan.heldout_subjects, key=str.casefold)
            ):
                raise ReferenceHoldoutStudyError(
                    "Frozen holdout configuration does not select the exact reserved cohort"
                )
            run_records.append(
                {
                    "run_id": run_id,
                    "finalist_id": finalist_id,
                    "cohort_id": "fixed-template-holdout",
                    "config": _relative(root, config_path),
                    "config_sha256": sha256_file(config_path),
                }
            )

        manifest = {
            "holdout_study_version": HOLDOUT_STUDY_VERSION,
            "study_id": f"reference-holdout-{uuid4().hex[:12]}",
            "parent": {
                "study_directory": str(parent_root),
                "study_id": parent_snapshot.study_id,
                "plan_fingerprint": parent_snapshot.plan.fingerprint,
                "manifest_sha256": sha256_file(parent_root / "validation-study.json"),
                "report_json_sha256": sha256_file(parent_report),
                "training_status": parent_snapshot.assessment.status,
                "training_preferred_finalist_id": (
                    parent_snapshot.assessment.recommended_finalist_id
                ),
            },
            "maximum_iterations": iterations,
            "launcher": parent_manifest["launcher"],
            "heldout_subjects": list(parent_snapshot.plan.heldout_subjects),
            "subjects": subject_records,
            "finalists": [item.as_manifest() for item in parent_snapshot.plan.finalists],
            "trained_models": model_records,
            "runs": run_records,
            "practical_error_margin": margin,
            "practical_error_margin_basis": margin_basis,
            "selection_rule": [
                "Reject incomplete, nonconverged, or geometrically invalid registrations.",
                "Compare every finalist on every identical heldout subject using "
                "symmetric vertex-to-triangle surface-distance p95.",
                "Treat errors within the predeclared practical margin as equivalent; "
                "then prefer lower pooled distortion and finally the smoother model.",
                "Require at least 80% paired heldout-subject support for robust evidence.",
            ],
            "scientific_boundary": (
                "Templates and control points are copied from completed training-only "
                "runs and frozen. Only heldout-subject momenta are estimated. This is "
                "out-of-sample geometric registration evidence, not proof of biological "
                "homology or a universal parameter optimum."
            ),
        }
        _write_json(root / HOLDOUT_MANIFEST, manifest, overwrite=False)
        write_text_safely(
            root / HOLDOUT_DIGEST,
            sha256_file(root / HOLDOUT_MANIFEST) + "\n",
            overwrite=False,
        )
        _append_event(
            root,
            "study_created",
            {
                "study_id": manifest["study_id"],
                "parent_study_id": parent_snapshot.study_id,
                "manifest_sha256": sha256_file(root / HOLDOUT_MANIFEST),
                "run_count": len(run_records),
                "heldout_subject_count": len(subject_records),
            },
        )
    except BaseException:
        if root.is_dir():
            shutil.rmtree(root)
        raise
    return load_reference_holdout_study(root)


def _verify_manifest(root: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((root / HOLDOUT_MANIFEST).read_text(encoding="utf-8"))
        expected = (root / HOLDOUT_DIGEST).read_text(encoding="utf-8").strip()
    except (OSError, json.JSONDecodeError) as error:
        raise ReferenceHoldoutStudyError(f"Could not read holdout manifest: {error}") from error
    if manifest.get("holdout_study_version") != HOLDOUT_STUDY_VERSION:
        raise ReferenceHoldoutStudyError(
            f"Unsupported holdout study version: {manifest.get('holdout_study_version')}"
        )
    if sha256_file(root / HOLDOUT_MANIFEST) != expected:
        raise ReferenceHoldoutStudyError("Holdout study manifest SHA-256 differs")
    parent_root = Path(manifest["parent"]["study_directory"]).expanduser().resolve()
    parent_snapshot = load_reference_validation_study(parent_root)
    if parent_snapshot.study_id != manifest["parent"]["study_id"]:
        raise ReferenceHoldoutStudyError("Parent Validation Lab identity differs")
    if sha256_file(parent_root / "validation-study.json") != manifest["parent"]["manifest_sha256"]:
        raise ReferenceHoldoutStudyError("Parent Validation Lab manifest changed")
    if (
        parent_snapshot.report_json_path is None
        or sha256_file(parent_snapshot.report_json_path) != manifest["parent"]["report_json_sha256"]
    ):
        raise ReferenceHoldoutStudyError("Parent Validation Lab report changed")
    bound = [
        *manifest["subjects"],
        *(
            artifact
            for model in manifest["trained_models"]
            for artifact in (model["template"], model["control_points"])
        ),
        *manifest["runs"],
    ]
    for record in bound:
        key = "config" if "config" in record else "copy"
        digest_key = "config_sha256" if key == "config" else "sha256"
        path = _safe_path(root, record[key])
        if not path.is_file() or sha256_file(path) != record[digest_key]:
            raise ReferenceHoldoutStudyError(f"Holdout bound file changed or is absent: {path}")
    for model in manifest["trained_models"]:
        training_run = Path(model["training_run_directory"]).expanduser().resolve()
        if (
            sha256_file(training_run / "result.json") != model["training_result_sha256"]
            or sha256_file(training_run / "output-inventory.json")
            != model["training_output_inventory_sha256"]
        ):
            raise ReferenceHoldoutStudyError(
                f"Parent training-run evidence changed for {model['finalist_id']}"
            )
    return manifest


def load_reference_holdout_study(
    study_directory: Path | str,
) -> ReferenceHoldoutStudySnapshot:
    root = Path(study_directory).expanduser().resolve()
    if not root.is_dir():
        raise ReferenceHoldoutStudyError(f"Holdout study does not exist: {root}")
    manifest = _verify_manifest(root)
    events = _load_events(root)
    states: list[ValidationStudyRunState] = []
    for record in manifest["runs"]:
        run_id = str(record["run_id"])
        starts = [
            item for item in events if item["event"] == "run_started" and item["run_id"] == run_id
        ]
        terminals = [
            item
            for item in events
            if item["event"] in {"run_completed", "run_failed", "run_interrupted"}
            and item["run_id"] == run_id
        ]
        completed = [item for item in terminals if item["event"] == "run_completed"]
        orphaned = bool(
            starts and (not terminals or starts[-1]["sequence"] > terminals[-1]["sequence"])
        )
        latest = terminals[-1] if terminals else None
        if completed:
            status = "completed"
            evidence = _evidence_from_manifest(completed[-1]["evidence"])
            run_directory = _safe_path(root, completed[-1]["run_directory"])
            error = None
        elif orphaned:
            status = "orphaned"
            evidence = None
            run_directory = _safe_path(root, starts[-1]["run_directory"])
            error = "Previous process ended before recording a terminal event"
        elif latest is not None:
            status = "failed"
            evidence = None
            relative_run = latest.get("run_directory")
            run_directory = _safe_path(root, relative_run) if relative_run else None
            error = str(latest.get("error", "Holdout run failed"))
        else:
            status = "pending"
            evidence = None
            run_directory = None
            error = None
        states.append(
            ValidationStudyRunState(
                run_id=run_id,
                finalist_id=str(record["finalist_id"]),
                cohort_id="fixed-template-holdout",
                status=status,
                config_path=_safe_path(root, record["config"]),
                run_directory=run_directory,
                attempts=len(starts),
                evidence=evidence,
                error=error,
            )
        )
    completion = next(
        (item for item in reversed(events) if item["event"] == "study_completed"),
        None,
    )
    assessment = None
    report_json = None
    report_html = None
    if completion is not None:
        report_json = _safe_path(root, completion["report_json"])
        report_html = _safe_path(root, completion["report_html"])
        if (
            sha256_file(report_json) != completion["report_json_sha256"]
            or sha256_file(report_html) != completion["report_html_sha256"]
        ):
            raise ReferenceHoldoutStudyError("Holdout report bytes changed")
        assessment = assess_reference_holdout(
            manifest,
            tuple(run.evidence for run in states if run.evidence is not None),
        )
        status = "completed"
    elif any(run.status == "orphaned" for run in states):
        status = "interrupted"
    elif all(run.status == "completed" for run in states):
        status = "awaiting_report"
    elif any(run.status == "failed" for run in states):
        status = "ready_to_retry"
    else:
        status = "ready"
    return ReferenceHoldoutStudySnapshot(
        study_directory=root,
        study_id=str(manifest["study_id"]),
        parent_study_directory=Path(manifest["parent"]["study_directory"]).resolve(),
        parent_study_id=str(manifest["parent"]["study_id"]),
        heldout_subjects=tuple(str(name) for name in manifest["heldout_subjects"]),
        finalist_ids=tuple(str(item["finalist_id"]) for item in manifest["finalists"]),
        status=status,
        runs=tuple(states),
        event_count=len(events),
        assessment=assessment,
        report_json_path=report_json,
        report_html_path=report_html,
    )


def _report_payload(
    snapshot: ReferenceHoldoutStudySnapshot,
    manifest: Mapping[str, Any],
    assessment: ReferenceHoldoutAssessment,
) -> dict[str, object]:
    return {
        "report_version": "0.1",
        "study_id": snapshot.study_id,
        "parent_study_id": snapshot.parent_study_id,
        "status": assessment.status,
        "claim_scope": manifest["scientific_boundary"],
        "design": {
            "registration_mode": "fixed template and fixed control points",
            "heldout_subject_count": len(snapshot.heldout_subjects),
            "finalist_count": len(snapshot.finalist_ids),
            "run_count": len(snapshot.runs),
            "selection_rule": manifest["selection_rule"],
        },
        "assessment": assessment.as_manifest(),
        "runs": [run.evidence.as_manifest() for run in snapshot.runs if run.evidence is not None],
        "warnings": list(assessment.warnings),
        "required_next_gates": list(assessment.next_gates),
    }


def _report_html(report: Mapping[str, object]) -> str:
    assessment = report["assessment"]
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['finalist_id']))}</td>"
        f"<td>{int(item['subject_win_count'])}</td>"
        f"<td>{float(item['subject_win_fraction']):.1%}</td>"
        f"<td>{html.escape(str(item['median_subject_residual_p95']))}</td>"
        f"<td>{html.escape(str(item['pooled_residual_p95']))}</td>"
        f"<td>{html.escape(str(item['distortion_p95']))}</td>"
        f"<td>{html.escape('; '.join(item['rejection_reasons']) or 'none')}</td>"
        "</tr>"
        for item in assessment["finalists"]
    )
    warnings = (
        "".join(f"<li>{html.escape(str(item))}</li>" for item in report["warnings"])
        or "<li>No additional numerical warning was triggered.</li>"
    )
    gates = "".join(f"<li>{html.escape(str(item))}</li>" for item in report["required_next_gates"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DiffeoForge fixed-template holdout report</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1150px;margin:36px auto;
padding:0 24px;color:#103b3b;line-height:1.45}}h1,h2{{color:#073c3b}}
.notice{{background:#e3f6ef;border-left:5px solid #13856f;padding:14px 18px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #c8d9d7;
padding:9px;text-align:left;vertical-align:top}}th{{background:#eef5f4}}
code{{background:#eef5f4;padding:2px 5px}}</style></head><body>
<h1>Fixed-template heldout confirmation</h1>
<p class="notice"><strong>Status:</strong> {html.escape(str(report["status"]))}<br>
<strong>Heldout preference:</strong> {html.escape(str(assessment["preferred_finalist_id"]))}<br>
<strong>Paired subject support:</strong> {html.escape(str(assessment["subject_support"]))}</p>
<p><strong>Claim boundary:</strong> {html.escape(str(report["claim_scope"]))}</p>
<h2>Frozen design</h2><p>{report["design"]["heldout_subject_count"]} untouched subjects;
{report["design"]["finalist_count"]} frozen trained models; {report["design"]["run_count"]}
fixed-template registrations. Template and control points were not re-estimated.</p>
<p>Practical error margin: {assessment["practical_error_margin"]}
({html.escape(str(assessment["practical_error_margin_basis"]))}).</p>
<h2>Paired heldout comparison</h2><table><thead><tr><th>Finalist</th>
<th>Subject wins</th><th>Support</th><th>Median subject p95</th><th>Pooled p95</th>
<th>Distortion p95</th><th>Rejections</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Warnings</h2><ul>{warnings}</ul><h2>Evidence still required</h2><ol>{gates}</ol>
<p>Study: <code>{html.escape(str(report["study_id"]))}</code><br>Parent:
<code>{html.escape(str(report["parent_study_id"]))}</code></p></body></html>"""


def _finalize_study(root: Path) -> ReferenceHoldoutStudySnapshot:
    snapshot = load_reference_holdout_study(root)
    if snapshot.status == "completed":
        return snapshot
    if any(run.evidence is None for run in snapshot.runs):
        raise ReferenceHoldoutStudyError(
            "Holdout report requires every predeclared run to complete"
        )
    manifest = _verify_manifest(root)
    assessment = assess_reference_holdout(
        manifest,
        tuple(run.evidence for run in snapshot.runs if run.evidence is not None),
    )
    report = _report_payload(snapshot, manifest, assessment)
    json_path = root / HOLDOUT_REPORT_JSON
    html_path = root / HOLDOUT_REPORT_HTML
    json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(json_path, report, overwrite=False)
    write_text_safely(html_path, _report_html(report), overwrite=False)
    _append_event(
        root,
        "study_completed",
        {
            "assessment_status": assessment.status,
            "preferred_finalist_id": assessment.preferred_finalist_id,
            "report_json": _relative(root, json_path),
            "report_json_sha256": sha256_file(json_path),
            "report_html": _relative(root, html_path),
            "report_html_sha256": sha256_file(html_path),
        },
    )
    return load_reference_holdout_study(root)


def _launch_request(
    root: Path,
    manifest: Mapping[str, Any],
    state: ValidationStudyRunState,
) -> DesktopReferenceLaunchRequest:
    attempt = state.attempts + 1
    attempt_id = f"attempt-{attempt:02d}"
    destination = (state.config_path.parent / "runs" / attempt_id).resolve()
    launcher = manifest["launcher"]
    return DesktopReferenceLaunchRequest(
        request_id=f"holdout-{uuid4().hex}",
        config_path=state.config_path,
        destination=destination,
        run_id=attempt_id,
        expected_config_sha256=sha256_file(state.config_path),
        launcher_engine=launcher.get("engine"),
        launcher_image=launcher.get("image"),
        launcher_type=str(launcher["type"]),
        launcher_distribution=launcher.get("distribution"),
        launcher_executable=launcher.get("executable"),
    )


class ReferenceHoldoutStudyRunner:
    """Execute missing fixed-template holdout runs sequentially and resume safely."""

    def __init__(
        self,
        study_directory: Path | str,
        *,
        controller_factory: ControllerFactory = ReferenceExecutionController,
    ) -> None:
        self.study_directory = Path(study_directory).expanduser().resolve()
        self._controller_factory = controller_factory
        self._active_controller: _Controller | None = None
        self._cancel_requested = False

    def request_cancel(self) -> bool:
        if self._cancel_requested:
            return False
        self._cancel_requested = True
        if self._active_controller is not None:
            self._active_controller.request_cancel()
        return True

    def run_all(
        self,
        *,
        event_callback: HoldoutEventCallback | None = None,
    ) -> ReferenceHoldoutStudySnapshot:
        snapshot = load_reference_holdout_study(self.study_directory)
        if snapshot.status == "completed":
            return snapshot
        manifest = _verify_manifest(self.study_directory)
        for state in snapshot.runs:
            if state.status == "completed" or self._cancel_requested:
                continue
            request = _launch_request(self.study_directory, manifest, state)
            started = _append_event(
                self.study_directory,
                "run_started",
                {
                    "run_id": state.run_id,
                    "finalist_id": state.finalist_id,
                    "cohort_id": state.cohort_id,
                    "attempt": state.attempts + 1,
                    "request_id": request.request_id,
                    "run_directory": _relative(self.study_directory, request.destination),
                },
            )
            if event_callback is not None:
                event_callback(started)
            controller = self._controller_factory(request)
            self._active_controller = controller

            def forward(
                event: DesktopReferenceWorkerEvent,
                holdout_run_id: str = state.run_id,
            ) -> None:
                if event_callback is not None:
                    event_callback(
                        {
                            "event": "worker_event",
                            "run_id": holdout_run_id,
                            "worker_event": event.as_dict(),
                        }
                    )

            try:
                result = controller.run(event_callback=forward)
                if result.completed:
                    evidence = collect_reference_validation_run_evidence(
                        request.destination,
                        run_id=state.run_id,
                        finalist_id=state.finalist_id,
                        cohort_id=state.cohort_id,
                    )
                    terminal = _append_event(
                        self.study_directory,
                        "run_completed",
                        {
                            "run_id": state.run_id,
                            "finalist_id": state.finalist_id,
                            "cohort_id": state.cohort_id,
                            "attempt": state.attempts + 1,
                            "run_directory": _relative(self.study_directory, request.destination),
                            "evidence": evidence.as_manifest(),
                        },
                    )
                else:
                    terminal = _append_event(
                        self.study_directory,
                        "run_interrupted",
                        {
                            "run_id": state.run_id,
                            "attempt": state.attempts + 1,
                            "run_directory": _relative(self.study_directory, request.destination),
                            "error": "Holdout execution was cancelled safely.",
                        },
                    )
                    self._cancel_requested = True
            except Exception as error:
                terminal = _append_event(
                    self.study_directory,
                    "run_failed",
                    {
                        "run_id": state.run_id,
                        "attempt": state.attempts + 1,
                        "run_directory": (
                            _relative(self.study_directory, request.destination)
                            if request.destination.exists()
                            else None
                        ),
                        "error": str(error),
                    },
                )
            finally:
                self._active_controller = None
            if event_callback is not None:
                event_callback(terminal)
        updated = load_reference_holdout_study(self.study_directory)
        if not self._cancel_requested and all(run.status == "completed" for run in updated.runs):
            updated = _finalize_study(self.study_directory)
            if event_callback is not None:
                event_callback(
                    {
                        "event": "holdout_completed",
                        "status": updated.assessment.status if updated.assessment else None,
                        "completed_run_count": updated.completed_run_count,
                    }
                )
        return updated

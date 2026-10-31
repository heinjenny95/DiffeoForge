"""Frozen, resumable multi-start template robustness for reference atlases."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import numpy as np
import yaml

from diffeoforge.analysis.pca_stability import compare_pca_stability
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import (
    ConfigurationError,
    load_config,
    validate_input_paths,
    validate_schema,
)
from diffeoforge.desktop.reference_execution_controller import (
    ReferenceExecutionController,
    ReferenceExecutionControllerResult,
)
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import load_reference_momenta
from diffeoforge.reference_recommendation import recommend_reference_parameters
from diffeoforge.reference_runtime import launcher_identity
from diffeoforge.reference_sensitivity_assessment import (
    compare_ordered_atlas_templates,
    identity_bound_momenta_pca,
    verified_atlas_from_momenta_input,
)
from diffeoforge.reference_validation import ValidationRunEvidence
from diffeoforge.reference_validation_metrics import (
    collect_reference_validation_run_evidence,
)

TEMPLATE_ROBUSTNESS_VERSION = "0.1"
TEMPLATE_ROBUSTNESS_EVENT_VERSION = "0.1"
TEMPLATE_ROBUSTNESS_MANIFEST = "template-robustness-study.json"
TEMPLATE_ROBUSTNESS_DIGEST = "template-robustness-study.sha256"
TEMPLATE_ROBUSTNESS_EVENTS = "events.jsonl"
TEMPLATE_ROBUSTNESS_REPORT_JSON = "report/template-robustness-report.json"
TEMPLATE_ROBUSTNESS_REPORT_HTML = "report/template-robustness-report.html"


class ReferenceTemplateRobustnessError(ConfigurationError):
    """Raised when a multi-start study is invalid or cannot progress."""


class _Controller(Protocol):
    def run(
        self,
        *,
        event_callback: Callable[[DesktopReferenceWorkerEvent], None] | None = None,
    ) -> ReferenceExecutionControllerResult: ...

    def request_cancel(self) -> bool: ...


ControllerFactory = Callable[[DesktopReferenceLaunchRequest], _Controller]
StudyEventCallback = Callable[[Mapping[str, object]], None]


@dataclass(frozen=True)
class TemplateRobustnessRunState:
    arm_id: str
    status: str
    config_path: Path
    run_directory: Path | None
    attempts: int
    evidence: ValidationRunEvidence | None
    error: str | None


@dataclass(frozen=True)
class ReferenceTemplateRobustnessSnapshot:
    study_directory: Path
    study_id: str
    status: str
    runs: tuple[TemplateRobustnessRunState, ...]
    event_count: int
    assessment: Mapping[str, Any] | None
    report_json_path: Path | None
    report_html_path: Path | None

    @property
    def completed_run_count(self) -> int:
        return sum(run.status == "completed" for run in self.runs)


def _canonical_json(value: object, *, indent: int | None = None) -> str:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":") if indent is None else None,
            indent=indent,
            ensure_ascii=False,
            allow_nan=False,
        )
        + ("\n" if indent is not None else "")
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object, *, overwrite: bool) -> None:
    write_text_safely(path, _canonical_json(value, indent=2), overwrite=overwrite)


def _safe_path(root: Path, value: object) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ReferenceTemplateRobustnessError(
            f"Unsafe template-robustness path: {relative}"
        )
    path = root.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ReferenceTemplateRobustnessError(
            f"Template-robustness path escapes its root: {relative}"
        )
    return path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ReferenceTemplateRobustnessError(
            f"Template-robustness path escapes its study: {path}"
        ) from error


def _link_or_copy(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ReferenceTemplateRobustnessError(
            f"Template-robustness destination already exists: {destination}"
        )
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    if sha256_file(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReferenceTemplateRobustnessError(
            f"Template-robustness copy changed bytes: {source}"
        )


def _load_events(root: Path) -> tuple[dict[str, Any], ...]:
    try:
        lines = (root / TEMPLATE_ROBUSTNESS_EVENTS).read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError as error:
        raise ReferenceTemplateRobustnessError(
            f"Could not read template-robustness event ledger: {error}"
        ) from error
    previous_hash: str | None = None
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReferenceTemplateRobustnessError(
                f"Invalid template-robustness event at line {index + 1}"
            ) from error
        recorded_hash = record.pop("event_hash", None)
        if record.get("sequence") != index or record.get("previous_hash") != previous_hash:
            raise ReferenceTemplateRobustnessError(
                f"Template-robustness event chain broke at line {index + 1}"
            )
        if recorded_hash != _canonical_hash(record):
            raise ReferenceTemplateRobustnessError(
                f"Template-robustness event hash differs at line {index + 1}"
            )
        record["event_hash"] = recorded_hash
        previous_hash = str(recorded_hash)
        events.append(record)
    if not events or events[0].get("event") != "study_created":
        raise ReferenceTemplateRobustnessError(
            "Template-robustness ledger does not start with study_created"
        )
    return tuple(events)


def _append_event(root: Path, event: str, payload: Mapping[str, object]) -> dict[str, Any]:
    events = _load_events(root) if (root / TEMPLATE_ROBUSTNESS_EVENTS).exists() else ()
    record: dict[str, Any] = {
        "event_version": TEMPLATE_ROBUSTNESS_EVENT_VERSION,
        "sequence": len(events),
        "previous_hash": events[-1]["event_hash"] if events else None,
        "event": event,
        **dict(payload),
    }
    record["event_hash"] = _canonical_hash(record)
    try:
        with (root / TEMPLATE_ROBUSTNESS_EVENTS).open(
            "a", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(_canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise ReferenceTemplateRobustnessError(
            f"Could not append template-robustness event: {error}"
        ) from error
    return record


def _diverse_subject_starts(config: Mapping[str, Any], inputs, count: int) -> tuple[Path, ...]:
    recommendation_record = (
        config.get("project", {})
        .get("parameter_provenance", {})
        .get("recommendation", {})
    )
    recommendation = recommend_reference_parameters(
        (inputs.template, *inputs.subjects),
        alignment_basis="declared_gpa",
        surface_detail_intent=str(
            recommendation_record.get("surface_detail_intent", "balanced")
        ),
        deformation_scale_intent=str(
            recommendation_record.get("deformation_scale_intent", "balanced")
        ),
        expected_shape_disparity=str(
            recommendation_record.get("expected_shape_disparity", "moderate")
        ),
    )
    observations = recommendation.observations[1:]
    raw = np.asarray(
        [
            (
                math.log(item.bounding_box_diagonal),
                math.log(item.rms_radius),
                math.log(item.median_sampled_edge_length),
                math.log(float(item.triangles)),
            )
            for item in observations
        ],
        dtype=np.float64,
    )
    median = np.median(raw, axis=0)
    scale = np.median(np.abs(raw - median), axis=0)
    scale[scale <= np.finfo(float).eps] = 1.0
    matrix = (raw - median) / scale
    selected: list[int] = []
    while len(selected) < count:
        if not selected:
            distances = np.sum(matrix**2, axis=1)
        else:
            distances = np.min(
                np.sum((matrix[:, None, :] - matrix[selected][None, :, :]) ** 2, axis=2),
                axis=1,
            )
        distances[selected] = -1.0
        maximum = float(np.max(distances))
        tied = np.flatnonzero(np.isclose(distances, maximum, rtol=1e-12, atol=1e-15))
        selected.append(
            min(tied.tolist(), key=lambda index: observations[index].filename.casefold())
        )
    paths = {path.name: path for path in inputs.subjects}
    return tuple(paths[observations[index].filename] for index in selected)


def _arm_configuration(
    source: Mapping[str, Any],
    *,
    config_directory: Path,
    subjects_directory: Path,
    template_path: Path,
    arm_id: str,
    maximum_iterations: int,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(source))
    config["project"]["name"] = f"{source['project']['name']} template robustness {arm_id}"
    config["input"]["directory"] = os.path.relpath(
        subjects_directory, config_directory
    ).replace("\\", "/")
    config["input"]["template"] = os.path.relpath(
        template_path, config_directory
    ).replace("\\", "/")
    config["input"]["subject_pattern"] = "*.vtk"
    config["output"]["directory"] = "./runs"
    config["optimization"]["max_iterations"] = maximum_iterations
    validate_schema(config)
    return config


def create_reference_template_robustness_study(
    config_path: Path | str,
    study_directory: Path | str,
    *,
    start_count: int = 3,
    maximum_iterations: int | None = None,
    template_p95_margin: float | None = None,
    minimum_pca_similarity: float = 0.95,
    pca_variance_target: float = 0.90,
) -> ReferenceTemplateRobustnessSnapshot:
    """Freeze baseline plus diverse subject-derived starts without launching work."""

    source_path = Path(config_path).expanduser().resolve()
    source = load_config(source_path)
    inputs = validate_input_paths(source, source_path)
    if source["runtime"]["backend"] != "deformetrica_reference":
        raise ReferenceTemplateRobustnessError(
            "Template robustness currently requires the Deformetrica reference backend"
        )
    if isinstance(start_count, bool) or not isinstance(start_count, int):
        raise ReferenceTemplateRobustnessError("start_count must be an integer")
    if start_count < 2 or start_count > min(4, inputs.subject_count + 1):
        raise ReferenceTemplateRobustnessError(
            "start_count must be between 2 and 4 and cannot exceed subjects plus baseline"
        )
    iterations = (
        int(source["optimization"]["max_iterations"])
        if maximum_iterations is None
        else maximum_iterations
    )
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ReferenceTemplateRobustnessError("maximum_iterations must be positive")
    if not 0.0 < float(minimum_pca_similarity) <= 1.0:
        raise ReferenceTemplateRobustnessError(
            "minimum_pca_similarity must be in (0, 1]"
        )
    if not 0.0 < float(pca_variance_target) <= 1.0:
        raise ReferenceTemplateRobustnessError("pca_variance_target must be in (0, 1]")
    observations = recommend_reference_parameters(
        (inputs.template, *inputs.subjects),
        alignment_basis="declared_gpa",
        surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
    )
    margin = (
        0.005 * observations.template_diagonal
        if template_p95_margin is None
        else float(template_p95_margin)
    )
    if not math.isfinite(margin) or margin <= 0.0:
        raise ReferenceTemplateRobustnessError(
            "template_p95_margin must be finite and positive"
        )
    alternatives = _diverse_subject_starts(source, inputs, start_count - 1)
    selected = (inputs.template, *alternatives)
    root = Path(study_directory).expanduser().resolve()
    if root.exists():
        raise ReferenceTemplateRobustnessError(
            f"Template-robustness destination already exists: {root}"
        )
    root.mkdir(parents=True)
    try:
        source_copy = root / "source" / "atlas.yaml"
        source_copy.parent.mkdir(parents=True)
        shutil.copy2(source_path, source_copy)
        subjects_directory = root / "inputs" / "subjects"
        subject_records = []
        for subject in inputs.subjects:
            digest = sha256_file(subject)
            copy_path = subjects_directory / subject.name
            _link_or_copy(subject, copy_path, digest)
            subject_records.append(
                {
                    "filename": subject.name,
                    "source_path": str(subject),
                    "copy": _relative(root, copy_path),
                    "sha256": digest,
                }
            )
        arms = []
        for index, template in enumerate(selected):
            arm_id = "baseline" if index == 0 else f"diverse-start-{index:02d}"
            template_copy = root / "starting-templates" / f"{arm_id}.vtk"
            digest = sha256_file(template)
            _link_or_copy(template, template_copy, digest)
            config_directory = root / "run-specs" / arm_id
            config_directory.mkdir(parents=True)
            config = _arm_configuration(
                source,
                config_directory=config_directory,
                subjects_directory=subjects_directory,
                template_path=template_copy,
                arm_id=arm_id,
                maximum_iterations=iterations,
            )
            arm_config = config_directory / "atlas.yaml"
            write_text_safely(
                arm_config,
                yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
                overwrite=False,
            )
            arms.append(
                {
                    "arm_id": arm_id,
                    "label": (
                        "Configured baseline template"
                        if index == 0
                        else f"Diverse subject-derived start {index}"
                    ),
                    "source_template_path": str(template),
                    "source_template_filename": template.name,
                    "template_copy": _relative(root, template_copy),
                    "template_sha256": digest,
                    "selection_role": (
                        "configured_baseline"
                        if index == 0
                        else "deterministic_geometry_diverse_initialization"
                    ),
                    "config": _relative(root, arm_config),
                    "config_sha256": sha256_file(arm_config),
                }
            )
        manifest = {
            "study_version": TEMPLATE_ROBUSTNESS_VERSION,
            "study_id": f"reference-template-robustness-{uuid4().hex[:12]}",
            "source_config": {
                "original_path": str(source_path),
                "copy": _relative(root, source_copy),
                "sha256": sha256_file(source_copy),
            },
            "launcher": launcher_identity(source["runtime"]["launcher"]),
            "maximum_iterations": iterations,
            "subjects": subject_records,
            "arms": arms,
            "thresholds": {
                "template_ordered_vertex_p95_margin": margin,
                "template_margin_basis": (
                    "explicit CLI value"
                    if template_p95_margin is not None
                    else "0.5% of the configured template bounding-box diagonal; a "
                    "numerical engineering gate, not a biological effect threshold"
                ),
                "minimum_pca_similarity": float(minimum_pca_similarity),
                "pca_variance_target": float(pca_variance_target),
            },
            "design": {
                "same_subject_cohort_across_arms": True,
                "same_model_and_optimizer_parameters_across_arms": True,
                "only_intended_difference": "initial template geometry",
                "subject_derived_starts_remain_in_subject_cohort": True,
            },
            "scientific_boundary": (
                "Stability across these deterministic starts supports limited initialization "
                "robustness. It does not prove global optimality, bootstrap stability, or "
                "biological validity."
            ),
        }
        _write_json(root / TEMPLATE_ROBUSTNESS_MANIFEST, manifest, overwrite=False)
        write_text_safely(
            root / TEMPLATE_ROBUSTNESS_DIGEST,
            sha256_file(root / TEMPLATE_ROBUSTNESS_MANIFEST) + "\n",
            overwrite=False,
        )
        _append_event(
            root,
            "study_created",
            {
                "study_id": manifest["study_id"],
                "manifest_sha256": sha256_file(root / TEMPLATE_ROBUSTNESS_MANIFEST),
                "arm_count": len(arms),
            },
        )
    except BaseException:
        if root.is_dir():
            shutil.rmtree(root)
        raise
    return load_reference_template_robustness_study(root)


def _verify_manifest(root: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(
            (root / TEMPLATE_ROBUSTNESS_MANIFEST).read_text(encoding="utf-8")
        )
        expected = (root / TEMPLATE_ROBUSTNESS_DIGEST).read_text(
            encoding="ascii"
        ).strip()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReferenceTemplateRobustnessError(
            f"Could not read template-robustness manifest: {error}"
        ) from error
    if sha256_file(root / TEMPLATE_ROBUSTNESS_MANIFEST) != expected:
        raise ReferenceTemplateRobustnessError(
            "Template-robustness manifest SHA-256 differs"
        )
    if manifest.get("study_version") != TEMPLATE_ROBUSTNESS_VERSION:
        raise ReferenceTemplateRobustnessError(
            f"Unsupported template-robustness version: {manifest.get('study_version')}"
        )
    records = [
        manifest["source_config"],
        *manifest["subjects"],
        *manifest["arms"],
    ]
    for record in records:
        if "config" in record:
            path = _safe_path(root, record["config"])
            digest = record["config_sha256"]
        else:
            path = _safe_path(root, record["copy"])
            digest = record["sha256"]
        if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
            raise ReferenceTemplateRobustnessError(
                f"Bound template-robustness file changed or is absent: {path}"
            )
    for arm in manifest["arms"]:
        template = _safe_path(root, arm["template_copy"])
        if not template.is_file() or sha256_file(template) != arm["template_sha256"]:
            raise ReferenceTemplateRobustnessError(
                f"Starting-template copy changed or is absent: {template}"
            )
    return manifest


def _evidence_from_manifest(value: Mapping[str, object]) -> ValidationRunEvidence:
    subjects = value.get("subject_residual_p95", {})
    return ValidationRunEvidence(
        run_id=str(value["run_id"]),
        finalist_id=str(value["finalist_id"]),
        cohort_id=str(value["cohort_id"]),
        completed=bool(value["completed"]),
        converged=bool(value["converged"]),
        invalid_face_count=int(value["invalid_face_count"]),
        external_residual_p95=float(value["external_residual_p95"]),
        distortion_p95=float(value["distortion_p95"]),
        runtime_seconds=float(value["runtime_seconds"]),
        atlas_path=str(value["atlas_path"]),
        subject_residual_p95=tuple(
            sorted((str(name), float(metric)) for name, metric in subjects.items())
        ),
    )


def _run_states(
    root: Path,
    manifest: Mapping[str, Any],
    events: tuple[dict[str, Any], ...],
) -> tuple[TemplateRobustnessRunState, ...]:
    states = []
    for arm in manifest["arms"]:
        arm_id = str(arm["arm_id"])
        starts = [
            event
            for event in events
            if event["event"] == "run_started" and event["arm_id"] == arm_id
        ]
        terminals = [
            event
            for event in events
            if event["event"] in {"run_completed", "run_failed", "run_interrupted"}
            and event["arm_id"] == arm_id
        ]
        completed = [event for event in terminals if event["event"] == "run_completed"]
        latest = terminals[-1] if terminals else None
        orphaned = bool(
            starts
            and (not terminals or starts[-1]["sequence"] > terminals[-1]["sequence"])
        )
        if completed:
            status = "completed"
            event = completed[-1]
            run_directory = _safe_path(root, event["run_directory"])
            evidence = _evidence_from_manifest(event["evidence"])
            error = None
        elif orphaned:
            status = "orphaned"
            run_directory = _safe_path(root, starts[-1]["run_directory"])
            evidence = None
            error = "Previous process ended before recording a terminal event"
        elif latest is not None:
            status = "failed"
            relative = latest.get("run_directory")
            run_directory = _safe_path(root, relative) if relative else None
            evidence = None
            error = str(latest.get("error", "Template-robustness run failed"))
        else:
            status = "pending"
            run_directory = None
            evidence = None
            error = None
        states.append(
            TemplateRobustnessRunState(
                arm_id=arm_id,
                status=status,
                config_path=_safe_path(root, arm["config"]),
                run_directory=run_directory,
                attempts=len(starts),
                evidence=evidence,
                error=error,
            )
        )
    return tuple(states)


def _outlier_set(evidence: ValidationRunEvidence, fraction: float = 0.10) -> set[str]:
    count = max(1, int(math.ceil(len(evidence.subject_residual_p95) * fraction)))
    ranked = sorted(
        evidence.subject_residual_p95,
        key=lambda item: (-item[1], item[0].casefold()),
    )
    return {name for name, _ in ranked[:count]}


def _assess(
    snapshot: ReferenceTemplateRobustnessSnapshot,
    manifest: Mapping[str, Any],
) -> dict[str, object]:
    if any(run.evidence is None or run.run_directory is None for run in snapshot.runs):
        raise ReferenceTemplateRobustnessError(
            "Template-robustness assessment requires every frozen arm to complete"
        )
    loaded = {}
    atlases = {}
    pcas = {}
    for run in snapshot.runs:
        inputs = load_reference_momenta(run.run_directory)
        atlas, _ = verified_atlas_from_momenta_input(
            inputs, str(run.evidence.atlas_path)
        )
        loaded[run.arm_id] = inputs
        atlases[run.arm_id] = atlas
        pcas[run.arm_id] = identity_bound_momenta_pca(inputs)
    subject_sets = {set(inputs.subject_labels) for inputs in loaded.values()}
    if len(subject_sets) != 1:
        raise ReferenceTemplateRobustnessError(
            "Template-robustness arms do not contain the same named subject cohort"
        )
    thresholds = manifest["thresholds"]
    margin = float(thresholds["template_ordered_vertex_p95_margin"])
    minimum_pca = float(thresholds["minimum_pca_similarity"])
    variance_target = float(thresholds["pca_variance_target"])
    comparisons = []
    arm_ids = sorted(loaded)
    for index, first_id in enumerate(arm_ids):
        for second_id in arm_ids[index + 1 :]:
            template = compare_ordered_atlas_templates(
                atlases[first_id], atlases[second_id]
            )
            pca = compare_pca_stability(
                pcas[first_id], pcas[second_id], variance_target=variance_target
            )
            first_run = next(run for run in snapshot.runs if run.arm_id == first_id)
            second_run = next(run for run in snapshot.runs if run.arm_id == second_id)
            left = _outlier_set(first_run.evidence)
            right = _outlier_set(second_run.evidence)
            comparisons.append(
                {
                    "first_arm_id": first_id,
                    "second_arm_id": second_id,
                    "template": {
                        **template,
                        "within_declared_margin": (
                            template["ordered_vertex_p95"] <= margin
                        ),
                    },
                    "pca_structure": {
                        **pca.as_manifest(),
                        "passes_engineering_gate": (
                            pca.score_linear_cka >= minimum_pca
                            and pca.score_distance_rank_correlation >= minimum_pca
                        ),
                    },
                    "high_residual_subject_jaccard": len(left & right) / len(left | right),
                }
            )
    valid = all(
        run.evidence.converged and run.evidence.invalid_face_count == 0
        for run in snapshot.runs
    )
    template_stable = all(
        comparison["template"]["within_declared_margin"]
        for comparison in comparisons
    )
    pca_stable = all(
        comparison["pca_structure"]["passes_engineering_gate"]
        for comparison in comparisons
    )
    if not valid:
        status = "failed_validity_gate"
    elif template_stable and pca_stable:
        status = "stable_across_tested_start_templates"
    else:
        status = "start_template_dependence_detected"
    warnings = []
    if not template_stable:
        warnings.append(
            "At least one estimated-template difference exceeds the frozen margin."
        )
    if not pca_stable:
        warnings.append("At least one paired PCA comparison misses the frozen gate.")
    if not valid:
        warnings.append(
            "At least one arm lacks explicit convergence or contains invalid output faces."
        )
    return {
        "assessment_version": "0.1",
        "status": status,
        "arm_count": len(snapshot.runs),
        "subject_count": len(next(iter(subject_sets))),
        "gates": {
            "all_runs_valid": valid,
            "estimated_templates_stable": template_stable,
            "pca_structure_stable": pca_stable,
        },
        "thresholds": dict(thresholds),
        "pairwise_comparisons": comparisons,
        "warnings": warnings,
        "claim_scope": manifest["scientific_boundary"],
        "next_step": (
            "Add bootstrap-cohort starts or inspect failed arms before locking an atlas."
            if status != "stable_across_tested_start_templates"
            else "Retain this artifact with the final scientific report; bootstrap-cohort "
            "evidence remains a stronger optional next gate."
        ),
    }


def _report_payload(
    snapshot: ReferenceTemplateRobustnessSnapshot,
    manifest: Mapping[str, Any],
    assessment: Mapping[str, Any],
) -> dict[str, object]:
    return {
        "report_version": "0.1",
        "study_id": snapshot.study_id,
        "source_manifest_sha256": sha256_file(
            snapshot.study_directory / TEMPLATE_ROBUSTNESS_MANIFEST
        ),
        "design": manifest["design"],
        "arms": manifest["arms"],
        "assessment": assessment,
        "scientific_boundary": manifest["scientific_boundary"],
    }


def _report_html(report: Mapping[str, Any]) -> str:
    assessment = report["assessment"]
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['first_arm_id'])} vs "
        f"{html.escape(item['second_arm_id'])}</td>"
        f"<td>{item['template']['ordered_vertex_p95']:.6g}</td>"
        f"<td>{item['pca_structure']['score_linear_cka']:.3f}</td>"
        f"<td>{item['pca_structure']['score_distance_rank_correlation']:.3f}</td>"
        f"<td>{item['high_residual_subject_jaccard']:.3f}</td></tr>"
        for item in assessment["pairwise_comparisons"]
    )
    warnings = "".join(
        f"<li>{html.escape(item)}</li>" for item in assessment["warnings"]
    ) or "<li>No additional numerical warning was triggered.</li>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DiffeoForge template robustness</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:36px auto;
padding:0 24px;color:#103b3b;line-height:1.45}}h1,h2{{color:#073c3b}}
.notice{{background:#e3f6ef;border-left:5px solid #13856f;padding:14px 18px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #c8d9d7;
padding:10px;text-align:left}}th{{background:#eef5f4}}</style></head><body>
<h1>DiffeoForge multi-start template robustness</h1>
<p class="notice"><strong>Status:</strong> {html.escape(assessment['status'])}<br>
{html.escape(report['scientific_boundary'])}</p><table><thead><tr><th>Starts</th>
<th>Template p95</th><th>PCA CKA</th><th>PCA rank correlation</th>
<th>High-residual Jaccard</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Warnings</h2><ul>{warnings}</ul><h2>Next step</h2>
<p>{html.escape(assessment['next_step'])}</p></body></html>"""


def load_reference_template_robustness_study(
    study_directory: Path | str,
) -> ReferenceTemplateRobustnessSnapshot:
    root = Path(study_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ReferenceTemplateRobustnessError(
            f"Template-robustness study is missing or symbolic: {root}"
        )
    manifest = _verify_manifest(root)
    events = _load_events(root)
    runs = _run_states(root, manifest, events)
    completion = next(
        (event for event in reversed(events) if event["event"] == "study_completed"),
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
            raise ReferenceTemplateRobustnessError(
                "Template-robustness report bytes changed"
            )
        provisional = ReferenceTemplateRobustnessSnapshot(
            root,
            str(manifest["study_id"]),
            "completed",
            runs,
            len(events),
            None,
            report_json,
            report_html,
        )
        assessment = _assess(provisional, manifest)
        expected = _report_payload(provisional, manifest, assessment)
        try:
            stored = json.loads(report_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReferenceTemplateRobustnessError(
                "Could not read template-robustness report"
            ) from error
        if stored != expected or report_html.read_text(encoding="utf-8") != _report_html(expected):
            raise ReferenceTemplateRobustnessError(
                "Template-robustness report differs from exact recomputation"
            )
        status = "completed"
    elif any(run.status == "orphaned" for run in runs):
        status = "interrupted"
    elif all(run.status == "completed" for run in runs):
        status = "awaiting_report"
    elif any(run.status == "failed" for run in runs):
        status = "ready_to_retry"
    else:
        status = "ready"
    return ReferenceTemplateRobustnessSnapshot(
        root,
        str(manifest["study_id"]),
        status,
        runs,
        len(events),
        assessment,
        report_json,
        report_html,
    )


def _finalize(root: Path) -> ReferenceTemplateRobustnessSnapshot:
    snapshot = load_reference_template_robustness_study(root)
    if snapshot.status == "completed":
        return snapshot
    manifest = _verify_manifest(root)
    assessment = _assess(snapshot, manifest)
    report = _report_payload(snapshot, manifest, assessment)
    json_path = root / TEMPLATE_ROBUSTNESS_REPORT_JSON
    html_path = root / TEMPLATE_ROBUSTNESS_REPORT_HTML
    json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(json_path, report, overwrite=False)
    write_text_safely(html_path, _report_html(report), overwrite=False)
    _append_event(
        root,
        "study_completed",
        {
            "assessment_status": assessment["status"],
            "report_json": _relative(root, json_path),
            "report_json_sha256": sha256_file(json_path),
            "report_html": _relative(root, html_path),
            "report_html_sha256": sha256_file(html_path),
        },
    )
    return load_reference_template_robustness_study(root)


def _launch_request(
    root: Path,
    manifest: Mapping[str, Any],
    state: TemplateRobustnessRunState,
) -> DesktopReferenceLaunchRequest:
    attempt = state.attempts + 1
    attempt_id = f"attempt-{attempt:02d}"
    destination = (state.config_path.parent / "runs" / attempt_id).resolve()
    launcher = manifest["launcher"]
    return DesktopReferenceLaunchRequest(
        request_id=f"template-robustness-{uuid4().hex}",
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


class ReferenceTemplateRobustnessRunner:
    """Execute missing multi-start arms sequentially and resume safely."""

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
        event_callback: StudyEventCallback | None = None,
    ) -> ReferenceTemplateRobustnessSnapshot:
        snapshot = load_reference_template_robustness_study(self.study_directory)
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
                    "arm_id": state.arm_id,
                    "attempt": state.attempts + 1,
                    "request_id": request.request_id,
                    "run_directory": _relative(
                        self.study_directory, request.destination
                    ),
                },
            )
            if event_callback is not None:
                event_callback(started)
            controller = self._controller_factory(request)
            self._active_controller = controller

            def forward(
                event: DesktopReferenceWorkerEvent,
                arm_id: str = state.arm_id,
            ) -> None:
                if event_callback is not None:
                    event_callback(
                        {
                            "event": "worker_event",
                            "arm_id": arm_id,
                            "worker_event": event.as_dict(),
                        }
                    )

            try:
                result = controller.run(event_callback=forward)
                if result.completed:
                    evidence = collect_reference_validation_run_evidence(
                        request.destination,
                        run_id=state.arm_id,
                        finalist_id=state.arm_id,
                        cohort_id="full-cohort",
                    )
                    terminal = _append_event(
                        self.study_directory,
                        "run_completed",
                        {
                            "arm_id": state.arm_id,
                            "attempt": state.attempts + 1,
                            "run_directory": _relative(
                                self.study_directory, request.destination
                            ),
                            "evidence": evidence.as_manifest(),
                        },
                    )
                else:
                    terminal = _append_event(
                        self.study_directory,
                        "run_interrupted",
                        {
                            "arm_id": state.arm_id,
                            "attempt": state.attempts + 1,
                            "run_directory": _relative(
                                self.study_directory, request.destination
                            ),
                            "error": "Template-robustness execution was cancelled safely.",
                        },
                    )
                    self._cancel_requested = True
            except Exception as error:
                terminal = _append_event(
                    self.study_directory,
                    "run_failed",
                    {
                        "arm_id": state.arm_id,
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
        updated = load_reference_template_robustness_study(self.study_directory)
        if not self._cancel_requested and all(
            run.status == "completed" for run in updated.runs
        ):
            updated = _finalize(self.study_directory)
            if event_callback is not None:
                event_callback(
                    {
                        "event": "template_robustness_completed",
                        "status": updated.assessment["status"],
                        "completed_run_count": updated.completed_run_count,
                    }
                )
        return updated

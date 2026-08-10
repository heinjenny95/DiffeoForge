"""Resumable execution and reporting for DiffeoForge Validation Lab."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import load_config, validate_input_paths, validate_schema
from diffeoforge.desktop.reference_execution_controller import (
    ReferenceExecutionController,
    ReferenceExecutionControllerResult,
)
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_runtime import launcher_identity
from diffeoforge.reference_validation import (
    ReferenceValidationAssessment,
    ReferenceValidationError,
    ReferenceValidationPlan,
    ValidationRunEvidence,
    assess_reference_validation,
    build_reference_validation_plan,
    reference_validation_plan_from_manifest,
)
from diffeoforge.reference_validation_metrics import (
    collect_reference_validation_run_evidence,
)

VALIDATION_STUDY_VERSION = "0.1"
VALIDATION_EVENT_VERSION = "0.1"
VALIDATION_MANIFEST = "validation-study.json"
VALIDATION_DIGEST = "validation-study.sha256"
VALIDATION_EVENTS = "events.jsonl"
VALIDATION_REPORT_JSON = "report/validation-report.json"
VALIDATION_REPORT_HTML = "report/validation-report.html"
ValidationEventCallback = Callable[[Mapping[str, object]], None]


class ReferenceValidationStudyError(ReferenceValidationError):
    """Raised when a Validation Lab study is invalid or cannot progress."""


class _Controller(Protocol):
    def run(
        self,
        *,
        event_callback: Callable[[DesktopReferenceWorkerEvent], None] | None = None,
    ) -> ReferenceExecutionControllerResult: ...

    def request_cancel(self) -> bool: ...


ControllerFactory = Callable[[DesktopReferenceLaunchRequest], _Controller]


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
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _write_json(path: Path, value: object, *, overwrite: bool) -> None:
    write_text_safely(path, _canonical_json(value, indent=2), overwrite=overwrite)


def _write_yaml(path: Path, value: Mapping[str, Any], *, overwrite: bool) -> None:
    write_text_safely(
        path,
        yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=True),
        overwrite=overwrite,
    )


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ReferenceValidationStudyError(
            f"Validation path escapes its study directory: {path}"
        ) from error


def _safe_path(root: Path, value: object) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ReferenceValidationStudyError(f"Unsafe validation-study path: {relative}")
    path = root.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ReferenceValidationStudyError(
            f"Validation-study path escapes its root: {relative}"
        )
    return path


def _copy_bound(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ReferenceValidationStudyError(
            f"Validation input destination already exists: {destination}"
        )
    shutil.copy2(source, destination)
    if sha256_file(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReferenceValidationStudyError(
            f"Validation input copy did not preserve bytes: {source}"
        )


def _link_or_copy_bound(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    if sha256_file(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReferenceValidationStudyError(
            f"Validation cohort copy did not preserve bytes: {source}"
        )


def _load_events(root: Path) -> tuple[dict[str, Any], ...]:
    path = root / VALIDATION_EVENTS
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ReferenceValidationStudyError(
            f"Could not read validation event ledger: {error}"
        ) from error
    previous_hash: str | None = None
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReferenceValidationStudyError(
                f"Invalid validation event JSON at line {index + 1}"
            ) from error
        recorded_hash = record.pop("event_hash", None)
        if record.get("sequence") != index or record.get("previous_hash") != previous_hash:
            raise ReferenceValidationStudyError(
                f"Validation event chain is broken at line {index + 1}"
            )
        expected = _canonical_hash(record)
        record["event_hash"] = recorded_hash
        if recorded_hash != expected:
            raise ReferenceValidationStudyError(
                f"Validation event hash differs at line {index + 1}"
            )
        previous_hash = str(recorded_hash)
        events.append(record)
    if not events or events[0].get("event") != "study_created":
        raise ReferenceValidationStudyError(
            "Validation event ledger does not start with study_created"
        )
    return tuple(events)


def _append_event(root: Path, event: str, payload: Mapping[str, object]) -> dict[str, Any]:
    events = _load_events(root) if (root / VALIDATION_EVENTS).exists() else ()
    record: dict[str, Any] = {
        "event_version": VALIDATION_EVENT_VERSION,
        "sequence": len(events),
        "previous_hash": events[-1]["event_hash"] if events else None,
        "event": event,
        **dict(payload),
    }
    record["event_hash"] = _canonical_hash(record)
    try:
        with (root / VALIDATION_EVENTS).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise ReferenceValidationStudyError(
            f"Could not append validation event: {error}"
        ) from error
    return record


def _validation_configuration(
    source: Mapping[str, Any],
    *,
    root: Path,
    config_directory: Path,
    template_copy: Path,
    cohort_directory: Path,
    finalist_values: Mapping[str, float],
    run_id: str,
    maximum_iterations: int,
    template_diagonal: float,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(source))
    config["project"]["name"] = f"{source['project']['name']} validation {run_id}"
    config["input"]["directory"] = os.path.relpath(
        cohort_directory, config_directory
    ).replace("\\", "/")
    config["input"]["template"] = os.path.relpath(
        template_copy, config_directory
    ).replace("\\", "/")
    config["input"]["subject_pattern"] = "*.vtk"
    config["output"]["directory"] = "./runs"
    config["optimization"]["max_iterations"] = maximum_iterations
    targets = {
        "attachment_kernel_width": ("attachment", "kernel_width"),
        "deformation_kernel_width": ("deformation", "kernel_width"),
        "initial_control_point_spacing": (
            "deformation",
            "initial_control_point_spacing",
        ),
    }
    for name, raw_value in finalist_values.items():
        value = float(raw_value)
        if name == "noise_std":
            config["model"]["noise_std"] = value
        elif name == "timepoints":
            config["model"]["deformation"]["timepoints"] = int(value)
        else:
            group, key = targets[name]
            config["model"][group][key] = value
        if name != "timepoints":
            config["project"]["parameter_provenance"]["ratios"][name] = (
                value / template_diagonal
            )
            config["project"]["parameter_provenance"]["sources"][name] = (
                "absolute_override"
            )
    validate_schema(config)
    return config


@dataclass(frozen=True)
class ValidationStudyRunState:
    run_id: str
    finalist_id: str
    cohort_id: str
    status: str
    config_path: Path
    run_directory: Path | None
    attempts: int
    evidence: ValidationRunEvidence | None
    error: str | None


@dataclass(frozen=True)
class ReferenceValidationStudySnapshot:
    study_directory: Path
    study_id: str
    plan: ReferenceValidationPlan
    status: str
    runs: tuple[ValidationStudyRunState, ...]
    event_count: int
    assessment: ReferenceValidationAssessment | None
    report_json_path: Path | None
    report_html_path: Path | None

    @property
    def completed_run_count(self) -> int:
        return sum(run.status == "completed" for run in self.runs)


def create_reference_validation_study(
    config_path: Path | str,
    study_directory: Path | str,
    *,
    holdout_fraction: float = 0.20,
    resample_count: int = 5,
    resample_fraction: float = 0.80,
    maximum_iterations: int | None = None,
) -> ReferenceValidationStudySnapshot:
    """Freeze the complete Validation Lab design without starting a process."""

    source_path = Path(config_path).expanduser().resolve()
    source_config = load_config(source_path)
    inputs = validate_input_paths(source_config, source_path)
    plan = build_reference_validation_plan(
        source_path,
        holdout_fraction=holdout_fraction,
        resample_count=resample_count,
        resample_fraction=resample_fraction,
    )
    iterations = (
        int(source_config["optimization"]["max_iterations"])
        if maximum_iterations is None
        else maximum_iterations
    )
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ReferenceValidationStudyError("maximum_iterations must be positive")
    root = Path(study_directory).expanduser().resolve()
    if root.exists():
        raise ReferenceValidationStudyError(
            f"Validation study destination already exists: {root}"
        )
    root.mkdir(parents=True)
    try:
        source_copy = root / "source" / "atlas-calibrated.yaml"
        _copy_bound(source_path, source_copy, plan.source_config_sha256)
        template_copy = root / "inputs" / "template" / inputs.template.name
        _copy_bound(inputs.template, template_copy, plan.template_sha256)
        source_subjects = {path.name: path for path in inputs.subjects}
        subject_records: list[dict[str, object]] = []
        master_directory = root / "inputs" / "subjects"
        for subject in plan.subjects:
            source_subject = source_subjects.get(subject.filename)
            if source_subject is None or sha256_file(source_subject) != subject.sha256:
                raise ReferenceValidationStudyError(
                    f"Validation subject changed after planning: {subject.filename}"
                )
            destination = master_directory / subject.filename
            _copy_bound(source_subject, destination, subject.sha256)
            subject_records.append(
                {
                    "filename": subject.filename,
                    "copy": _relative(root, destination),
                    "sha256": subject.sha256,
                    "role": subject.role,
                }
            )

        cohort_directories: dict[str, Path] = {}
        for cohort in plan.cohorts:
            cohort_directory = root / "cohorts" / cohort.cohort_id
            cohort_directories[cohort.cohort_id] = cohort_directory
            for name in cohort.subject_filenames:
                record = next(item for item in subject_records if item["filename"] == name)
                _link_or_copy_bound(
                    _safe_path(root, record["copy"]),
                    cohort_directory / name,
                    str(record["sha256"]),
                )

        finalist_by_id = {item.finalist_id: item for item in plan.finalists}
        run_records: list[dict[str, object]] = []
        for spec in plan.run_specs:
            config_directory = root / "run-specs" / spec.run_id
            config_directory.mkdir(parents=True)
            config = _validation_configuration(
                source_config,
                root=root,
                config_directory=config_directory,
                template_copy=template_copy,
                cohort_directory=cohort_directories[spec.cohort_id],
                finalist_values=finalist_by_id[spec.finalist_id].values,
                run_id=spec.run_id,
                maximum_iterations=iterations,
                template_diagonal=plan.template_diagonal,
            )
            candidate_config = config_directory / "atlas.yaml"
            _write_yaml(candidate_config, config, overwrite=False)
            run_records.append(
                {
                    **spec.as_manifest(),
                    "config": _relative(root, candidate_config),
                    "config_sha256": sha256_file(candidate_config),
                }
            )
        manifest = {
            "study_version": VALIDATION_STUDY_VERSION,
            "study_id": f"reference-validation-{uuid4().hex[:12]}",
            "plan_fingerprint": plan.fingerprint,
            "plan": plan.as_manifest(),
            "maximum_iterations": iterations,
            "launcher": launcher_identity(source_config["runtime"]["launcher"]),
            "source_config": {
                "original_path": str(source_path),
                "copy": _relative(root, source_copy),
                "sha256": sha256_file(source_copy),
            },
            "inputs": {
                "template": {
                    "copy": _relative(root, template_copy),
                    "sha256": sha256_file(template_copy),
                },
                "subjects": subject_records,
            },
            "runs": run_records,
            "scientific_boundary": (
                "A robust result means stable preference within the frozen finalist "
                "search space. It is not a universal optimum and does not replace "
                "heldout registration or anatomy-specific validation."
            ),
        }
        _write_json(root / VALIDATION_MANIFEST, manifest, overwrite=False)
        write_text_safely(
            root / VALIDATION_DIGEST,
            sha256_file(root / VALIDATION_MANIFEST) + "\n",
            overwrite=False,
        )
        _append_event(
            root,
            "study_created",
            {
                "study_id": manifest["study_id"],
                "plan_fingerprint": plan.fingerprint,
                "manifest_sha256": sha256_file(root / VALIDATION_MANIFEST),
                "run_count": len(plan.run_specs),
            },
        )
    except BaseException:
        if root.is_dir():
            shutil.rmtree(root)
        raise
    return load_reference_validation_study(root)


def _verify_manifest(root: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((root / VALIDATION_MANIFEST).read_text(encoding="utf-8"))
        expected = (root / VALIDATION_DIGEST).read_text(encoding="utf-8").strip()
    except (OSError, json.JSONDecodeError) as error:
        raise ReferenceValidationStudyError(
            f"Could not read validation study manifest: {error}"
        ) from error
    if sha256_file(root / VALIDATION_MANIFEST) != expected:
        raise ReferenceValidationStudyError("Validation study manifest SHA-256 differs")
    if manifest.get("study_version") != VALIDATION_STUDY_VERSION:
        raise ReferenceValidationStudyError(
            f"Unsupported validation study version: {manifest.get('study_version')}"
        )
    plan = reference_validation_plan_from_manifest(manifest["plan"])
    if manifest.get("plan_fingerprint") != plan.fingerprint:
        raise ReferenceValidationStudyError("Validation study plan binding differs")
    bound = [
        manifest["source_config"],
        manifest["inputs"]["template"],
        *manifest["inputs"]["subjects"],
        *manifest["runs"],
    ]
    for record in bound:
        key = "config" if "config" in record else "copy"
        path = _safe_path(root, record[key])
        digest_key = "config_sha256" if key == "config" else "sha256"
        if not path.is_file() or sha256_file(path) != record[digest_key]:
            raise ReferenceValidationStudyError(
                f"Validation study bound file changed or is absent: {path}"
            )
    subject_hashes = {
        str(record["filename"]): str(record["sha256"])
        for record in manifest["inputs"]["subjects"]
    }
    for cohort in plan.cohorts:
        for filename in cohort.subject_filenames:
            path = root / "cohorts" / cohort.cohort_id / filename
            if (
                filename not in subject_hashes
                or not path.is_file()
                or sha256_file(path) != subject_hashes[filename]
            ):
                raise ReferenceValidationStudyError(
                    f"Validation cohort input changed or is absent: {path}"
                )
    return manifest


def _evidence_from_manifest(value: Mapping[str, object]) -> ValidationRunEvidence:
    raw_subjects = value.get("subject_residual_p95", {})
    return ValidationRunEvidence(
        run_id=str(value["run_id"]),
        finalist_id=str(value["finalist_id"]),
        cohort_id=str(value["cohort_id"]),
        completed=bool(value["completed"]),
        converged=bool(value["converged"]),
        invalid_face_count=int(value["invalid_face_count"]),
        external_residual_p95=(
            None
            if value.get("external_residual_p95") is None
            else float(value["external_residual_p95"])
        ),
        distortion_p95=(
            None if value.get("distortion_p95") is None else float(value["distortion_p95"])
        ),
        runtime_seconds=(
            None
            if value.get("runtime_seconds") is None
            else float(value["runtime_seconds"])
        ),
        atlas_path=(None if value.get("atlas_path") is None else str(value["atlas_path"])),
        subject_residual_p95=tuple(
            sorted((str(name), float(metric)) for name, metric in raw_subjects.items())
        ),
    )


def load_reference_validation_study(
    study_directory: Path | str,
) -> ReferenceValidationStudySnapshot:
    root = Path(study_directory).expanduser().resolve()
    if not root.is_dir():
        raise ReferenceValidationStudyError(
            f"Validation study directory does not exist: {root}"
        )
    manifest = _verify_manifest(root)
    plan = reference_validation_plan_from_manifest(manifest["plan"])
    events = _load_events(root)
    run_states: list[ValidationStudyRunState] = []
    for record in manifest["runs"]:
        run_id = str(record["run_id"])
        starts = [
            event
            for event in events
            if event["event"] == "run_started" and event["run_id"] == run_id
        ]
        terminals = [
            event
            for event in events
            if event["event"] in {"run_completed", "run_failed", "run_interrupted"}
            and event["run_id"] == run_id
        ]
        completed = [event for event in terminals if event["event"] == "run_completed"]
        latest_terminal = terminals[-1] if terminals else None
        orphaned = bool(
            starts
            and (
                not terminals
                or starts[-1]["sequence"] > terminals[-1]["sequence"]
            )
        )
        if completed:
            status = "completed"
            evidence = _evidence_from_manifest(completed[-1]["evidence"])
            error = None
            run_directory = _safe_path(root, completed[-1]["run_directory"])
        elif orphaned:
            status = "orphaned"
            evidence = None
            error = "Previous process ended before recording a terminal event"
            run_directory = _safe_path(root, starts[-1]["run_directory"])
        elif latest_terminal is not None:
            status = "failed"
            evidence = None
            error = str(latest_terminal.get("error", "Validation run failed"))
            relative_run = latest_terminal.get("run_directory")
            run_directory = _safe_path(root, relative_run) if relative_run else None
        else:
            status = "pending"
            evidence = None
            error = None
            run_directory = None
        run_states.append(
            ValidationStudyRunState(
                run_id=run_id,
                finalist_id=str(record["finalist_id"]),
                cohort_id=str(record["cohort_id"]),
                status=status,
                config_path=_safe_path(root, record["config"]),
                run_directory=run_directory,
                attempts=len(starts),
                evidence=evidence,
                error=error,
            )
        )
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
            raise ReferenceValidationStudyError("Validation report bytes changed")
        assessment = assess_reference_validation(
            plan,
            tuple(
                run.evidence for run in run_states if run.evidence is not None
            ),
        )
        status = "completed"
    elif any(run.status == "orphaned" for run in run_states):
        status = "interrupted"
    elif all(run.status == "completed" for run in run_states):
        status = "awaiting_report"
    elif any(run.status == "failed" for run in run_states):
        status = "ready_to_retry"
    else:
        status = "ready"
    return ReferenceValidationStudySnapshot(
        study_directory=root,
        study_id=str(manifest["study_id"]),
        plan=plan,
        status=status,
        runs=tuple(run_states),
        event_count=len(events),
        assessment=assessment,
        report_json_path=report_json,
        report_html_path=report_html,
    )
def _report_payload(
    snapshot: ReferenceValidationStudySnapshot,
    assessment: ReferenceValidationAssessment,
) -> dict[str, object]:
    finalists = {item.finalist_id: item for item in snapshot.plan.finalists}
    return {
        "report_version": "0.1",
        "study_id": snapshot.study_id,
        "plan_fingerprint": snapshot.plan.fingerprint,
        "status": assessment.status,
        "claim_scope": (
            "Robustness within the predeclared finalist search space; not a universal "
            "or automatically biologically optimal parameter claim."
        ),
        "recommended_finalist": (
            None
            if assessment.recommended_finalist_id is None
            else finalists[assessment.recommended_finalist_id].as_manifest()
        ),
        "assessment": assessment.as_manifest(),
        "design": {
            "subject_count": snapshot.plan.subject_count,
            "training_subject_count": len(snapshot.plan.training_subjects),
            "reserved_holdout_subject_count": len(snapshot.plan.heldout_subjects),
            "resample_count": snapshot.plan.resample_count,
            "run_count": len(snapshot.plan.run_specs),
            "external_metric": (
                "Symmetric deterministic vertex-to-triangle surface-distance p95"
            ),
            "selection_rule": list(snapshot.plan.selection_rule),
        },
        "finalists": [item.as_manifest() for item in assessment.finalists],
        "warnings": list(assessment.warnings),
        "required_next_gates": list(assessment.next_gates),
        "limitations": list(snapshot.plan.limitations),
    }


def _report_html(report: Mapping[str, object]) -> str:
    assessment = report["assessment"]
    recommended = report["recommended_finalist"]
    winner = "No unique robust finalist"
    if recommended is not None:
        winner = f"{recommended['label']} ({recommended['finalist_id']})"
    finalist_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['finalist_id']))}</td>"
        f"<td>{float(item['group_win_fraction']):.1%}</td>"
        f"<td>{html.escape(str(item['median_external_residual_p95']))}</td>"
        f"<td>{html.escape(str(item['median_distortion_p95']))}</td>"
        f"<td>{html.escape('; '.join(item['rejection_reasons']) or 'none')}</td>"
        "</tr>"
        for item in report["finalists"]
    )
    next_steps = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["required_next_gates"]
    )
    limitations = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["limitations"]
    )
    warnings = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["warnings"]
    ) or "<li>No additional numerical warning was triggered.</li>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DiffeoForge Validation Lab report</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:36px auto;
padding:0 24px;color:#103b3b;line-height:1.45}}h1,h2{{color:#073c3b}}
.notice{{background:#e3f6ef;border-left:5px solid #13856f;padding:14px 18px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #c8d9d7;
padding:10px;text-align:left;vertical-align:top}}th{{background:#eef5f4}}
code{{background:#eef5f4;padding:2px 5px}}</style></head><body>
<h1>DiffeoForge Validation Lab report</h1>
<p class="notice"><strong>Evidence status:</strong>
{html.escape(str(assessment['confidence']))}.<br><strong>Preferred finalist:</strong>
{html.escape(winner)}</p>
<p><strong>Claim boundary:</strong> {html.escape(str(report['claim_scope']))}</p>
<h2>Frozen design</h2><p>{report['design']['training_subject_count']} training subjects;
{report['design']['reserved_holdout_subject_count']} untouched heldout subjects;
{report['design']['resample_count']} resamples; {report['design']['run_count']} atlas runs.</p>
<p>Practical error margin: {assessment['practical_error_margin']}
({html.escape(str(assessment['practical_error_margin_basis']))}).</p>
<h2>Finalist comparison</h2><table><thead><tr><th>Finalist</th><th>Cohort wins</th>
<th>Median external p95</th><th>Median distortion p95</th><th>Rejections</th></tr></thead>
<tbody>{finalist_rows}</tbody></table>
<h2>Warnings</h2><ul>{warnings}</ul><h2>Evidence still required</h2><ol>{next_steps}</ol>
<h2>Limitations</h2><ul>{limitations}</ul>
<p>Study: <code>{html.escape(str(report['study_id']))}</code><br>Plan:
<code>{html.escape(str(report['plan_fingerprint']))}</code></p></body></html>"""


def _finalize_study(root: Path) -> ReferenceValidationStudySnapshot:
    snapshot = load_reference_validation_study(root)
    if snapshot.status == "completed":
        return snapshot
    if any(run.evidence is None for run in snapshot.runs):
        raise ReferenceValidationStudyError(
            "Validation report requires every predeclared run to complete"
        )
    assessment = assess_reference_validation(
        snapshot.plan, tuple(run.evidence for run in snapshot.runs if run.evidence is not None)
    )
    report = _report_payload(snapshot, assessment)
    json_path = root / VALIDATION_REPORT_JSON
    html_path = root / VALIDATION_REPORT_HTML
    json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(json_path, report, overwrite=False)
    write_text_safely(html_path, _report_html(report), overwrite=False)
    _append_event(
        root,
        "study_completed",
        {
            "assessment_status": assessment.status,
            "recommended_finalist_id": assessment.recommended_finalist_id,
            "report_json": _relative(root, json_path),
            "report_json_sha256": sha256_file(json_path),
            "report_html": _relative(root, html_path),
            "report_html_sha256": sha256_file(html_path),
        },
    )
    return load_reference_validation_study(root)


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
        request_id=f"validation-{uuid4().hex}",
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


class ReferenceValidationStudyRunner:
    """Execute every missing frozen run sequentially and resume safely."""

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
        event_callback: ValidationEventCallback | None = None,
    ) -> ReferenceValidationStudySnapshot:
        snapshot = load_reference_validation_study(self.study_directory)
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
                validation_run_id: str = state.run_id,
            ) -> None:
                if event_callback is not None:
                    event_callback(
                        {
                            "event": "worker_event",
                            "run_id": validation_run_id,
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
                            "run_id": state.run_id,
                            "attempt": state.attempts + 1,
                            "run_directory": _relative(
                                self.study_directory, request.destination
                            ),
                            "error": "Validation execution was cancelled safely.",
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
        updated = load_reference_validation_study(self.study_directory)
        if not self._cancel_requested and all(
            run.status == "completed" for run in updated.runs
        ):
            updated = _finalize_study(self.study_directory)
            if event_callback is not None:
                event_callback(
                    {
                        "event": "validation_completed",
                        "status": updated.assessment.status if updated.assessment else None,
                        "completed_run_count": updated.completed_run_count,
                    }
                )
        return updated

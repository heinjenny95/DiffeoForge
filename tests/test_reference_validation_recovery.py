from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from test_reference_validation import _calibrated_project

import diffeoforge.reference_validation_recovery as recovery
from diffeoforge.cli import main
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_validation import ValidationRunEvidence
from diffeoforge.reference_validation_study import (
    ReferenceValidationStudyError,
    ReferenceValidationStudyRunner,
    _append_event,
    _load_events,
    create_reference_validation_study,
    load_reference_validation_study,
    validation_study_writer_lock,
)
from diffeoforge.runs import prepare_run


@pytest.fixture
def failed_evaluation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    snapshot = create_reference_validation_study(
        _calibrated_project(tmp_path),
        tmp_path / "study",
        resample_count=1,
    )
    state = snapshot.runs[0]
    run = prepare_run(
        state.config_path, run_id="attempt-01", output_directory=state.config_path.parent / "runs"
    )
    atlas = run / "output" / "estimated-template.vtk"
    shutil.copy2(next((run / "input/template").glob("*.vtk")), atlas)
    inventory = {
        "inventory_version": "0.1",
        "files": [
            {
                "path": atlas.name,
                "bytes": atlas.stat().st_size,
                "sha256": sha256_file(atlas),
            }
        ],
    }
    (run / "output-inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    (run / "logs/convergence.csv").write_text(
        "iteration,log_likelihood,attachment,regularity\n0,-10,-10,0\n1,-5,-4,-1\n",
        encoding="utf-8",
    )
    (run / "logs/deformetrica.log").write_text("Tolerance threshold met.\n", encoding="utf-8")
    result = {
        "result_version": "0.1",
        "run_id": "attempt-01",
        "status": "completed",
        "started_at": "2026-07-15T12:00:00Z",
        "ended_at": "2026-07-15T12:01:00Z",
        "duration_seconds": 60.0,
        "return_code": 0,
        "execution_error": None,
        "convergence_rows": 2,
        "outputs": {
            "file_count": 1,
            "total_bytes": atlas.stat().st_size,
            "inventory_path": "output-inventory.json",
            "inventory_sha256": sha256_file(run / "output-inventory.json"),
        },
    }
    (run / "result.json").write_text(json.dumps(result), encoding="utf-8")
    with (run / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": "started", "timestamp": result["started_at"]}) + "\n")
        stream.write(
            json.dumps(
                {
                    "event": "completed",
                    "timestamp": result["ended_at"],
                    "return_code": 0,
                    "duration_seconds": 60.0,
                }
            )
            + "\n"
        )
    for item in snapshot.runs:
        relative = str(
            item.config_path.parent.relative_to(snapshot.study_directory) / "runs/attempt-01"
        )
        _append_event(
            snapshot.study_directory,
            "run_started",
            {
                "run_id": item.run_id,
                "run_directory": relative,
                "attempt": 1,
            },
        )
        _append_event(
            snapshot.study_directory,
            "run_failed",
            {
                "run_id": item.run_id,
                "run_directory": relative,
                "attempt": 1,
                "error": "Point-to-surface metric found a zero-area triangle",
            },
        )

    def collect(run_directory, *, run_id, finalist_id, cohort_id, progress_callback=None):
        cohort = next(c for c in snapshot.plan.cohorts if c.cohort_id == cohort_id)
        return ValidationRunEvidence(
            run_id=run_id,
            finalist_id=finalist_id,
            cohort_id=cohort_id,
            completed=True,
            converged=True,
            invalid_face_count=0,
            external_residual_p95=0.01,
            distortion_p95=0.02,
            runtime_seconds=60.0,
            atlas_path=str(atlas),
            subject_residual_p95=tuple((name, 0.01) for name in cohort.subject_filenames),
        )

    monkeypatch.setattr(recovery, "collect_reference_validation_run_evidence", collect)
    return snapshot.study_directory, state.run_id, run, tmp_path / "recovered.json"


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256_file(path) for path in root.rglob("*") if path.is_file()
    }


def test_export_is_read_only_and_adoption_preserves_original_attempt(failed_evaluation) -> None:
    root, run_id, run, output = failed_evaluation
    before = _hashes(root)
    recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    assert _hashes(root) == before
    digest = sha256_file(output)
    assert output.with_suffix(".json.sha256").read_text().strip() == digest
    original_ledger = (root / "events.jsonl").read_bytes()
    original_run = _hashes(run)

    adopted = recovery.adopt_reference_validation_evidence_recovery(
        root,
        output,
        expected_sha256=digest,
    )
    assert adopted.completed_run_count == 1
    assert adopted.runs[0].attempts == 1
    assert (root / "events.jsonl").read_bytes().startswith(original_ledger)
    assert _hashes(run) == original_run
    ledger = (root / "events.jsonl").read_bytes()
    assert (
        recovery.adopt_reference_validation_evidence_recovery(
            root,
            output,
            expected_sha256=digest,
        )
        == adopted
    )
    assert (root / "events.jsonl").read_bytes() == ledger


def test_export_during_other_active_run_but_adoption_blocked(failed_evaluation) -> None:
    root, run_id, _, output = failed_evaluation
    other = load_reference_validation_study(root).runs[1]
    _append_event(
        root,
        "run_started",
        {
            "run_id": other.run_id,
            "run_directory": "other-attempt",
            "attempt": 2,
        },
    )
    before = _hashes(root)
    recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    with pytest.raises(ReferenceValidationStudyError, match="pending or active"):
        recovery.adopt_reference_validation_evidence_recovery(
            root,
            output,
            expected_sha256=sha256_file(output),
        )
    assert _hashes(root) == before


def test_recovery_never_writes_in_study_or_overwrites_bundle(failed_evaluation) -> None:
    root, run_id, _, output = failed_evaluation
    with pytest.raises(ReferenceValidationStudyError, match="outside"):
        recovery.export_reference_validation_evidence_recovery(root, run_id, root / "recovery.json")
    output.write_text("keep me", encoding="utf-8")
    with pytest.raises(ReferenceValidationStudyError, match="already exists"):
        recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    assert output.read_text() == "keep me"


def test_changed_output_is_not_recoverable(failed_evaluation) -> None:
    root, run_id, run, output = failed_evaluation
    atlas = run / "output/estimated-template.vtk"
    original = atlas.read_bytes()
    atlas.write_bytes(original.replace(b"0", b"1", 1))
    with pytest.raises(ReferenceValidationStudyError, match="integrity"):
        recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    assert not output.exists()


def test_changed_bundle_is_not_adopted(failed_evaluation) -> None:
    root, run_id, _, output = failed_evaluation
    recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    digest = sha256_file(output)
    output.write_text(output.read_text() + " ", encoding="utf-8")
    before = (root / "events.jsonl").read_bytes()
    with pytest.raises(ReferenceValidationStudyError, match="SHA-256"):
        recovery.adopt_reference_validation_evidence_recovery(root, output, expected_sha256=digest)
    assert (root / "events.jsonl").read_bytes() == before


def test_changed_source_since_export_is_not_adopted(failed_evaluation) -> None:
    root, run_id, run, output = failed_evaluation
    recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    (run / "logs/deformetrica.log").write_text("changed log", encoding="utf-8")
    before = (root / "events.jsonl").read_bytes()
    with pytest.raises(ReferenceValidationStudyError, match="no longer matches"):
        recovery.adopt_reference_validation_evidence_recovery(
            root,
            output,
            expected_sha256=sha256_file(output),
        )
    assert (root / "events.jsonl").read_bytes() == before


def test_new_runner_refuses_to_recompute_successful_backend(failed_evaluation) -> None:
    root, _, _, _ = failed_evaluation
    for state in load_reference_validation_study(root).runs[1:]:
        state.run_directory.mkdir(parents=True, exist_ok=True)
        (state.run_directory / "result.json").write_text(
            json.dumps({"status": "completed", "return_code": 0}),
            encoding="utf-8",
        )
    before = _hashes(root)

    def forbidden(request):
        pytest.fail("Recovery must not start a backend")

    with pytest.raises(ReferenceValidationStudyError, match="already completed"):
        ReferenceValidationStudyRunner(root, controller_factory=forbidden).run_all()
    assert _hashes(root) == before


def test_recovery_cli_exports_and_adopts_without_execution(failed_evaluation, capsys) -> None:
    root, run_id, _, output = failed_evaluation
    assert (
        main(
            [
                "reference-validation-evidence-export",
                str(root),
                "--run-id",
                run_id,
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert "No atlas was executed" in capsys.readouterr().out
    assert (
        main(
            [
                "reference-validation-evidence-adopt",
                str(root),
                str(output),
                "--expect-sha256",
                sha256_file(output),
            ]
        )
        == 0
    )
    assert "1/" in capsys.readouterr().out


def test_existing_writer_excludes_adoption_and_runner(failed_evaluation) -> None:
    root, run_id, _, output = failed_evaluation
    recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    before = (root / "events.jsonl").read_bytes()
    with validation_study_writer_lock(root):
        with pytest.raises(ReferenceValidationStudyError, match="Another validation writer"):
            recovery.adopt_reference_validation_evidence_recovery(
                root,
                output,
                expected_sha256=sha256_file(output),
            )
        with pytest.raises(ReferenceValidationStudyError, match="Another validation writer"):
            ReferenceValidationStudyRunner(root).run_all()
    assert not (root / ".validation-writer.lock").exists()
    assert (root / "events.jsonl").read_bytes() == before


def test_nonfinite_recovered_metric_is_not_published(failed_evaluation, monkeypatch) -> None:
    from dataclasses import replace

    root, run_id, _, output = failed_evaluation
    original = recovery.collect_reference_validation_run_evidence

    def invalid(*args, **kwargs):
        return replace(original(*args, **kwargs), external_residual_p95=float("nan"))

    monkeypatch.setattr(recovery, "collect_reference_validation_run_evidence", invalid)
    with pytest.raises(ReferenceValidationStudyError, match="finite"):
        recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    assert not output.exists()


def test_changed_source_during_computation_is_not_published(failed_evaluation, monkeypatch) -> None:
    root, run_id, run, output = failed_evaluation
    original = recovery.collect_reference_validation_run_evidence

    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        (run / "logs/deformetrica.log").write_text("changed during evaluation", encoding="utf-8")
        return value

    monkeypatch.setattr(recovery, "collect_reference_validation_run_evidence", changed)
    with pytest.raises(ReferenceValidationStudyError, match="changed while"):
        recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    assert not output.exists()


def test_changed_staged_input_is_not_recoverable(failed_evaluation) -> None:
    root, run_id, run, output = failed_evaluation
    staged = next((run / "input/subjects").glob("*.vtk"))
    staged.write_bytes(staged.read_bytes().replace(b"0", b"1", 1))
    with pytest.raises(ReferenceValidationStudyError, match="Protected run artifact"):
        recovery.export_reference_validation_evidence_recovery(root, run_id, output)
    assert not output.exists()


def test_runner_can_continue_pending_work_without_restarting_finished_atlas(
    failed_evaluation,
) -> None:
    from types import SimpleNamespace

    root, run_id, run, _ = failed_evaluation
    # Keep only study creation and the first failed-evaluation attempt; the
    # other predeclared runs have not yet been attempted in this fixture.
    events = _load_events(root)[:3]
    (root / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    before = _hashes(run)
    requested = []

    class CancelNextRun:
        def __init__(self, request):
            requested.append(request)

        def run(self, *, event_callback=None):
            return SimpleNamespace(completed=False)

        def request_cancel(self):
            return True

    snapshot = ReferenceValidationStudyRunner(root, controller_factory=CancelNextRun).run_all()
    assert len(requested) == 1
    assert requested[0].config_path != snapshot.runs[0].config_path
    assert snapshot.runs[0].run_id == run_id
    assert snapshot.runs[0].attempts == 1
    assert _hashes(run) == before

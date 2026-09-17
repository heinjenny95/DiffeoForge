from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffeoforge.desktop.run_location import (
    RunFolderState,
    RunLookupPurpose,
    describe_run_location,
    explain_missing_run,
)


def _reference_run(
    directory: Path,
    *,
    result: dict | None = None,
    latest_event: str | None = None,
) -> Path:
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps({"backend": {"id": "deformetrica_reference"}}),
        encoding="utf-8",
    )
    if result is not None:
        (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
    if latest_event is not None:
        (directory / "events.jsonl").write_text(
            json.dumps({"event": "prepared"}) + "\n" + json.dumps({"event": latest_event}) + "\n",
            encoding="utf-8",
        )
    return directory


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("result", "latest_event", "expected"),
    [
        ({"status": "completed", "return_code": 0}, "completed", RunFolderState.COMPLETED),
        (
            {"status": "interrupted", "checkpoint": {"available": True}},
            "interrupted",
            RunFolderState.STOPPED_WITH_CHECKPOINT,
        ),
        (
            {"status": "interrupted", "checkpoint": {"available": False}},
            "interrupted",
            RunFolderState.STOPPED_WITHOUT_CHECKPOINT,
        ),
        ({"status": "failed"}, "failed", RunFolderState.STOPPED_WITHOUT_CHECKPOINT),
        (None, "started", RunFolderState.STARTED),
        (None, "prepared", RunFolderState.PREPARED),
        (None, None, RunFolderState.UNRECOGNIZED),
    ],
)
def test_each_lifecycle_state_is_classified_without_changing_the_run(
    tmp_path: Path,
    result,
    latest_event,
    expected,
) -> None:
    run = _reference_run(tmp_path / "runs" / "run-001", result=result, latest_event=latest_event)
    before = _snapshot(tmp_path)

    for selected in (run, tmp_path):
        description = describe_run_location(selected)
        assert [(item.run_directory, item.state) for item in description.findings] == [
            (run.resolve(), expected)
        ]

    assert _snapshot(tmp_path) == before


def test_modern_result_is_reported_as_completed(tmp_path: Path) -> None:
    run = tmp_path / "diffeoforge-project" / "runs" / "modern-001"
    run.mkdir(parents=True)
    (run / "workflow-manifest.json").write_text("{}\n", encoding="utf-8")

    description = describe_run_location(tmp_path)

    assert [item.state for item in description.findings] == [RunFolderState.COMPLETED]


def test_interrupted_run_without_checkpoint_gets_a_distinct_explanation(tmp_path: Path) -> None:
    run = _reference_run(
        tmp_path / "runs" / "desktop-ref-crashed",
        result={
            "status": "interrupted",
            "checkpoint": {"available": False},
            "convergence_rows": 6,
            "recovery": {"process_stopped_confirmed": True},
        },
        latest_event="interrupted",
    )

    for purpose in RunLookupPurpose:
        message = explain_missing_run(purpose, describe_run_location(run))
        assert str(run.resolve()) in message
        assert "desktop-ref-crashed" in message
        assert "no checkpoint was ever written" in message
        assert "cannot be continued" in message
        assert "recorded by crash recovery" in message
        assert "6 recorded iteration row(s)" in message
        assert "Nothing was loaded and nothing was changed." in message
        assert "Use “" not in message


def test_wrong_action_for_the_found_state_names_the_fitting_action(tmp_path: Path) -> None:
    _reference_run(
        tmp_path / "runs" / "done",
        result={"status": "completed", "return_code": 0},
        latest_event="completed",
    )
    _reference_run(tmp_path / "runs" / "unclean", latest_event="started")
    description = describe_run_location(tmp_path)

    message = explain_missing_run(RunLookupPurpose.RESUME_INTERRUPTED, description)

    assert "done: a completed Deformetrica run. Use “Open completed run…” for it." in message
    assert "Use “Recover after crash…” for it." in message
    assert "Use “Resume interrupted run…”" not in message


def test_rejected_candidate_reason_is_reported_once(tmp_path: Path) -> None:
    run = _reference_run(
        tmp_path / "runs" / "interrupted-001",
        result={"status": "interrupted", "checkpoint": {"available": True}},
        latest_event="interrupted",
    )

    message = explain_missing_run(
        RunLookupPurpose.RESUME_INTERRUPTED,
        describe_run_location(tmp_path),
        ((run.resolve(), "Source checkpoint size differs from its inventory"),),
    )

    assert "failed full verification" in message
    assert "interrupted-001: Source checkpoint size differs from its inventory" in message
    assert message.count("interrupted-001") == 1


def test_selection_inside_a_run_suggests_the_enclosing_run_folder(tmp_path: Path) -> None:
    run = _reference_run(tmp_path / "runs" / "run-001", latest_event="started")
    inner = run / "output"
    inner.mkdir()

    description = describe_run_location(inner)
    message = explain_missing_run(RunLookupPurpose.RECOVER_CRASHED, description)

    assert description.findings == ()
    assert description.enclosing_run == run.resolve()
    assert f"Select this folder instead: {run.resolve()}" in message


def test_selection_above_or_at_the_runs_folder_suggests_the_right_level(tmp_path: Path) -> None:
    pilot = tmp_path / "pilot"
    _reference_run(pilot / "selected" / "runs" / "run-001", latest_event="started")

    above = describe_run_location(pilot)
    at_runs = describe_run_location(pilot / "selected" / "runs")

    assert above.findings == ()
    assert above.nearby_run_roots == ((pilot / "selected").resolve(),)
    assert at_runs.nearby_run_roots == ((pilot / "selected").resolve(),)
    message = explain_missing_run(RunLookupPurpose.RECOVER_CRASHED, above)
    assert "Run folders exist one level away" in message
    assert str((pilot / "selected").resolve()) in message


def test_unrelated_or_missing_folder_is_stated_plainly(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    for selected in (empty, tmp_path / "missing"):
        message = explain_missing_run(
            RunLookupPurpose.OPEN_COMPLETED, describe_run_location(selected)
        )
        assert "No DiffeoForge run folder was found at this location." in message
        assert "manifest.json" in message
        assert "Nothing was loaded and nothing was changed." in message

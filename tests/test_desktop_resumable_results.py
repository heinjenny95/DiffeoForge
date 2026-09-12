from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import diffeoforge.desktop.resumable_results as resumable_results
from diffeoforge.desktop.resumable_results import (
    AbandonedReferenceRun,
    discover_abandoned_reference_runs,
    discover_resumable_reference_runs,
    recover_abandoned_reference_run,
)


def test_resumable_discovery_returns_only_fully_verified_reference_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    source = project / "runs" / "interrupted-001"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps({"backend": {"id": "deformetrica_reference"}}),
        encoding="utf-8",
    )
    (source / "result.json").write_text(
        json.dumps({"status": "interrupted"}),
        encoding="utf-8",
    )
    source_config = source / "config" / "source-config.yaml"
    source_config.parent.mkdir()
    source_config.write_text("reviewed\n", encoding="utf-8")
    manifest = {
        "project": {"name": "Production atlas"},
        "source_config": {"sha256": "a" * 64},
        "input_count": {"subjects": 300, "templates": 1},
    }
    monkeypatch.setattr(
        resumable_results,
        "inspect_resume_source",
        lambda path: SimpleNamespace(
            source_run=Path(path).resolve(),
            manifest=manifest,
            terminal_status="interrupted",
            checkpoint_bytes=123_456,
        ),
    )

    discovered = discover_resumable_reference_runs(project)

    assert len(discovered) == 1
    assert discovered[0].run_directory == source.resolve()
    assert discovered[0].project_name == "Production atlas"
    assert discovered[0].subject_count == 300
    assert discovered[0].checkpoint_bytes == 123_456
    assert discovered[0].source_config_path == source_config.resolve()


def test_resumable_discovery_ignores_completed_and_unverifiable_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runs = tmp_path / "runs"
    completed = runs / "completed"
    interrupted = runs / "interrupted"
    for path, status in ((completed, "completed"), (interrupted, "interrupted")):
        path.mkdir(parents=True)
        (path / "manifest.json").write_text(
            json.dumps({"backend": {"id": "deformetrica_reference"}}),
            encoding="utf-8",
        )
        (path / "result.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    monkeypatch.setattr(
        resumable_results,
        "inspect_resume_source",
        lambda _path: (_ for _ in ()).throw(ValueError("checkpoint mismatch")),
    )

    assert discover_resumable_reference_runs(tmp_path) == ()


def test_abandoned_discovery_returns_only_verified_started_reference_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    source = project / "runs" / "unclean-001"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps({"backend": {"id": "deformetrica_reference"}}),
        encoding="utf-8",
    )
    (source / "events.jsonl").write_text(
        json.dumps({"timestamp": "2026-08-11T12:00:00Z", "event": "started"})
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "project": {"name": "Production atlas"},
        "input_count": {"subjects": 300, "templates": 1},
    }
    monkeypatch.setattr(
        resumable_results,
        "inspect_abandoned_run",
        lambda path: SimpleNamespace(
            run_directory=Path(path).resolve(),
            manifest=manifest,
            started_event={"timestamp": "2026-08-11T12:00:00Z", "event": "started"},
            checkpoint_bytes=2_000_000,
            terminal_result=None,
        ),
    )

    discovered = discover_abandoned_reference_runs(project)

    assert discovered == (
        AbandonedReferenceRun(
            run_directory=source.resolve(),
            project_name="Production atlas",
            subject_count=300,
            started_at="2026-08-11T12:00:00Z",
            checkpoint_bytes=2_000_000,
        ),
    )


def test_abandoned_discovery_ignores_terminal_or_wrong_backend(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for name, backend, event in (
        ("completed", "deformetrica_reference", "completed"),
        ("modern", "modern_cpu", "started"),
    ):
        candidate = runs / name
        candidate.mkdir(parents=True)
        (candidate / "manifest.json").write_text(
            json.dumps({"backend": {"id": backend}}),
            encoding="utf-8",
        )
        (candidate / "events.jsonl").write_text(
            json.dumps({"timestamp": "2026-08-11T12:00:00Z", "event": event}) + "\n",
            encoding="utf-8",
        )

    assert discover_abandoned_reference_runs(tmp_path) == ()


def test_recover_abandoned_run_returns_verified_resume_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = (tmp_path / "runs" / "unclean-001").resolve()
    source.mkdir(parents=True)
    abandoned = AbandonedReferenceRun(
        run_directory=source,
        project_name="Production atlas",
        subject_count=300,
        started_at="2026-08-11T12:00:00Z",
        checkpoint_bytes=123_456,
    )
    manifest = {
        "project": {"name": "Production atlas"},
        "source_config": {"sha256": "a" * 64},
        "input_count": {"subjects": 300, "templates": 1},
    }
    calls = []
    monkeypatch.setattr(
        resumable_results,
        "recover_run",
        lambda path, **kwargs: calls.append((Path(path), kwargs))
        or {"status": "interrupted", "checkpoint": {"available": True}},
    )
    monkeypatch.setattr(
        resumable_results,
        "inspect_resume_source",
        lambda path: SimpleNamespace(
            source_run=Path(path),
            manifest=manifest,
            terminal_status="interrupted",
            checkpoint_bytes=123_456,
        ),
    )

    recovered = recover_abandoned_reference_run(abandoned, reason="power loss")

    assert calls == [
        (
            source,
            {"reason": "power loss", "confirm_process_stopped": True},
        )
    ]
    assert recovered.run_directory == source
    assert recovered.terminal_status == "interrupted"
    assert recovered.resumable is not None
    assert recovered.resumable.checkpoint_bytes == 123_456


def test_recovered_completed_terminal_result_is_not_offered_for_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = (tmp_path / "runs" / "unclean-001").resolve()
    source.mkdir(parents=True)
    abandoned = AbandonedReferenceRun(
        run_directory=source,
        project_name="Production atlas",
        subject_count=300,
        started_at="2026-08-11T12:00:00Z",
        checkpoint_bytes=123_456,
        retained_terminal_status="completed",
    )
    monkeypatch.setattr(
        resumable_results,
        "recover_run",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "checkpoint": {"available": True},
        },
    )
    monkeypatch.setattr(
        resumable_results,
        "inspect_resume_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("completed result must not enter resume verification")
        ),
    )

    recovered = recover_abandoned_reference_run(abandoned, reason="power loss")

    assert recovered.terminal_status == "completed"
    assert recovered.resumable is None

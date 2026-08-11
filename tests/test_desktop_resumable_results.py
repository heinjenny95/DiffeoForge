from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import diffeoforge.desktop.resumable_results as resumable_results
from diffeoforge.desktop.resumable_results import discover_resumable_reference_runs


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

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from diffeoforge.desktop.completed_results import (
    CompletedResultDiscoveryError,
    discover_completed_results,
)


def _write_reference_run(directory: Path, *, completed: bool = True) -> Path:
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps({"backend": {"id": "deformetrica_reference"}}),
        encoding="utf-8",
    )
    (directory / "result.json").write_text(
        json.dumps(
            {
                "status": "completed" if completed else "running",
                "return_code": 0 if completed else None,
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_discovers_exact_completed_reference_run(tmp_path: Path) -> None:
    run = _write_reference_run(tmp_path / "desktop-ref-complete")

    results = discover_completed_results(run)

    assert len(results) == 1
    assert results[0].run_directory == run.resolve()
    assert results[0].reference is True


def test_discovers_only_completed_runs_from_project_folder(tmp_path: Path) -> None:
    project = tmp_path / "study"
    completed = _write_reference_run(
        project / "diffeoforge-project" / "runs" / "desktop-ref-complete"
    )
    _write_reference_run(
        project / "diffeoforge-project" / "runs" / "desktop-ref-running",
        completed=False,
    )

    results = discover_completed_results(project)

    assert tuple(result.run_directory for result in results) == (completed.resolve(),)


def test_completed_runs_are_sorted_newest_first(tmp_path: Path) -> None:
    project = tmp_path / "project"
    older = _write_reference_run(project / "runs" / "older")
    newer = _write_reference_run(project / "runs" / "newer")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

    results = discover_completed_results(project)

    assert tuple(result.run_directory for result in results) == (
        newer.resolve(),
        older.resolve(),
    )


def test_rejects_missing_or_symbolic_selection(tmp_path: Path) -> None:
    with pytest.raises(CompletedResultDiscoveryError, match="missing"):
        discover_completed_results(tmp_path / "missing")

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    with pytest.raises(CompletedResultDiscoveryError, match="symbolic"):
        discover_completed_results(link)

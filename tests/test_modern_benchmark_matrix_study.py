from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("psutil")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.modern_benchmark import (  # noqa: E402
    REPORT_CSV_NAME,
    collect_modern_benchmark,
    write_modern_benchmark_report,
)
from diffeoforge.modern_benchmark_matrix_design import (  # noqa: E402
    create_modern_benchmark_matrix_design,
)
from diffeoforge.modern_benchmark_matrix_study import (  # noqa: E402
    EVENTS_NAME,
    MANIFEST_NAME,
    STATE_NAME,
    ModernBenchmarkStudyError,
    _manifest_schema,
    _study_lock,
    inspect_modern_benchmark_matrix_study_run,
    run_modern_benchmark_matrix_study,
    verify_modern_benchmark_matrix_study_run,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
MESHES = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-07-17T12:00:00+00:00"


def _write_config(path: Path) -> Path:
    config = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    config["input"]["directory"] = str(MESHES)
    config["input"]["template"] = str(MESHES / "template.vtk")
    config["output"]["directory"] = str(path.parent / "future-run")
    config["runtime"]["pairwise_evaluation"] = {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _sample(_number: int = 1) -> dict:
    return {
        "wall_time_ns": 100,
        "rss_before_bytes": 1_000,
        "sampled_peak_rss_bytes": 2_000,
        "sampled_rss_delta_bytes": 1_000,
        "rss_sample_count": 3,
        "objective": -4.5,
        "gradient_norm": 7.25,
    }


def _publish_without_computing(
    config_path,
    *,
    subject_count,
    repeats,
    warmup_evaluations,
    tile_autograd_strategy,
    query_tile_size,
    source_tile_size,
    destination,
):
    report = collect_modern_benchmark(
        config_path,
        subject_count=subject_count,
        repeats=repeats,
        warmup_evaluations=warmup_evaluations,
        tile_autograd_strategy=tile_autograd_strategy,
        query_tile_size=query_tile_size,
        source_tile_size=source_tile_size,
        created_at=FIXED_TIME,
    )
    return write_modern_benchmark_report(report, destination)


def test_interrupted_study_reconciles_valid_prefix_and_resumes_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_matrix_design(
        config,
        subject_counts=[1],
        tile_shapes=[(3, 5)],
        repeats_per_condition=1,
        warmup_evaluations=0,
        order_seed=7,
        destination=tmp_path / "design",
    )
    import diffeoforge.modern_benchmark as benchmark_module
    import diffeoforge.modern_benchmark_matrix_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(kwargs["tile_autograd_strategy"])
        if len(calls) == 2:
            raise RuntimeError("injected interruption")
        return _publish_without_computing(*args, **kwargs)

    monkeypatch.setattr(study_module, "benchmark_modern_objective", fail_second)
    run = tmp_path / "study-run"
    first_progress = []
    with pytest.raises(ModernBenchmarkStudyError, match="injected interruption"):
        run_modern_benchmark_matrix_study(
            design,
            config,
            destination=run,
            progress_callback=first_progress.append,
        )
    assert [event.status for event in first_progress] == [
        "study_started",
        "condition_started",
        "condition_completed",
        "condition_started",
        "study_interrupted",
    ]
    state = json.loads((run / STATE_NAME).read_text(encoding="utf-8"))
    assert state["status"] == "interrupted"
    assert len(state["completed_condition_ids"]) == 1
    assert state["active_condition_id"] is None
    status = inspect_modern_benchmark_matrix_study_run(run)
    assert status["status"] == "interrupted"
    assert status["verified_report_count"] == 1
    assert status["state_completed_condition_count"] == 1
    assert status["reconciliation_required"] is False
    assert status["next_condition"] is not None

    state["completed_condition_ids"].append(status["next_condition"]["condition_id"])
    (run / STATE_NAME).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(ModernBenchmarkStudyError, match="claims completed"):
        inspect_modern_benchmark_matrix_study_run(run)

    state["completed_condition_ids"] = []
    (run / STATE_NAME).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    status = inspect_modern_benchmark_matrix_study_run(run)
    assert status["verified_report_count"] == 1
    assert status["state_completed_condition_count"] == 0
    assert status["reconciliation_required"] is True

    resumed_calls = []

    def resume(*args, **kwargs):
        resumed_calls.append(kwargs["tile_autograd_strategy"])
        return _publish_without_computing(*args, **kwargs)

    monkeypatch.setattr(study_module, "benchmark_modern_objective", resume)
    resumed_progress = []
    assert (
        run_modern_benchmark_matrix_study(
            design,
            config,
            destination=run,
            progress_callback=resumed_progress.append,
        )
        == run.resolve()
    )
    assert len(resumed_calls) == 1
    assert [event.status for event in resumed_progress] == [
        "condition_reconciled",
        "study_resumed",
        "condition_started",
        "condition_completed",
        "study_completed",
    ]
    manifest = verify_modern_benchmark_matrix_study_run(run)
    assert manifest["status"] == "complete"
    assert manifest["analysis_performed"] is False
    assert len(manifest["conditions"]) == 2
    assert _manifest_schema()["title"] == (
        "DiffeoForge completed multi-tile matrix benchmark study run"
    )
    assert {condition["cell_id"] for condition in manifest["conditions"]} == {
        "subjects-000001-tiles-q000003-s000005"
    }
    assert {
        (
            condition["effective_pairwise_evaluation"]["query_tile_size"],
            condition["effective_pairwise_evaluation"]["source_tile_size"],
        )
        for condition in manifest["conditions"]
    } == {(3, 5)}
    events = [json.loads(line) for line in (run / EVENTS_NAME).read_text().splitlines()]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert any(event["event"] == "condition_failed" for event in events)
    assert events[-1]["event"] == "study_completed"

    complete_progress = []
    assert (
        run_modern_benchmark_matrix_study(
            design,
            config,
            destination=run,
            progress_callback=complete_progress.append,
        )
        == run.resolve()
    )
    assert [event.status for event in complete_progress] == ["study_already_complete"]


def test_config_or_raw_report_tampering_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_matrix_design(
        config,
        subject_counts=[1],
        tile_shapes=[(3, 5)],
        repeats_per_condition=1,
        warmup_evaluations=0,
        destination=tmp_path / "design",
    )
    import diffeoforge.modern_benchmark as benchmark_module
    import diffeoforge.modern_benchmark_matrix_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    monkeypatch.setattr(
        study_module, "benchmark_modern_objective", _publish_without_computing
    )
    run = run_modern_benchmark_matrix_study(
        design, config, destination=tmp_path / "run"
    )
    manifest = json.loads((run / MANIFEST_NAME).read_text(encoding="utf-8"))
    first_report = run / manifest["conditions"][0]["report_directory"]
    csv_path = first_report / REPORT_CSV_NAME
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("100,", "101,", 1),
        encoding="utf-8",
    )
    with pytest.raises(ModernBenchmarkStudyError, match="CSV rows differ"):
        verify_modern_benchmark_matrix_study_run(run)

    modified = yaml.safe_load(config.read_text(encoding="utf-8"))
    modified["runtime"]["threads"] += 1
    config.write_text(yaml.safe_dump(modified, sort_keys=False), encoding="utf-8")
    with pytest.raises(ModernBenchmarkStudyError, match="differs from the design"):
        run_modern_benchmark_matrix_study(
            design, config, destination=tmp_path / "other-run"
        )
    assert not (tmp_path / "other-run").exists()


def test_wrong_effective_plan_and_nonprefix_reports_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_matrix_design(
        config,
        subject_counts=[1],
        tile_shapes=[(3, 5), (5, 3)],
        repeats_per_condition=1,
        warmup_evaluations=0,
        order_seed=17,
        destination=tmp_path / "design",
    )
    import diffeoforge.modern_benchmark as benchmark_module
    import diffeoforge.modern_benchmark_matrix_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())

    def publish_wrong_plan(*args, **kwargs):
        kwargs["source_tile_size"] += 1
        return _publish_without_computing(*args, **kwargs)

    monkeypatch.setattr(
        study_module, "benchmark_modern_objective", publish_wrong_plan
    )
    with pytest.raises(ModernBenchmarkStudyError, match="Condition protocol differs"):
        run_modern_benchmark_matrix_study(
            design, config, destination=tmp_path / "wrong-plan-run"
        )

    def stop_before_report(*_args, **_kwargs):
        raise RuntimeError("stop before report")

    monkeypatch.setattr(study_module, "benchmark_modern_objective", stop_before_report)
    nonprefix_run = tmp_path / "nonprefix-run"
    with pytest.raises(ModernBenchmarkStudyError, match="stop before report"):
        run_modern_benchmark_matrix_study(
            design, config, destination=nonprefix_run
        )
    frozen = json.loads(
        (design / "matrix-design.json").read_text(encoding="utf-8")
    )
    later = frozen["conditions"][1]
    plan = later["effective_pairwise_evaluation"]
    _publish_without_computing(
        config,
        subject_count=later["subject_count"],
        repeats=frozen["protocol"]["repeats_per_condition"],
        warmup_evaluations=frozen["protocol"]["warmup_evaluations_per_repeat"],
        tile_autograd_strategy=later["tile_autograd_strategy"],
        query_tile_size=plan["query_tile_size"],
        source_tile_size=plan["source_tile_size"],
        destination=nonprefix_run / later["output_directory"],
    )
    with pytest.raises(ModernBenchmarkStudyError, match="outside frozen order"):
        inspect_modern_benchmark_matrix_study_run(nonprefix_run)


def test_event_manifest_and_design_family_tampering_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_matrix_design(
        config,
        subject_counts=[1],
        tile_shapes=[(3, 5)],
        repeats_per_condition=1,
        warmup_evaluations=0,
        destination=tmp_path / "matrix-design",
    )
    import diffeoforge.modern_benchmark as benchmark_module
    import diffeoforge.modern_benchmark_matrix_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    monkeypatch.setattr(
        study_module, "benchmark_modern_objective", _publish_without_computing
    )
    run = run_modern_benchmark_matrix_study(
        design, config, destination=tmp_path / "run"
    )
    events_path = run / EVENTS_NAME
    original_events = events_path.read_text(encoding="utf-8")
    event_records = [json.loads(line) for line in original_events.splitlines()]
    event_records[-1]["sequence"] += 1
    events_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in event_records),
        encoding="utf-8",
    )
    with pytest.raises(ModernBenchmarkStudyError, match="event sequence"):
        verify_modern_benchmark_matrix_study_run(run)
    events_path.write_text(original_events, encoding="utf-8")

    manifest_path = run / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["analysis_performed"] = True
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(ModernBenchmarkStudyError, match="sidecar does not match"):
        verify_modern_benchmark_matrix_study_run(run)

    from diffeoforge.modern_benchmark_design import create_modern_benchmark_design

    old_design = create_modern_benchmark_design(
        config,
        subject_counts=[1],
        repeats_per_condition=1,
        warmup_evaluations=0,
        destination=tmp_path / "single-tile-design",
    )
    with pytest.raises(RuntimeError, match="unexpected files"):
        run_modern_benchmark_matrix_study(
            old_design, config, destination=tmp_path / "wrong-family-run"
        )
    assert not (tmp_path / "wrong-family-run").exists()


def test_concurrent_lock_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    with _study_lock(root):
        with pytest.raises(ModernBenchmarkStudyError, match="Another process"):
            with _study_lock(root):
                raise AssertionError("second lock must not be acquired")


def test_progress_observer_does_not_change_published_study_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_matrix_design(
        config,
        subject_counts=[1],
        tile_shapes=[(3, 5)],
        repeats_per_condition=1,
        warmup_evaluations=0,
        destination=tmp_path / "design",
    )
    import diffeoforge.modern_benchmark as benchmark_module
    import diffeoforge.modern_benchmark_matrix_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    monkeypatch.setattr(
        study_module, "benchmark_modern_objective", _publish_without_computing
    )
    monkeypatch.setattr(study_module, "_timestamp", lambda: FIXED_TIME)
    unobserved = run_modern_benchmark_matrix_study(
        design, config, destination=tmp_path / "unobserved"
    )
    events = []
    observed = run_modern_benchmark_matrix_study(
        design,
        config,
        destination=tmp_path / "observed",
        progress_callback=events.append,
    )

    def tree_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    assert tree_bytes(observed) == tree_bytes(unobserved)
    assert [event.sequence for event in events] == list(range(len(events)))
    assert [event.status for event in events] == [
        "study_started",
        "condition_started",
        "condition_completed",
        "condition_started",
        "condition_completed",
        "study_completed",
    ]


def test_cli_runs_one_real_two_condition_windows_smoke_study(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_matrix_design(
        config,
        subject_counts=[1],
        tile_shapes=[(3, 5)],
        repeats_per_condition=1,
        warmup_evaluations=0,
        order_seed=11,
        destination=tmp_path / "design",
    )
    run = tmp_path / "real-study"
    code = main(
        [
            "modern-benchmark-matrix-study",
            str(design),
            str(config),
            "--output",
            str(run),
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "Matrix study progress [0/2 conditions] study_started" in captured.out
    assert "Matrix study progress [2/2 conditions] study_completed" in captured.out
    assert "completed and verified" in captured.out
    assert "Separate raw v0.4 condition reports: 2" in captured.out
    assert "No automatic comparison" in captured.out
    manifest = verify_modern_benchmark_matrix_study_run(run)
    assert {condition["tile_autograd_strategy"] for condition in manifest["conditions"]} == {
        "standard",
        "recompute",
    }

    assert main(["modern-benchmark-matrix-study-status", str(run), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "complete"
    assert status["verified_report_count"] == 2
    assert status["completion_manifest_verified"] is True

    assert main(["modern-benchmark-matrix-study-verify", str(run)]) == 0
    verified_output = capsys.readouterr().out
    assert "Completed benchmark matrix study verified" in verified_output
    assert "No automatic comparison" in verified_output

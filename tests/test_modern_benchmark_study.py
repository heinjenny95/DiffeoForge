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
from diffeoforge.modern_benchmark_design import (  # noqa: E402
    create_modern_benchmark_design,
)
from diffeoforge.modern_benchmark_study import (  # noqa: E402
    EVENTS_NAME,
    MANIFEST_NAME,
    STATE_NAME,
    ModernBenchmarkStudyError,
    _manifest_schema,
    _study_lock,
    inspect_modern_benchmark_study_run,
    run_modern_benchmark_study,
    verify_modern_benchmark_study_run,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
MESHES = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-07-16T10:00:00+00:00"


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
    destination,
):
    report = collect_modern_benchmark(
        config_path,
        subject_count=subject_count,
        repeats=repeats,
        warmup_evaluations=warmup_evaluations,
        tile_autograd_strategy=tile_autograd_strategy,
        created_at=FIXED_TIME,
    )
    return write_modern_benchmark_report(report, destination)


def test_interrupted_study_reconciles_valid_prefix_and_resumes_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_design(
        config,
        subject_counts=[1],
        repeats_per_condition=1,
        warmup_evaluations=0,
        order_seed=7,
        destination=tmp_path / "design",
    )
    import diffeoforge.modern_benchmark as benchmark_module
    import diffeoforge.modern_benchmark_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(kwargs["tile_autograd_strategy"])
        if len(calls) == 2:
            raise RuntimeError("injected interruption")
        return _publish_without_computing(*args, **kwargs)

    monkeypatch.setattr(study_module, "benchmark_modern_objective", fail_second)
    run = tmp_path / "study-run"
    with pytest.raises(ModernBenchmarkStudyError, match="injected interruption"):
        run_modern_benchmark_study(design, config, destination=run)
    state = json.loads((run / STATE_NAME).read_text(encoding="utf-8"))
    assert state["status"] == "interrupted"
    assert len(state["completed_condition_ids"]) == 1
    assert state["active_condition_id"] is None
    status = inspect_modern_benchmark_study_run(run)
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
        inspect_modern_benchmark_study_run(run)

    state["completed_condition_ids"] = []
    (run / STATE_NAME).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    status = inspect_modern_benchmark_study_run(run)
    assert status["verified_report_count"] == 1
    assert status["state_completed_condition_count"] == 0
    assert status["reconciliation_required"] is True

    resumed_calls = []

    def resume(*args, **kwargs):
        resumed_calls.append(kwargs["tile_autograd_strategy"])
        return _publish_without_computing(*args, **kwargs)

    monkeypatch.setattr(study_module, "benchmark_modern_objective", resume)
    assert run_modern_benchmark_study(design, config, destination=run) == run.resolve()
    assert len(resumed_calls) == 1
    manifest = verify_modern_benchmark_study_run(run)
    assert manifest["status"] == "complete"
    assert manifest["analysis_performed"] is False
    assert len(manifest["conditions"]) == 2
    assert _manifest_schema()["title"] == "DiffeoForge completed paired benchmark study run"
    events = [json.loads(line) for line in (run / EVENTS_NAME).read_text().splitlines()]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert any(event["event"] == "condition_failed" for event in events)
    assert events[-1]["event"] == "study_completed"

    assert run_modern_benchmark_study(design, config, destination=run) == run.resolve()


def test_config_or_raw_report_tampering_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_design(
        config,
        subject_counts=[1],
        repeats_per_condition=1,
        warmup_evaluations=0,
        destination=tmp_path / "design",
    )
    import diffeoforge.modern_benchmark as benchmark_module
    import diffeoforge.modern_benchmark_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    monkeypatch.setattr(
        study_module, "benchmark_modern_objective", _publish_without_computing
    )
    run = run_modern_benchmark_study(design, config, destination=tmp_path / "run")
    manifest = json.loads((run / MANIFEST_NAME).read_text(encoding="utf-8"))
    first_report = run / manifest["conditions"][0]["report_directory"]
    csv_path = first_report / REPORT_CSV_NAME
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("100,", "101,", 1),
        encoding="utf-8",
    )
    with pytest.raises(ModernBenchmarkStudyError, match="CSV rows differ"):
        verify_modern_benchmark_study_run(run)

    modified = yaml.safe_load(config.read_text(encoding="utf-8"))
    modified["runtime"]["threads"] += 1
    config.write_text(yaml.safe_dump(modified, sort_keys=False), encoding="utf-8")
    with pytest.raises(ModernBenchmarkStudyError, match="differs from the design"):
        run_modern_benchmark_study(design, config, destination=tmp_path / "other-run")
    assert not (tmp_path / "other-run").exists()


def test_concurrent_lock_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    with _study_lock(root):
        with pytest.raises(ModernBenchmarkStudyError, match="Another process"):
            with _study_lock(root):
                raise AssertionError("second lock must not be acquired")


def test_cli_runs_one_real_two_condition_windows_smoke_study(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = create_modern_benchmark_design(
        config,
        subject_counts=[1],
        repeats_per_condition=1,
        warmup_evaluations=0,
        order_seed=11,
        destination=tmp_path / "design",
    )
    run = tmp_path / "real-study"
    code = main(
        [
            "modern-benchmark-study",
            str(design),
            str(config),
            "--output",
            str(run),
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "completed and verified" in captured.out
    assert "Separate raw condition reports: 2" in captured.out
    assert "No automatic comparison" in captured.out
    manifest = verify_modern_benchmark_study_run(run)
    assert {condition["tile_autograd_strategy"] for condition in manifest["conditions"]} == {
        "standard",
        "recompute",
    }

    assert main(["modern-benchmark-study-status", str(run), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "complete"
    assert status["verified_report_count"] == 2
    assert status["completion_manifest_verified"] is True

    assert main(["modern-benchmark-study-verify", str(run)]) == 0
    verified_output = capsys.readouterr().out
    assert "Completed benchmark study verified" in verified_output
    assert "No automatic comparison" in verified_output

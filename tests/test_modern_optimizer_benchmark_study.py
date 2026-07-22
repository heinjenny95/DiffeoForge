from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("psutil")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.modern_optimizer_benchmark_design import (  # noqa: E402
    collect_modern_optimizer_benchmark_design,
    write_modern_optimizer_benchmark_design,
)
from diffeoforge.modern_optimizer_benchmark_study import (  # noqa: E402
    CONDITIONS_DIRECTORY_NAME,
    EVENTS_NAME,
    MANIFEST_NAME,
    MANIFEST_SIDECAR_NAME,
    STATE_NAME,
    ModernOptimizerBenchmarkStudyError,
    inspect_modern_optimizer_benchmark_study_run,
    run_modern_optimizer_benchmark_study,
    verify_modern_optimizer_benchmark_study_run,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
FIXED_TIME = "2026-07-22T14:00:00+00:00"
HASH = "a" * 64


def _sample() -> dict:
    return {
        "target_preparation_wall_time_ns": 10,
        "optimizer_wall_time_ns": 100,
        "rss_before_bytes": 1_000,
        "sampled_peak_rss_bytes": 2_000,
        "sampled_rss_delta_bytes": 1_000,
        "rss_sample_count": 3,
        "termination_reason": "max_cycles",
        "converged": False,
        "failed_block": None,
        "cycles_completed": 1,
        "accepted_decisions": 3,
        "stationary_decisions": 0,
        "failed_decisions": 0,
        "line_search_evaluations": 3,
        "objective_evaluations": 6,
        "gradient_evaluations": 6,
        "candidate_gradient_evaluations": 3,
        "line_search_candidates_without_gradient": 0,
        "final_objective": -4.5,
        "final_attachment": -4.0,
        "final_regularity": -0.5,
        "history_sha256": HASH,
        "template_sha256": HASH,
        "control_points_sha256": HASH,
        "momenta_sha256": HASH,
    }


def _design(tmp_path: Path, *, subjects: list[int]) -> Path:
    design = collect_modern_optimizer_benchmark_design(
        EXAMPLE,
        subject_counts=subjects,
        cycle_caps=[1],
        repeats_per_condition=1,
        warmup_runs=0,
        order_seed=23,
        created_at=FIXED_TIME,
    )
    return write_modern_optimizer_benchmark_design(design, tmp_path / "design")


def test_study_executes_verifies_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import diffeoforge.modern_optimizer_benchmark as benchmark_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    design = _design(tmp_path, subjects=[1])
    progress: list[dict] = []
    run = run_modern_optimizer_benchmark_study(
        design,
        EXAMPLE,
        destination=tmp_path / "run",
        progress_callback=progress.append,
    )
    manifest = verify_modern_optimizer_benchmark_study_run(run)

    assert len(manifest["conditions"]) == 1
    assert manifest["analysis_performed"] is False
    assert (run / MANIFEST_NAME).is_file()
    assert (run / MANIFEST_SIDECAR_NAME).is_file()
    assert json.loads((run / STATE_NAME).read_text(encoding="utf-8"))["status"] == "complete"
    assert [event.status for event in progress] == [
        "study_started",
        "condition_started",
        "condition_completed",
        "study_completed",
    ]

    before = {
        path.relative_to(run): path.read_bytes()
        for path in run.rglob("*")
        if path.is_file()
    }
    repeated = []
    assert (
        run_modern_optimizer_benchmark_study(
            design, EXAMPLE, destination=run, progress_callback=repeated.append
        )
        == run
    )
    assert repeated[0].status == "study_already_complete"
    assert before == {
        path.relative_to(run): path.read_bytes()
        for path in run.rglob("*")
        if path.is_file()
    }


def test_interrupted_study_resumes_from_verified_report_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import diffeoforge.modern_optimizer_benchmark as benchmark_module
    import diffeoforge.modern_optimizer_benchmark_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    design = _design(tmp_path, subjects=[1, 2])
    original = study_module.benchmark_modern_optimizer
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(study_module, "benchmark_modern_optimizer", interrupted)
    run = tmp_path / "run"
    with pytest.raises(ModernOptimizerBenchmarkStudyError, match="synthetic interruption"):
        run_modern_optimizer_benchmark_study(design, EXAMPLE, destination=run)
    state = json.loads((run / STATE_NAME).read_text(encoding="utf-8"))
    assert state["status"] == "interrupted"
    assert len(list((run / CONDITIONS_DIRECTORY_NAME).iterdir())) == 1
    status = inspect_modern_optimizer_benchmark_study_run(run)
    assert status["status"] == "interrupted"
    assert status["verified_report_count"] == 1
    assert status["state_completed_condition_count"] == 1
    assert status["next_condition"] is not None

    monkeypatch.setattr(study_module, "benchmark_modern_optimizer", original)
    assert run_modern_optimizer_benchmark_study(design, EXAMPLE, destination=run) == run
    manifest = verify_modern_optimizer_benchmark_study_run(run)
    assert len(manifest["conditions"]) == 2
    events = [json.loads(line) for line in (run / EVENTS_NAME).read_text().splitlines()]
    assert any(event["event"] == "condition_failed" for event in events)
    assert events[-1]["event"] == "study_completed"


def test_published_report_ahead_of_state_is_reported_and_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import diffeoforge.modern_optimizer_benchmark as benchmark_module
    import diffeoforge.modern_optimizer_benchmark_study as study_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    design = _design(tmp_path, subjects=[1])
    original = study_module.benchmark_modern_optimizer

    def publish_then_interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic post-publication interruption")

    monkeypatch.setattr(
        study_module, "benchmark_modern_optimizer", publish_then_interrupt
    )
    run = tmp_path / "run"
    with pytest.raises(ModernOptimizerBenchmarkStudyError, match="post-publication"):
        run_modern_optimizer_benchmark_study(design, EXAMPLE, destination=run)

    status = inspect_modern_optimizer_benchmark_study_run(run)
    assert status["verified_report_count"] == 1
    assert status["state_completed_condition_count"] == 0
    assert status["reconciliation_required"] is True
    assert status["next_condition"] is None

    monkeypatch.setattr(study_module, "benchmark_modern_optimizer", original)
    progress = []
    assert (
        run_modern_optimizer_benchmark_study(
            design, EXAMPLE, destination=run, progress_callback=progress.append
        )
        == run.resolve()
    )
    assert [event.status for event in progress] == [
        "condition_reconciled",
        "study_resumed",
        "study_completed",
    ]
    assert verify_modern_optimizer_benchmark_study_run(run)["status"] == "complete"


def test_verifier_rejects_changed_raw_report_and_cli_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import diffeoforge.modern_optimizer_benchmark as benchmark_module

    monkeypatch.setattr(benchmark_module, "_run_fresh_sample", lambda *_args: _sample())
    design = _design(tmp_path, subjects=[1])
    run = tmp_path / "run"
    assert (
        main(
            [
                "modern-optimizer-benchmark-study",
                str(design),
                str(EXAMPLE),
                "--output",
                str(run),
            ]
        )
        == 0
    )
    assert "No automatic comparison" in capsys.readouterr().out
    assert main(["modern-optimizer-benchmark-study-verify", str(run)]) == 0
    assert "No automatic comparison" in capsys.readouterr().out
    assert (
        main(["modern-optimizer-benchmark-study-status", str(run), "--json"])
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "complete"
    assert status["verified_report_count"] == 1
    assert status["completion_manifest_verified"] is True

    condition = next((run / CONDITIONS_DIRECTORY_NAME).iterdir())
    report_html = condition / "optimizer-benchmark.html"
    report_html.write_text("tampered", encoding="utf-8")
    with pytest.raises(ModernOptimizerBenchmarkStudyError, match="condition"):
        verify_modern_optimizer_benchmark_study_run(run)

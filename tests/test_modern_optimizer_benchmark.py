from __future__ import annotations

import csv
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("psutil")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.modern_optimizer_benchmark import (  # noqa: E402
    REPORT_COLUMNS,
    REPORT_CSV_NAME,
    REPORT_HTML_NAME,
    REPORT_JSON_NAME,
    ModernOptimizerBenchmarkError,
    _schema,
    collect_modern_optimizer_benchmark,
    render_modern_optimizer_benchmark_html,
    verify_modern_optimizer_benchmark_report,
    write_modern_optimizer_benchmark_report,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
FIXED_TIME = "2026-07-22T08:00:00+00:00"
HASH = "a" * 64


def _sample(number: int = 1) -> dict:
    return {
        "target_preparation_wall_time_ns": number * 10,
        "optimizer_wall_time_ns": number * 100,
        "rss_before_bytes": 1_000 + number,
        "sampled_peak_rss_bytes": 2_000 + number,
        "sampled_rss_delta_bytes": 1_000,
        "rss_sample_count": 3,
        "termination_reason": "max_cycles",
        "converged": False,
        "failed_block": None,
        "cycles_completed": 2,
        "accepted_decisions": 6,
        "stationary_decisions": 0,
        "failed_decisions": 0,
        "line_search_evaluations": 9,
        "objective_evaluations": 15,
        "gradient_evaluations": 12,
        "candidate_gradient_evaluations": 6,
        "line_search_candidates_without_gradient": 3,
        "final_objective": -4.5,
        "final_attachment": -4.0,
        "final_regularity": -0.5,
        "history_sha256": HASH,
        "template_sha256": HASH,
        "control_points_sha256": HASH,
        "momenta_sha256": HASH,
    }


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        self.tags.append(tag)


def test_collection_binds_declared_optimizer_scope_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import diffeoforge.modern_optimizer_benchmark as module

    calls = []

    def fixed_worker(*args):
        calls.append(args)
        return _sample(len(calls))

    monkeypatch.setattr(module, "_run_fresh_sample", fixed_worker)
    report = collect_modern_optimizer_benchmark(
        EXAMPLE,
        subject_count=2,
        max_cycles=2,
        repeats=3,
        warmup_runs=1,
        created_at=FIXED_TIME,
    )

    assert report["benchmark_version"] == "0.1"
    assert report["benchmark_id"] == "production_multi_cycle_optimizer"
    assert report["created_at"] == FIXED_TIME
    assert [subject["label"] for subject in report["input"]["subjects"]] == [
        "subject-01.vtk",
        "subject-02.vtk",
    ]
    assert report["configuration"]["source_max_cycles"] == 3
    assert report["configuration"]["measured_max_cycles"] == 2
    assert report["configuration"]["warmup_runs_per_repeat"] == 1
    assert report["configuration"]["pairwise_evaluation"]["mode"] == "dense"
    assert report["summary"]["optimizer_wall_time_ns"] == {
        "minimum": 100,
        "median": 200,
        "maximum": 300,
    }
    assert report["repeat_consistency"]["consistent"] is True
    assert calls == [(EXAMPLE.resolve(), 2, 2, 1)] * 3
    assert "not a convergence result" in report["scientific_boundary"]
    assert _schema()["title"].endswith("optimizer benchmark")


def test_report_is_atomic_escaped_and_strictly_verifiable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import diffeoforge.modern_optimizer_benchmark as module

    monkeypatch.setattr(module, "_run_fresh_sample", lambda *_args: _sample())
    report = collect_modern_optimizer_benchmark(
        EXAMPLE,
        subject_count=1,
        max_cycles=2,
        repeats=1,
        created_at=FIXED_TIME,
    )
    report["source_config"]["project"] = "<script>alert(1)</script>"
    rendered = render_modern_optimizer_benchmark_html(report)
    parser = _StructureParser()
    parser.feed(rendered)
    parser.close()

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert parser.tags.count("table") == 1
    output = write_modern_optimizer_benchmark_report(report, tmp_path / "report")
    assert verify_modern_optimizer_benchmark_report(output) == report
    with (output / REPORT_CSV_NAME).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == REPORT_COLUMNS
    assert rows[0]["line_search_candidates_without_gradient"] == "3"
    with pytest.raises(FileExistsError):
        write_modern_optimizer_benchmark_report(report, output)
    write_modern_optimizer_benchmark_report(report, output, overwrite=True)

    csv_path = output / REPORT_CSV_NAME
    original = csv_path.read_text(encoding="utf-8")
    csv_path.write_text(original.replace(",3,-4.5", ",2,-4.5", 1), encoding="utf-8")
    with pytest.raises(ModernOptimizerBenchmarkError, match="CSV rows differ"):
        verify_modern_optimizer_benchmark_report(output)
    csv_path.write_text(original, encoding="utf-8")

    invalid = json.loads(json.dumps(report))
    invalid["samples"][0]["candidate_gradient_evaluations"] = 7
    with pytest.raises(ModernOptimizerBenchmarkError, match="Deferred-gradient count"):
        write_modern_optimizer_benchmark_report(invalid, tmp_path / "invalid")

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "keep.txt").write_text("user", encoding="utf-8")
    with pytest.raises(ModernOptimizerBenchmarkError, match="Refusing"):
        write_modern_optimizer_benchmark_report(report, unsafe, overwrite=True)
    assert (unsafe / "keep.txt").read_text(encoding="utf-8") == "user"


def test_collection_rejects_invalid_scope_before_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import diffeoforge.modern_optimizer_benchmark as module

    monkeypatch.setattr(
        module,
        "_run_fresh_sample",
        lambda *_args: (_ for _ in ()).throw(AssertionError("worker must not start")),
    )
    with pytest.raises(ValueError, match="between 1 and 100"):
        collect_modern_optimizer_benchmark(EXAMPLE, subject_count=1, max_cycles=0)
    with pytest.raises(ValueError, match="between 1 and 50"):
        collect_modern_optimizer_benchmark(
            EXAMPLE,
            subject_count=1,
            max_cycles=1,
            repeats=0,
        )
    with pytest.raises(ValueError, match="between 0 and 10"):
        collect_modern_optimizer_benchmark(
            EXAMPLE,
            subject_count=1,
            max_cycles=1,
            warmup_runs=11,
        )


def test_cli_runs_one_real_fresh_process_optimizer_measurement(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "optimizer-benchmark"
    code = main(
        [
            "modern-optimizer-benchmark",
            str(EXAMPLE),
            "--subjects",
            "1",
            "--cycles",
            "1",
            "--repeats",
            "1",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "Selected subjects: 1" in captured.out
    assert "Measured cycle cap: 1" in captured.out
    assert "not a convergence or ETA result" in captured.out
    report = verify_modern_optimizer_benchmark_report(output)
    sample = report["samples"][0]
    assert sample["optimizer_wall_time_ns"] > 0
    assert sample["target_preparation_wall_time_ns"] > 0
    assert sample["rss_sample_count"] >= 2
    assert sample["objective_evaluations"] >= sample["gradient_evaluations"]
    assert sample["line_search_candidates_without_gradient"] >= 0
    assert report["repeat_consistency"]["consistent"] is True
    assert (output / REPORT_JSON_NAME).is_file()
    assert (output / REPORT_HTML_NAME).is_file()
    assert main(["modern-optimizer-benchmark-verify", str(output)]) == 0

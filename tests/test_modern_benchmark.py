from __future__ import annotations

import csv
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("psutil")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.config import ConfigurationError  # noqa: E402
from diffeoforge.modern_benchmark import (  # noqa: E402
    REPORT_CSV_NAME,
    REPORT_HTML_NAME,
    REPORT_JSON_NAME,
    ModernBenchmarkError,
    _schema,
    collect_modern_benchmark,
    render_modern_benchmark_html,
    write_modern_benchmark_report,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
FIXED_TIME = "2026-07-16T12:00:00+00:00"


def _sample(number: int) -> dict:
    return {
        "wall_time_ns": number * 100,
        "rss_before_bytes": 1_000 + number,
        "sampled_peak_rss_bytes": 2_000 + number,
        "sampled_rss_delta_bytes": 1_000,
        "rss_sample_count": 3,
        "objective": -4.5,
        "gradient_norm": 7.25,
    }


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        self.tags.append(tag)


def test_dense_v01_benchmark_refuses_blockwise_config_before_spawning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    config["runtime"]["pairwise_evaluation"] = {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }
    path = tmp_path / "blockwise.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    import diffeoforge.modern_benchmark as module

    def fail(*_args, **_kwargs):
        raise AssertionError("fresh benchmark process must not spawn")

    monkeypatch.setattr(module, "_run_fresh_sample", fail)
    with pytest.raises(ModernBenchmarkError, match="will not be silently reported as dense"):
        collect_modern_benchmark(path, subject_count=1, repeats=1)


def test_collection_binds_selection_operations_and_descriptive_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fixed_worker(config_path, subject_count, warmups):
        calls.append((config_path, subject_count, warmups))
        return _sample(len(calls))

    import diffeoforge.modern_benchmark as module

    monkeypatch.setattr(module, "_run_fresh_sample", fixed_worker)
    report = collect_modern_benchmark(
        EXAMPLE,
        subject_count=2,
        repeats=3,
        warmup_evaluations=1,
        created_at=FIXED_TIME,
    )

    assert [subject["label"] for subject in report["input"]["subjects"]] == [
        "subject-01.vtk",
        "subject-02.vtk",
    ]
    assert report["input"]["available_subject_count"] == 5
    assert report["operation_model"]["dense_gaussian_calls_per_evaluation"] == 80
    assert report["operation_model"]["dense_gaussian_pair_elements_per_evaluation"] == 642_426
    assert report["summary"]["wall_time_ns"] == {
        "minimum": 100,
        "median": 200,
        "maximum": 300,
    }
    assert report["numerical_consistency"]["consistent"] is True
    assert report["created_at"] == FIXED_TIME
    assert len(calls) == 3
    assert all(subject_count == 2 and warmups == 1 for _, subject_count, warmups in calls)
    assert "hardware pass/fail verdict" in report["scientific_boundary"]
    assert _schema()["title"] == "DiffeoForge modern objective benchmark"


def test_reports_are_escaped_atomic_and_refuse_unrelated_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import diffeoforge.modern_benchmark as module

    monkeypatch.setattr(module, "_run_fresh_sample", lambda *_args: _sample(1))
    report = collect_modern_benchmark(
        EXAMPLE,
        subject_count=1,
        repeats=1,
        warmup_evaluations=0,
        created_at=FIXED_TIME,
    )
    report["source_config"]["project"] = "<script>alert(1)</script>"
    rendered = render_modern_benchmark_html(report)
    parser = _StructureParser()
    parser.feed(rendered)
    parser.close()

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert parser.tags.count("h1") == 1
    assert parser.tags.count("table") == 1
    output = write_modern_benchmark_report(report, tmp_path / "report")
    assert json.loads((output / REPORT_JSON_NAME).read_text(encoding="utf-8")) == report
    with (output / REPORT_CSV_NAME).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["wall_time_ns"] == "100"
    assert (output / REPORT_HTML_NAME).read_text(encoding="utf-8") == rendered
    with pytest.raises(FileExistsError):
        write_modern_benchmark_report(report, output)
    write_modern_benchmark_report(report, output, overwrite=True)

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "user.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ModernBenchmarkError, match="Refusing"):
        write_modern_benchmark_report(report, unsafe, overwrite=True)
    assert (unsafe / "user.txt").read_text(encoding="utf-8") == "keep"

    invalid = json.loads(json.dumps(report))
    invalid["unexpected"] = True
    with pytest.raises(ModernBenchmarkError, match="schema validation"):
        write_modern_benchmark_report(invalid, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()

    inconsistent = json.loads(json.dumps(report))
    inconsistent["samples"][0]["sampled_rss_delta_bytes"] = 999
    inconsistent["summary"]["sampled_rss_delta_bytes"] = {
        "minimum": 999,
        "median": 999,
        "maximum": 999,
    }
    with pytest.raises(ModernBenchmarkError, match="RSS delta"):
        write_modern_benchmark_report(inconsistent, tmp_path / "inconsistent")

    def fail_render(_report):
        raise RuntimeError("injected rendering failure")

    monkeypatch.setattr(module, "render_modern_benchmark_html", fail_render)
    failed = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="injected"):
        write_modern_benchmark_report(report, failed)
    assert not failed.exists()
    assert not tuple(tmp_path.glob(".failed.tmp-*"))


def test_subject_selection_and_procrustes_scope_fail_before_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import diffeoforge.modern_benchmark as module

    def fail(*_args):
        raise AssertionError("worker must not start")

    monkeypatch.setattr(module, "_run_fresh_sample", fail)
    with pytest.raises(ConfigurationError, match="only 5 are available"):
        collect_modern_benchmark(EXAMPLE, subject_count=6, repeats=1)

    config = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    config["input"]["directory"] = str(ROOT / "examples" / "synthetic" / "meshes")
    config["input"]["template"] = str(
        ROOT / "examples" / "synthetic" / "meshes" / "template.vtk"
    )
    config["preprocessing"]["procrustes"]["enabled"] = True
    config["preprocessing"]["procrustes"]["landmarks_file"] = "not-read.csv"
    path = tmp_path / "procrustes.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="requires.*false"):
        collect_modern_benchmark(path, subject_count=1, repeats=1)


def test_cli_runs_one_real_fresh_process_measurement(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "benchmark"
    code = main(
        [
            "modern-benchmark",
            str(EXAMPLE),
            "--subjects",
            "1",
            "--repeats",
            "2",
            "--warmups",
            "0",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "Selected subjects: 1" in captured.out
    assert "Do not extrapolate" in captured.out
    report = json.loads((output / REPORT_JSON_NAME).read_text(encoding="utf-8"))
    assert len(report["samples"]) == 2
    assert all(sample["wall_time_ns"] > 0 for sample in report["samples"])
    assert all(sample["sampled_peak_rss_bytes"] > 0 for sample in report["samples"])
    assert all(sample["rss_sample_count"] >= 2 for sample in report["samples"])
    assert report["numerical_consistency"]["consistent"] is True
    assert report["numerical_consistency"]["objective_span"] <= 1e-12
    assert report["numerical_consistency"]["gradient_norm_span"] <= 1e-12

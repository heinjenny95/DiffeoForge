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
    verify_modern_benchmark_report,
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


def _write_portable_config(path: Path, *, mode: str = "dense") -> Path:
    config = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    mesh_directory = ROOT / "examples" / "synthetic" / "meshes"
    config["input"]["directory"] = str(mesh_directory)
    config["input"]["template"] = str(mesh_directory / "template.vtk")
    config["output"]["directory"] = str(path.parent / "future-run")
    if mode == "blockwise":
        config["runtime"]["pairwise_evaluation"] = {
            "mode": "blockwise",
            "query_tile_size": 64,
            "source_tile_size": 64,
        }
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_blockwise_collection_binds_configured_plan_to_worker_and_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_portable_config(tmp_path / "blockwise.yaml", mode="blockwise")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))

    import diffeoforge.modern_benchmark as module

    calls = []

    def fixed_worker(*args):
        calls.append(args)
        return _sample(1)

    monkeypatch.setattr(module, "_run_fresh_sample", fixed_worker)
    report = collect_modern_benchmark(
        path,
        subject_count=1,
        repeats=1,
        tile_autograd_strategy="recompute",
    )

    assert len(calls) == 1
    assert (
        report["configuration"]["pairwise_evaluation"] == config["runtime"]["pairwise_evaluation"]
    )
    assert calls[0][-3:] == ("recompute", None, None)
    assert report["configuration"]["tile_autograd_strategy"] == "recompute"
    assert report["operation_model"]["largest_execution_tile"]["tile_rows"] == 64
    assert report["operation_model"]["largest_execution_tile"]["tile_columns"] == 64


def test_rectangular_tile_override_binds_worker_operation_model_and_v04_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_portable_config(tmp_path / "blockwise.yaml", mode="blockwise")
    calls = []

    import diffeoforge.modern_benchmark as module

    def fixed_worker(*args):
        calls.append(args)
        return _sample(1)

    monkeypatch.setattr(module, "_run_fresh_sample", fixed_worker)
    report = collect_modern_benchmark(
        path,
        subject_count=1,
        repeats=1,
        tile_autograd_strategy="recompute",
        query_tile_size=3,
        source_tile_size=5,
        created_at=FIXED_TIME,
    )

    assert report["benchmark_version"] == "0.4"
    assert report["configuration"]["source_pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }
    assert report["configuration"]["effective_pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 3,
        "source_tile_size": 5,
    }
    assert "pairwise_evaluation" not in report["configuration"]
    assert calls[0][-3:] == ("recompute", 3, 5)
    assert report["operation_model"]["largest_execution_tile"]["tile_rows"] == 3
    assert report["operation_model"]["largest_execution_tile"]["tile_columns"] == 5
    assert _schema("0.4")["title"].endswith("effective tile override")
    rendered = render_modern_benchmark_html(report)
    assert "Source-declared pairwise execution: blockwise (64 × 64)" in rendered
    assert "Effective benchmark-only pairwise execution: blockwise (3 × 5)" in rendered
    output = write_modern_benchmark_report(report, tmp_path / "v04-report")
    assert verify_modern_benchmark_report(output) == report


def test_collection_binds_selection_operations_and_descriptive_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fixed_worker(
        config_path,
        subject_count,
        warmups,
        autograd_strategy,
        query_tile_size,
        source_tile_size,
    ):
        calls.append(
            (
                config_path,
                subject_count,
                warmups,
                autograd_strategy,
                query_tile_size,
                source_tile_size,
            )
        )
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
    assert report["operation_model"]["gaussian_calls_per_evaluation"] == 80
    assert report["operation_model"]["gaussian_pair_elements_per_evaluation"] == 642_426
    assert report["summary"]["wall_time_ns"] == {
        "minimum": 100,
        "median": 200,
        "maximum": 300,
    }
    assert report["numerical_consistency"]["consistent"] is True
    assert report["created_at"] == FIXED_TIME
    assert report["benchmark_version"] == "0.3"
    assert "source_pairwise_evaluation" not in report["configuration"]
    assert "effective_pairwise_evaluation" not in report["configuration"]
    assert report["configuration"]["tile_autograd_strategy"] == "standard"
    assert len(calls) == 3
    assert all(
        subject_count == 2
        and warmups == 1
        and strategy == "standard"
        and query_tile_size is None
        and source_tile_size is None
        for (
            _,
            subject_count,
            warmups,
            strategy,
            query_tile_size,
            source_tile_size,
        ) in calls
    )
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
    assert "Tile autograd strategy: standard" in rendered
    assert parser.tags.count("h1") == 1
    assert parser.tags.count("table") == 1
    output = write_modern_benchmark_report(report, tmp_path / "report")
    assert json.loads((output / REPORT_JSON_NAME).read_text(encoding="utf-8")) == report
    with (output / REPORT_CSV_NAME).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["wall_time_ns"] == "100"
    assert (output / REPORT_HTML_NAME).read_text(encoding="utf-8") == rendered
    assert verify_modern_benchmark_report(output) == report
    with pytest.raises(FileExistsError):
        write_modern_benchmark_report(report, output)
    write_modern_benchmark_report(report, output, overwrite=True)

    csv_path = output / REPORT_CSV_NAME
    original_csv = csv_path.read_text(encoding="utf-8")
    csv_path.write_text(original_csv.replace("100,", "101,", 1), encoding="utf-8")
    with pytest.raises(ModernBenchmarkError, match="CSV rows differ"):
        verify_modern_benchmark_report(output)
    csv_path.write_text(original_csv, encoding="utf-8")

    html_path = output / REPORT_HTML_NAME
    original_html = html_path.read_text(encoding="utf-8")
    html_path.write_text(original_html + "changed", encoding="utf-8")
    with pytest.raises(ModernBenchmarkError, match="HTML differs"):
        verify_modern_benchmark_report(output)
    html_path.write_text(original_html, encoding="utf-8")

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

    inconsistent_tile = json.loads(json.dumps(report))
    inconsistent_tile["operation_model"]["largest_execution_tile"]["float64_matrix_bytes"] += 8
    with pytest.raises(ModernBenchmarkError, match="execution-tile payload"):
        write_modern_benchmark_report(inconsistent_tile, tmp_path / "inconsistent-tile")

    inconsistent_operation = json.loads(json.dumps(report))
    inconsistent_operation["operation_model"]["gaussian_calls_per_evaluation"] += 1
    with pytest.raises(ModernBenchmarkError, match="inventory and configuration"):
        write_modern_benchmark_report(inconsistent_operation, tmp_path / "inconsistent-operation")

    inconsistent_strategy = json.loads(json.dumps(report))
    inconsistent_strategy["configuration"]["tile_autograd_strategy"] = "recompute"
    with pytest.raises(ModernBenchmarkError, match="Dense benchmark execution"):
        write_modern_benchmark_report(inconsistent_strategy, tmp_path / "inconsistent-strategy")

    unsupported = json.loads(json.dumps(report))
    unsupported["benchmark_version"] = "0.5"
    with pytest.raises(ModernBenchmarkError, match="Unsupported modern benchmark version"):
        write_modern_benchmark_report(unsupported, tmp_path / "unsupported-version")

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
    config["input"]["template"] = str(ROOT / "examples" / "synthetic" / "meshes" / "template.vtk")
    config["preprocessing"]["procrustes"]["enabled"] = True
    config["preprocessing"]["procrustes"]["landmarks_file"] = "not-read.csv"
    path = tmp_path / "procrustes.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="requires.*false"):
        collect_modern_benchmark(path, subject_count=1, repeats=1)

    with pytest.raises(ConfigurationError, match="requires configured blockwise"):
        collect_modern_benchmark(
            EXAMPLE,
            subject_count=1,
            repeats=1,
            tile_autograd_strategy="recompute",
        )

    blockwise = _write_portable_config(tmp_path / "blockwise.yaml", mode="blockwise")
    with pytest.raises(ValueError, match="must be supplied together"):
        collect_modern_benchmark(
            blockwise,
            subject_count=1,
            repeats=1,
            query_tile_size=3,
        )
    with pytest.raises(ValueError, match="must be at least 1"):
        collect_modern_benchmark(
            blockwise,
            subject_count=1,
            repeats=1,
            query_tile_size=0,
            source_tile_size=5,
        )
    with pytest.raises(TypeError, match="must be an integer"):
        collect_modern_benchmark(
            blockwise,
            subject_count=1,
            repeats=1,
            query_tile_size=True,
            source_tile_size=5,
        )
    with pytest.raises(ConfigurationError, match="tile-size overrides require configured"):
        collect_modern_benchmark(
            EXAMPLE,
            subject_count=1,
            repeats=1,
            query_tile_size=3,
            source_tile_size=5,
        )


def test_cli_rejects_partial_tile_override_before_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_portable_config(tmp_path / "blockwise.yaml", mode="blockwise")
    output = tmp_path / "partial"
    code = main(
        [
            "modern-benchmark",
            str(config),
            "--subjects",
            "1",
            "--query-tile-size",
            "3",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "must be supplied together" in captured.err
    assert not output.exists()


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
    assert report["configuration"]["tile_autograd_strategy"] == "standard"
    assert report["numerical_consistency"]["objective_span"] <= 1e-12
    assert report["numerical_consistency"]["gradient_norm_span"] <= 1e-12


@pytest.mark.parametrize("autograd_strategy", ["standard", "recompute"])
def test_cli_runs_one_real_fresh_blockwise_process_measurement(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    autograd_strategy: str,
) -> None:
    config = _write_portable_config(tmp_path / "blockwise.yaml", mode="blockwise")
    output = tmp_path / f"blockwise-{autograd_strategy}-benchmark"
    code = main(
        [
            "modern-benchmark",
            str(config),
            "--subjects",
            "1",
            "--repeats",
            "1",
            "--warmups",
            "0",
            "--tile-autograd-strategy",
            autograd_strategy,
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "Pairwise execution: blockwise" in captured.out
    assert f"Tile autograd strategy: {autograd_strategy}" in captured.out
    report = json.loads((output / REPORT_JSON_NAME).read_text(encoding="utf-8"))
    assert report["configuration"]["pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }
    assert report["configuration"]["tile_autograd_strategy"] == autograd_strategy
    assert report["operation_model"]["largest_execution_tile"]["tile_rows"] == 64
    assert report["operation_model"]["largest_execution_tile"]["tile_columns"] == 64
    assert report["samples"][0]["wall_time_ns"] > 0
    assert report["samples"][0]["sampled_peak_rss_bytes"] > 0
    assert report["samples"][0]["rss_sample_count"] >= 2
    assert report["numerical_consistency"]["consistent"] is True


@pytest.mark.parametrize("autograd_strategy", ["standard", "recompute"])
def test_cli_runs_rectangular_override_in_one_real_fresh_process(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    autograd_strategy: str,
) -> None:
    config = _write_portable_config(tmp_path / "blockwise.yaml", mode="blockwise")
    output = tmp_path / f"rectangular-{autograd_strategy}"
    code = main(
        [
            "modern-benchmark",
            str(config),
            "--subjects",
            "1",
            "--repeats",
            "1",
            "--warmups",
            "0",
            "--tile-autograd-strategy",
            autograd_strategy,
            "--query-tile-size",
            "3",
            "--source-tile-size",
            "5",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "Source-declared tile rows: 64 x 64" in captured.out
    assert "Effective benchmark-only tile rows: 3 x 5" in captured.out
    report = verify_modern_benchmark_report(output)
    assert report["benchmark_version"] == "0.4"
    assert report["configuration"]["effective_pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 3,
        "source_tile_size": 5,
    }
    assert report["configuration"]["tile_autograd_strategy"] == autograd_strategy
    assert report["samples"][0]["wall_time_ns"] > 0

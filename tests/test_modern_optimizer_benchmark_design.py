from __future__ import annotations

import copy
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("psutil")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.config import ConfigurationError  # noqa: E402
from diffeoforge.modern_optimizer_benchmark_design import (  # noqa: E402
    DESIGN_HTML_NAME,
    DESIGN_JSON_NAME,
    DESIGN_SIDECAR_NAME,
    ModernOptimizerBenchmarkDesignError,
    _schema,
    _validate_design,
    collect_modern_optimizer_benchmark_design,
    render_modern_optimizer_benchmark_design_html,
    verify_modern_optimizer_benchmark_design,
    write_modern_optimizer_benchmark_design,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
FIXED_TIME = "2026-07-22T12:00:00+00:00"


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        self.tags.append(tag)


def test_design_freezes_full_factorial_schedule_without_results() -> None:
    first = collect_modern_optimizer_benchmark_design(
        EXAMPLE,
        subject_counts=[1, 3],
        cycle_caps=[1, 2],
        repeats_per_condition=4,
        warmup_runs=1,
        order_seed=17,
        created_at=FIXED_TIME,
    )
    second = collect_modern_optimizer_benchmark_design(
        EXAMPLE,
        subject_counts=[1, 3],
        cycle_caps=[1, 2],
        repeats_per_condition=4,
        warmup_runs=1,
        order_seed=17,
        created_at=FIXED_TIME,
    )

    assert first == second
    assert first["optimizer_design_version"] == "0.1"
    assert first["software"]["optimizer_benchmark_version"] == "0.1"
    assert first["protocol"]["condition_count"] == 4
    assert first["configuration"]["pairwise_evaluation"]["mode"] == "dense"
    assert len(first["input"]["subjects"]) == 5
    assert {
        (condition["subject_count"], condition["cycle_cap"])
        for condition in first["conditions"]
    } == {(1, 1), (1, 2), (3, 1), (3, 2)}
    for sequence, condition in enumerate(first["conditions"], start=1):
        assert condition["sequence"] == sequence
        argv = condition["argv"]
        assert argv[:3] == [
            "diffeoforge",
            "modern-optimizer-benchmark",
            "<verified-source-config>",
        ]
        assert argv[argv.index("--subjects") + 1] == str(condition["subject_count"])
        assert argv[argv.index("--cycles") + 1] == str(condition["cycle_cap"])
        assert argv[-1] == condition["output_directory"]
    assert "results" not in first
    assert _schema()["title"] == "DiffeoForge prospective optimizer scaling design"


def test_invalid_factors_and_semantic_schedule_mutation_fail() -> None:
    with pytest.raises(ValueError, match="subject_counts.*non-empty"):
        collect_modern_optimizer_benchmark_design(
            EXAMPLE, subject_counts=[], cycle_caps=[1]
        )
    with pytest.raises(ValueError, match="subject_counts.*duplicates"):
        collect_modern_optimizer_benchmark_design(
            EXAMPLE, subject_counts=[1, 1], cycle_caps=[1]
        )
    with pytest.raises(ValueError, match="cycle_caps.*duplicates"):
        collect_modern_optimizer_benchmark_design(
            EXAMPLE, subject_counts=[1], cycle_caps=[2, 2]
        )
    with pytest.raises(ConfigurationError, match="only 5 are available"):
        collect_modern_optimizer_benchmark_design(
            EXAMPLE, subject_counts=[6], cycle_caps=[1]
        )
    with pytest.raises(ValueError, match="cycle_cap"):
        collect_modern_optimizer_benchmark_design(
            EXAMPLE, subject_counts=[1], cycle_caps=[101]
        )

    design = collect_modern_optimizer_benchmark_design(
        EXAMPLE,
        subject_counts=[1, 3],
        cycle_caps=[1, 2],
        created_at=FIXED_TIME,
    )
    reordered = copy.deepcopy(design)
    reordered["conditions"].reverse()
    with pytest.raises(ModernOptimizerBenchmarkDesignError, match="deterministic"):
        _validate_design(reordered)
    inconsistent = copy.deepcopy(design)
    inconsistent["protocol"]["condition_count"] += 1
    with pytest.raises(ModernOptimizerBenchmarkDesignError, match="condition count"):
        _validate_design(inconsistent)


def test_publication_is_atomic_escaped_immutable_and_strict(tmp_path: Path) -> None:
    design = collect_modern_optimizer_benchmark_design(
        EXAMPLE,
        subject_counts=[1, 3],
        cycle_caps=[1, 2],
        created_at=FIXED_TIME,
    )
    design["source_config"]["project"] = "<script>alert(1)</script>"
    rendered = render_modern_optimizer_benchmark_design_html(design)
    parser = _StructureParser()
    parser.feed(rendered)

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert parser.tags.count("table") == 1
    output = write_modern_optimizer_benchmark_design(design, tmp_path / "design")
    assert {path.name for path in output.iterdir()} == {
        DESIGN_JSON_NAME,
        DESIGN_SIDECAR_NAME,
        DESIGN_HTML_NAME,
    }
    assert verify_modern_optimizer_benchmark_design(output) == design
    with pytest.raises(FileExistsError):
        write_modern_optimizer_benchmark_design(design, output)

    (output / DESIGN_HTML_NAME).write_text("tampered", encoding="utf-8")
    with pytest.raises(ModernOptimizerBenchmarkDesignError, match="HTML differs"):
        verify_modern_optimizer_benchmark_design(output)
    (output / DESIGN_HTML_NAME).write_text(rendered, encoding="utf-8", newline="\n")
    payload = json.loads((output / DESIGN_JSON_NAME).read_text(encoding="utf-8"))
    payload["conditions"].reverse()
    (output / DESIGN_JSON_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(ModernOptimizerBenchmarkDesignError, match="sidecar"):
        verify_modern_optimizer_benchmark_design(output)


def test_cli_creates_and_read_only_verifies_design(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "optimizer-study"
    assert (
        main(
            [
                "modern-optimizer-benchmark-design",
                str(EXAMPLE),
                "--subjects",
                "1",
                "3",
                "--cycles",
                "1",
                "2",
                "--repeats",
                "2",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    created = capsys.readouterr()
    assert "No optimizer has been run" in created.out
    assert "4/1000" in created.out
    before = {
        path.name: path.read_bytes()
        for path in output.iterdir()
    }
    assert main(["modern-optimizer-benchmark-design-verify", str(output)]) == 0
    verified = capsys.readouterr()
    assert "No optimizer result" in verified.out
    assert before == {path.name: path.read_bytes() for path in output.iterdir()}

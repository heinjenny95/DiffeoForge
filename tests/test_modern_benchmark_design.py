from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("psutil")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.config import ConfigurationError  # noqa: E402
from diffeoforge.mesh import sha256_file  # noqa: E402
from diffeoforge.modern_benchmark_design import (  # noqa: E402
    DESIGN_HTML_NAME,
    DESIGN_JSON_NAME,
    DESIGN_SIDECAR_NAME,
    ModernBenchmarkDesignError,
    _schema,
    collect_modern_benchmark_design,
    render_modern_benchmark_design_html,
    verify_modern_benchmark_design,
    write_modern_benchmark_design,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
BLOCKWISE_EXAMPLE = ROOT / "examples" / "minimal-modern-atlas-blockwise.yaml"
MESHES = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-07-16T10:00:00+00:00"


def test_committed_blockwise_example_supports_prospective_design() -> None:
    design = collect_modern_benchmark_design(
        BLOCKWISE_EXAMPLE,
        subject_counts=[1, 3, 5],
        repeats_per_condition=1,
        warmup_evaluations=0,
        order_seed=20260722,
        created_at=FIXED_TIME,
    )

    assert design["configuration"]["pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }
    assert len(design["conditions"]) == 6


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        self.tags.append(tag)


def _write_config(
    path: Path, *, mode: str = "blockwise", procrustes: bool = False
) -> Path:
    config = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    config["input"]["directory"] = str(MESHES)
    config["input"]["template"] = str(MESHES / "template.vtk")
    config["output"]["directory"] = str(path.parent / "future-run")
    if mode == "blockwise":
        config["runtime"]["pairwise_evaluation"] = {
            "mode": "blockwise",
            "query_tile_size": 64,
            "source_tile_size": 32,
        }
    if procrustes:
        config["preprocessing"]["procrustes"]["enabled"] = True
        config["preprocessing"]["procrustes"]["landmarks_file"] = "not-read.csv"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_collection_freezes_inventory_pairing_and_exact_deterministic_argv(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    first = collect_modern_benchmark_design(
        config,
        subject_counts=[1, 3, 5],
        repeats_per_condition=7,
        warmup_evaluations=2,
        order_seed=42,
        created_at=FIXED_TIME,
    )
    second = collect_modern_benchmark_design(
        config,
        subject_counts=[1, 3, 5],
        repeats_per_condition=7,
        warmup_evaluations=2,
        order_seed=42,
        created_at="later",
    )

    assert first["design_version"] == "0.1"
    assert first["software"]["benchmark_version"] == "0.3"
    assert first["created_at"] == FIXED_TIME
    assert first["input"]["available_subject_count"] == 5
    assert [item["label"] for item in first["input"]["subjects"]] == [
        "subject-01.vtk",
        "subject-02.vtk",
        "subject-03.vtk",
        "subject-04.vtk",
        "subject-05.vtk",
    ]
    assert first["configuration"]["pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 32,
    }
    assert first["conditions"] == second["conditions"]
    assert [condition["sequence"] for condition in first["conditions"]] == list(
        range(1, 7)
    )
    for count in (1, 3, 5):
        pair = [
            condition
            for condition in first["conditions"]
            if condition["subject_count"] == count
        ]
        assert {condition["tile_autograd_strategy"] for condition in pair} == {
            "standard",
            "recompute",
        }
        assert {condition["pair_id"] for condition in pair} == {
            f"subjects-{count:05d}"
        }
        for condition in pair:
            assert condition["argv"][0:3] == [
                "diffeoforge",
                "modern-benchmark",
                "<verified-source-config>",
            ]
            assert condition["argv"][-1] == condition["output_directory"]
    assert "results" not in first
    assert "select a winner" in first["protocol"]["analysis_policy"]
    assert _schema()["title"] == "DiffeoForge prospective paired benchmark design"


def test_invalid_scope_and_protocol_fail_before_publication(tmp_path: Path) -> None:
    dense = _write_config(tmp_path / "dense.yaml", mode="dense")
    with pytest.raises(ConfigurationError, match="requires configured blockwise"):
        collect_modern_benchmark_design(dense, subject_counts=[1])

    procrustes = _write_config(tmp_path / "procrustes.yaml", procrustes=True)
    with pytest.raises(ConfigurationError, match="requires.*false"):
        collect_modern_benchmark_design(procrustes, subject_counts=[1])

    blockwise = _write_config(tmp_path / "blockwise.yaml")
    with pytest.raises(ValueError, match="non-empty"):
        collect_modern_benchmark_design(blockwise, subject_counts=[])
    with pytest.raises(ValueError, match="duplicates"):
        collect_modern_benchmark_design(blockwise, subject_counts=[1, 1])
    with pytest.raises(ConfigurationError, match="only 5 are available"):
        collect_modern_benchmark_design(blockwise, subject_counts=[6])
    with pytest.raises(TypeError, match="repeats_per_condition"):
        collect_modern_benchmark_design(
            blockwise, subject_counts=[1], repeats_per_condition=True
        )
    with pytest.raises(ValueError, match="order_seed"):
        collect_modern_benchmark_design(blockwise, subject_counts=[1], order_seed=-1)


def test_design_publication_is_atomic_escaped_immutable_and_verifiable(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = collect_modern_benchmark_design(
        config,
        subject_counts=[1, 2],
        repeats_per_condition=2,
        warmup_evaluations=0,
        created_at=FIXED_TIME,
    )
    design["source_config"]["project"] = "<script>alert(1)</script>"
    rendered = render_modern_benchmark_design_html(design)
    parser = _StructureParser()
    parser.feed(rendered)
    parser.close()

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "contains no measurements or ranking" in rendered
    assert parser.tags.count("h1") == 1
    assert parser.tags.count("table") == 1

    output = write_modern_benchmark_design(design, tmp_path / "study")
    assert verify_modern_benchmark_design(output) == design
    assert {path.name for path in output.iterdir()} == {
        DESIGN_JSON_NAME,
        DESIGN_SIDECAR_NAME,
        DESIGN_HTML_NAME,
    }
    sidecar = (output / DESIGN_SIDECAR_NAME).read_text(encoding="utf-8")
    assert sidecar == f"{sha256_file(output / DESIGN_JSON_NAME)}  {DESIGN_JSON_NAME}\n"
    with pytest.raises(FileExistsError):
        write_modern_benchmark_design(design, output)

    html_path = output / DESIGN_HTML_NAME
    original_html = html_path.read_text(encoding="utf-8")
    html_path.write_text(original_html + "changed", encoding="utf-8")
    with pytest.raises(ModernBenchmarkDesignError, match="HTML differs"):
        verify_modern_benchmark_design(output)
    html_path.write_text(original_html, encoding="utf-8")

    (output / DESIGN_JSON_NAME).write_text("{}\n", encoding="utf-8")
    with pytest.raises(ModernBenchmarkDesignError, match="sidecar does not match"):
        verify_modern_benchmark_design(output)


def test_semantic_validation_rejects_a_reordered_or_unpaired_condition(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = collect_modern_benchmark_design(config, subject_counts=[1, 2])
    design["conditions"][0], design["conditions"][1] = (
        design["conditions"][1],
        design["conditions"][0],
    )
    with pytest.raises(ModernBenchmarkDesignError, match="deterministic paired schedule"):
        render_modern_benchmark_design_html(design)


def test_cli_creates_and_immediately_verifies_pre_results_design(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    output = tmp_path / "paper-study"
    code = main(
        [
            "modern-benchmark-design",
            str(config),
            "--subjects",
            "1",
            "3",
            "5",
            "--repeats",
            "4",
            "--warmups",
            "0",
            "--order-seed",
            "17",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "Prospective benchmark design created" in captured.out
    assert "Frozen condition count: 6" in captured.out
    assert "No benchmark has been run" in captured.out
    design = verify_modern_benchmark_design(output)
    assert design["protocol"]["subject_counts"] == [1, 3, 5]
    assert design["protocol"]["repeats_per_condition"] == 4
    assert design["protocol"]["warmup_evaluations_per_repeat"] == 0
    assert design["protocol"]["order_seed"] == 17

    assert main(["modern-benchmark-design-verify", str(output)]) == 0
    verified_output = capsys.readouterr().out
    assert "Prospective benchmark design verified" in verified_output
    assert "No benchmark result" in verified_output

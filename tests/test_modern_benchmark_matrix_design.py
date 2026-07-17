from __future__ import annotations

import copy
import json
import subprocess
import sys
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
from diffeoforge.modern_benchmark_matrix_design import (  # noqa: E402
    MATRIX_DESIGN_HTML_NAME,
    MATRIX_DESIGN_JSON_NAME,
    MATRIX_DESIGN_SIDECAR_NAME,
    ModernBenchmarkMatrixDesignError,
    _schema,
    collect_modern_benchmark_matrix_design,
    render_modern_benchmark_matrix_design_html,
    verify_modern_benchmark_matrix_design,
    write_modern_benchmark_matrix_design,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
MESHES = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-07-17T10:00:00+00:00"


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


def _design(config: Path) -> dict:
    return collect_modern_benchmark_matrix_design(
        config,
        subject_counts=[1, 3],
        tile_shapes=[(64, 128), (128, 64), (3, 5)],
        repeats_per_condition=7,
        warmup_evaluations=2,
        order_seed=42,
        created_at=FIXED_TIME,
    )


def test_collection_freezes_full_factorial_adjacency_and_exact_v04_argv(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    first = _design(config)
    second = _design(config)

    assert first["matrix_design_version"] == "0.1"
    assert first["software"]["benchmark_version"] == "0.4"
    assert first["created_at"] == FIXED_TIME
    assert first["input"]["available_subject_count"] == 5
    assert first["configuration"]["source_pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 32,
    }
    protocol = first["protocol"]
    assert protocol["cell_count"] == 6
    assert protocol["condition_count"] == 12
    assert protocol["maximum_condition_count"] == 1000
    assert first["conditions"] == second["conditions"]
    assert [condition["sequence"] for condition in first["conditions"]] == list(
        range(1, 13)
    )
    assert [condition["condition_id"] for condition in first["conditions"]] == [
        "condition-0001-subjects-000001-tiles-q000128-s000064-standard",
        "condition-0002-subjects-000001-tiles-q000128-s000064-recompute",
        "condition-0003-subjects-000003-tiles-q000064-s000128-recompute",
        "condition-0004-subjects-000003-tiles-q000064-s000128-standard",
        "condition-0005-subjects-000003-tiles-q000128-s000064-recompute",
        "condition-0006-subjects-000003-tiles-q000128-s000064-standard",
        "condition-0007-subjects-000001-tiles-q000003-s000005-standard",
        "condition-0008-subjects-000001-tiles-q000003-s000005-recompute",
        "condition-0009-subjects-000001-tiles-q000064-s000128-standard",
        "condition-0010-subjects-000001-tiles-q000064-s000128-recompute",
        "condition-0011-subjects-000003-tiles-q000003-s000005-standard",
        "condition-0012-subjects-000003-tiles-q000003-s000005-recompute",
    ]

    expected_cells = {
        (count, query, source)
        for count in (1, 3)
        for query, source in ((64, 128), (128, 64), (3, 5))
    }
    observed_cells: set[tuple[int, int, int]] = set()
    for index in range(0, len(first["conditions"]), 2):
        pair = first["conditions"][index : index + 2]
        assert pair[0]["cell_id"] == pair[1]["cell_id"]
        assert {condition["tile_autograd_strategy"] for condition in pair} == {
            "standard",
            "recompute",
        }
        plan = pair[0]["effective_pairwise_evaluation"]
        observed_cells.add(
            (pair[0]["subject_count"], plan["query_tile_size"], plan["source_tile_size"])
        )
        for condition in pair:
            argv = condition["argv"]
            assert argv[0:3] == [
                "diffeoforge",
                "modern-benchmark",
                "<verified-source-config>",
            ]
            assert argv[argv.index("--query-tile-size") + 1] == str(
                condition["effective_pairwise_evaluation"]["query_tile_size"]
            )
            assert argv[argv.index("--source-tile-size") + 1] == str(
                condition["effective_pairwise_evaluation"]["source_tile_size"]
            )
            assert argv[-1] == condition["output_directory"]
    assert observed_cells == expected_cells
    assert "results" not in first
    assert _schema()["title"] == (
        "DiffeoForge prospective multi-tile benchmark matrix design"
    )


def test_invalid_scope_factors_and_condition_overflow_fail_before_publication(
    tmp_path: Path,
) -> None:
    dense = _write_config(tmp_path / "dense.yaml", mode="dense")
    with pytest.raises(ConfigurationError, match="requires configured blockwise"):
        collect_modern_benchmark_matrix_design(
            dense, subject_counts=[1], tile_shapes=[(64, 64)]
        )

    procrustes = _write_config(tmp_path / "procrustes.yaml", procrustes=True)
    with pytest.raises(ConfigurationError, match="requires.*false"):
        collect_modern_benchmark_matrix_design(
            procrustes, subject_counts=[1], tile_shapes=[(64, 64)]
        )

    blockwise = _write_config(tmp_path / "blockwise.yaml")
    with pytest.raises(ValueError, match="subject_counts.*non-empty"):
        collect_modern_benchmark_matrix_design(
            blockwise, subject_counts=[], tile_shapes=[(64, 64)]
        )
    with pytest.raises(ValueError, match="subject_counts.*duplicates"):
        collect_modern_benchmark_matrix_design(
            blockwise, subject_counts=[1, 1], tile_shapes=[(64, 64)]
        )
    with pytest.raises(ConfigurationError, match="only 5 are available"):
        collect_modern_benchmark_matrix_design(
            blockwise, subject_counts=[6], tile_shapes=[(64, 64)]
        )
    with pytest.raises(ValueError, match="tile_shapes.*non-empty"):
        collect_modern_benchmark_matrix_design(
            blockwise, subject_counts=[1], tile_shapes=[]
        )
    with pytest.raises(ValueError, match="duplicate ordered pairs"):
        collect_modern_benchmark_matrix_design(
            blockwise, subject_counts=[1], tile_shapes=[(64, 128), (64, 128)]
        )
    with pytest.raises(ValueError, match="each tile shape"):
        collect_modern_benchmark_matrix_design(
            blockwise, subject_counts=[1], tile_shapes=[(64,)]
        )
    with pytest.raises(ValueError, match="query_tile_size"):
        collect_modern_benchmark_matrix_design(
            blockwise, subject_counts=[1], tile_shapes=[(0, 64)]
        )
    with pytest.raises(TypeError, match="source_tile_size"):
        collect_modern_benchmark_matrix_design(
            blockwise, subject_counts=[1], tile_shapes=[(64, True)]
        )
    with pytest.raises(ValueError, match="exceeding the 1000-condition limit"):
        collect_modern_benchmark_matrix_design(
            blockwise,
            subject_counts=[1],
            tile_shapes=[(value, 1) for value in range(1, 502)],
        )


def test_transposed_tile_pairs_are_distinct_levels(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = collect_modern_benchmark_matrix_design(
        config,
        subject_counts=[1],
        tile_shapes=[(64, 128), (128, 64)],
        created_at=FIXED_TIME,
    )

    assert design["protocol"]["tile_shapes"] == [
        {"query_tile_size": 64, "source_tile_size": 128},
        {"query_tile_size": 128, "source_tile_size": 64},
    ]
    assert design["protocol"]["cell_count"] == 2
    assert len({condition["cell_id"] for condition in design["conditions"]}) == 2


def test_publication_is_atomic_escaped_immutable_and_verifiable(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = _design(config)
    design["source_config"]["project"] = "<script>alert(1)</script>"
    rendered = render_modern_benchmark_matrix_design_html(design)
    parser = _StructureParser()
    parser.feed(rendered)
    parser.close()

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "creating it runs no benchmark" in rendered
    assert "Frozen conditions: 12 of at most" in rendered
    assert parser.tags.count("h1") == 1
    assert parser.tags.count("table") == 1

    output = write_modern_benchmark_matrix_design(design, tmp_path / "matrix")
    assert verify_modern_benchmark_matrix_design(output) == design
    assert {path.name for path in output.iterdir()} == {
        MATRIX_DESIGN_JSON_NAME,
        MATRIX_DESIGN_SIDECAR_NAME,
        MATRIX_DESIGN_HTML_NAME,
    }
    assert (output / MATRIX_DESIGN_SIDECAR_NAME).read_text(encoding="utf-8") == (
        f"{sha256_file(output / MATRIX_DESIGN_JSON_NAME)}  {MATRIX_DESIGN_JSON_NAME}\n"
    )
    with pytest.raises(FileExistsError):
        write_modern_benchmark_matrix_design(design, output)

    (output / "extra.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ModernBenchmarkMatrixDesignError, match="unexpected files"):
        verify_modern_benchmark_matrix_design(output)
    (output / "extra.txt").unlink()

    html_path = output / MATRIX_DESIGN_HTML_NAME
    original_html = html_path.read_text(encoding="utf-8")
    html_path.write_text(original_html + "changed", encoding="utf-8")
    with pytest.raises(ModernBenchmarkMatrixDesignError, match="HTML differs"):
        verify_modern_benchmark_matrix_design(output)
    html_path.write_text(original_html, encoding="utf-8")

    (output / MATRIX_DESIGN_JSON_NAME).write_text("{}\n", encoding="utf-8")
    with pytest.raises(ModernBenchmarkMatrixDesignError, match="sidecar does not match"):
        verify_modern_benchmark_matrix_design(output)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda design: design["conditions"].reverse(), "full-factorial schedule"),
        (
            lambda design: design["protocol"].__setitem__("condition_count", 999),
            "condition count is inconsistent",
        ),
        (
            lambda design: design["protocol"]["tile_shapes"].append(
                {"query_tile_size": 64, "source_tile_size": 128}
            ),
            "non-unique elements",
        ),
    ],
)
def test_semantic_reconstruction_rejects_tampering(
    tmp_path: Path, mutation, match: str
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = _design(config)
    mutation(design)

    with pytest.raises(ModernBenchmarkMatrixDesignError, match=match):
        render_modern_benchmark_matrix_design_html(design)


def test_schema_rejects_unknown_fields(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    design = copy.deepcopy(_design(config))
    design["protocol"]["future_result"] = 1

    with pytest.raises(ModernBenchmarkMatrixDesignError, match="Additional properties"):
        render_modern_benchmark_matrix_design_html(design)


def test_cli_creates_and_immediately_verifies_design_without_execution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    output = tmp_path / "paper-matrix"
    code = main(
        [
            "modern-benchmark-matrix-design",
            str(config),
            "--subjects",
            "1",
            "3",
            "--tile-shape",
            "64x128",
            "--tile-shape",
            "128x64",
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
    assert "Pre-publication full-factorial review: 4 cells; 8/1000 conditions" in captured.out
    assert "Prospective benchmark matrix design created" in captured.out
    assert "Frozen full-factorial cells: 4" in captured.out
    assert "Frozen condition count: 8/1000" in captured.out
    assert "No benchmark has been run" in captured.out
    design = verify_modern_benchmark_matrix_design(output)
    assert design["protocol"]["subject_counts"] == [1, 3]
    assert design["protocol"]["repeats_per_condition"] == 4
    assert design["protocol"]["warmup_evaluations_per_repeat"] == 0
    assert design["protocol"]["order_seed"] == 17

    verify_code = main(["modern-benchmark-matrix-design-verify", str(output)])
    verify_output = capsys.readouterr()
    assert verify_code == 0
    assert "Prospective benchmark matrix design verified" in verify_output.out
    assert "Frozen condition count: 8/1000" in verify_output.out
    assert "No benchmark result or performance claim is present" in verify_output.out


def test_fresh_process_cli_publishes_only_three_design_files(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "blockwise.yaml")
    output = tmp_path / "fresh-process-matrix"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "modern-benchmark-matrix-design",
            str(config),
            "--subjects",
            "1",
            "--tile-shape",
            "3x5",
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Frozen condition count: 2/1000" in result.stdout
    assert "No benchmark has been run" in result.stdout
    assert {path.name for path in output.iterdir()} == {
        MATRIX_DESIGN_JSON_NAME,
        MATRIX_DESIGN_SIDECAR_NAME,
        MATRIX_DESIGN_HTML_NAME,
    }
    payload = json.loads((output / MATRIX_DESIGN_JSON_NAME).read_text(encoding="utf-8"))
    assert payload["protocol"]["condition_count"] == 2

    verification = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "modern-benchmark-matrix-design-verify",
            str(output),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert verification.returncode == 0, verification.stderr
    assert "Frozen condition count: 2/1000" in verification.stdout

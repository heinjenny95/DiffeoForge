from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.engine import atlas_objective, dense  # noqa: E402
from diffeoforge.modern_workload import (  # noqa: E402
    REPORT_HTML_NAME,
    REPORT_JSON_NAME,
    ModernWorkloadError,
    _operation_model,
    _schema,
    collect_modern_workload,
    render_modern_workload_html,
    write_modern_workload_report,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "minimal-modern-atlas.yaml"
FIXED_HOST = {
    "platform": "test-platform",
    "logical_cpus": 16,
    "physical_memory_bytes": 128 * 1024**3,
    "output_filesystem_free_bytes": 512 * 1024**3,
}


class _ReportStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        self.tags.append(tag)


def _example_config() -> dict:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def _write_portable_config(path: Path, *, project: str = "workload-test") -> Path:
    config = _example_config()
    mesh_directory = ROOT / "examples" / "synthetic" / "meshes"
    config["project"]["name"] = project
    config["input"]["directory"] = str(mesh_directory)
    config["input"]["template"] = str(mesh_directory / "template.vtk")
    config["output"]["directory"] = str(path.parent / "future-run")
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_example_workload_has_exact_public_dimensions_and_formulas() -> None:
    report = collect_modern_workload(EXAMPLE, host_observations=FIXED_HOST)

    assert report["input"]["subject_count"] == 5
    assert report["input"]["template"]["points"] == 162
    assert report["input"]["template"]["triangles"] == 320
    assert {subject["triangles"] for subject in report["input"]["subjects"]} == {320}
    objective = report["operation_model"]["one_objective_forward"]
    assert objective == {
        "gaussian_calls": 200,
        "gaussian_pair_elements": 1_606_065,
        "attachment": {
            "calls": 15,
            "pair_elements": 1_536_000,
            "orientation_pair_elements": 0,
        },
        "shooting": {"calls": 120, "pair_elements": 9_720},
        "template_flow": {"calls": 40, "pair_elements": 58_320},
        "deformetrica_heun_extrapolation": {"calls": 20, "pair_elements": 1_620},
        "deformation_energy": {"calls": 5, "pair_elements": 405},
    }
    largest = report["operation_model"]["largest_logical_pair"]
    assert largest["rows"] == largest["columns"] == 320
    assert largest["float64_xyz_difference_tensor_bytes"] == 2_457_600
    assert report["optimizer_bound"]["objective_gradient_evaluation_upper_bound"] == 190
    assert report["optimizer_bound"]["gaussian_pair_elements_upper_bound"] == (
        190 * 1_606_065
    )
    assert report["output_bound"] == {
        "maximum_retained_components": 4,
        "maximum_deformation_components": 3,
        "maximum_pca_meshes_including_mean": 7,
        "maximum_bundle_vtk_meshes": 13,
    }
    assert report["host_observations"] == FIXED_HOST
    assert "peak-RAM predictor" in report["scientific_boundary"]
    assert _schema()["title"] == "DiffeoForge modern configured-engine workload plan"


def test_blockwise_plan_separates_logical_pair_from_exact_execution_tile(
    tmp_path: Path,
) -> None:
    path = _write_portable_config(tmp_path / "blockwise.yaml")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["runtime"]["pairwise_evaluation"] = {
        "mode": "blockwise",
        "query_tile_size": 64,
        "source_tile_size": 64,
    }
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    report = collect_modern_workload(path, host_observations=FIXED_HOST)

    assert report["engine"]["id"] == "diffeoforge_modern_blockwise"
    assert report["engine"]["pairwise_evaluation"] == config["runtime"][
        "pairwise_evaluation"
    ]
    assert report["operation_model"]["largest_logical_pair"][
        "float64_xyz_difference_tensor_bytes"
    ] == 2_457_600
    tile = report["operation_model"]["largest_execution_tile"]
    assert (tile["tile_rows"], tile["tile_columns"]) == (64, 64)
    assert tile["float64_xyz_difference_tensor_bytes"] == 64 * 64 * 3 * 8
    assert report["payload_model"][
        "largest_single_execution_xyz_difference_tensor_bytes"
    ] == 64 * 64 * 3 * 8


@pytest.mark.parametrize("attachment_type", ["current", "varifold"])
@pytest.mark.parametrize("shooting_integrator", ["euler", "rk2"])
@pytest.mark.parametrize("flow_integrator", ["euler", "heun", "deformetrica_heun"])
def test_predicted_gaussian_pairs_equal_instrumented_dense_objective(
    monkeypatch: pytest.MonkeyPatch,
    attachment_type: str,
    shooting_integrator: str,
    flow_integrator: str,
) -> None:
    template_vertices = torch.tensor(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        dtype=torch.float64,
    )
    template_triangles = torch.tensor(
        [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)],
        dtype=torch.int64,
    )
    target_triangles = (
        torch.tensor([(0, 2, 1)], dtype=torch.int64),
        torch.tensor([(0, 2, 1), (0, 1, 3)], dtype=torch.int64),
    )
    targets = tuple((template_vertices.clone(), triangles) for triangles in target_triangles)
    control_points = template_vertices[:2].clone()
    momenta = torch.zeros((2, 2, 3), dtype=torch.float64)
    config = {
        "initialization": {"control_points": {"count": 2}},
        "model": {
            "attachment": {"type": attachment_type},
            "deformation": {
                "timepoints": 3,
                "shooting_integrator": shooting_integrator,
                "flow_integrator": flow_integrator,
            },
        },
    }
    template = {"points": 4, "triangles": 4}
    subjects = [
        {"label": "one-face", "points": 4, "triangles": 1},
        {"label": "two-face", "points": 4, "triangles": 2},
    ]
    predicted = _operation_model(config, template, subjects)["one_objective_forward"]
    observed_calls: list[int] = []
    original = dense.gaussian_kernel

    def observed(x, y, kernel_width):
        observed_calls.append(x.shape[0] * y.shape[0])
        return original(x, y, kernel_width)

    monkeypatch.setattr(dense, "gaussian_kernel", observed)
    result = atlas_objective(
        template_vertices,
        template_triangles,
        targets,
        control_points,
        momenta,
        deformation_kernel_width=0.8,
        attachment_kernel_width=0.7,
        noise_variance=0.1,
        number_of_time_points=3,
        attachment_type=attachment_type,
        shooting_integrator=shooting_integrator,
        flow_integrator=flow_integrator,
    )

    assert torch.isfinite(result.total)
    assert len(observed_calls) == predicted["gaussian_calls"]
    assert sum(observed_calls) == predicted["gaussian_pair_elements"]
    expected_orientation = (
        predicted["attachment"]["pair_elements"] if attachment_type == "varifold" else 0
    )
    assert predicted["attachment"]["orientation_pair_elements"] == expected_orientation


def test_html_is_escaped_and_reports_known_payloads(tmp_path: Path) -> None:
    config = _write_portable_config(tmp_path / "modern.yaml", project="<script>alert(1)</script>")
    report = collect_modern_workload(config, host_observations=FIXED_HOST)
    rendered = render_modern_workload_html(report)

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "Known payloads, not peak RAM" in rendered
    assert "not a peak-RAM predictor" in rendered
    parser = _ReportStructureParser()
    parser.feed(rendered)
    parser.close()
    assert parser.tags.count("h1") == 1
    assert parser.tags.count("h2") == 5
    assert parser.tags.count("table") == 1
    assert parser.tags.count("tr") == report["input"]["subject_count"] + 2


def test_report_directory_is_deterministic_atomic_and_safely_replaceable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_portable_config(tmp_path / "modern.yaml")
    report = collect_modern_workload(config, host_observations=FIXED_HOST)
    first = write_modern_workload_report(report, tmp_path / "first")
    second = write_modern_workload_report(report, tmp_path / "second")

    assert (first / REPORT_JSON_NAME).read_bytes() == (second / REPORT_JSON_NAME).read_bytes()
    assert (first / REPORT_HTML_NAME).read_bytes() == (second / REPORT_HTML_NAME).read_bytes()
    with pytest.raises(FileExistsError):
        write_modern_workload_report(report, first)
    changed = json.loads(json.dumps(report))
    changed["warnings"].append("new warning")
    write_modern_workload_report(changed, first, overwrite=True)
    assert json.loads((first / REPORT_JSON_NAME).read_text(encoding="utf-8")) == changed

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "user-data.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ModernWorkloadError, match="Refusing"):
        write_modern_workload_report(report, unsafe, overwrite=True)
    assert (unsafe / "user-data.txt").read_text(encoding="utf-8") == "keep"

    invalid = json.loads(json.dumps(report))
    invalid["unexpected"] = True
    with pytest.raises(ModernWorkloadError, match="schema validation"):
        write_modern_workload_report(invalid, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()

    inconsistent = json.loads(json.dumps(report))
    inconsistent["operation_model"]["largest_execution_tile"][
        "float64_xyz_difference_tensor_bytes"
    ] += 24
    with pytest.raises(ModernWorkloadError, match="execution-tile payload"):
        write_modern_workload_report(inconsistent, tmp_path / "inconsistent")
    assert not (tmp_path / "inconsistent").exists()

    inconsistent_operation = json.loads(json.dumps(report))
    inconsistent_operation["operation_model"]["one_objective_forward"][
        "gaussian_calls"
    ] += 1
    with pytest.raises(ModernWorkloadError, match="inventory and configuration"):
        write_modern_workload_report(
            inconsistent_operation, tmp_path / "inconsistent-operation"
        )

    import diffeoforge.modern_workload as module

    def fail(_report):
        raise RuntimeError("injected rendering failure")

    monkeypatch.setattr(module, "render_modern_workload_html", fail)
    failed = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="injected"):
        write_modern_workload_report(report, failed)
    assert not failed.exists()
    assert not tuple(tmp_path.glob(".failed.tmp-*"))


def test_low_detected_memory_is_a_warning_not_a_false_peak_prediction(tmp_path: Path) -> None:
    config = _write_portable_config(tmp_path / "modern.yaml")
    host = {**FIXED_HOST, "physical_memory_bytes": 1}
    report = collect_modern_workload(config, host_observations=host)

    assert any("exceeds detected physical memory" in item for item in report["warnings"])
    assert all("will use" not in item for item in report["warnings"])


def test_modern_plan_cli_writes_reports_without_starting_optimizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_portable_config(tmp_path / "modern.yaml")
    destination = tmp_path / "plan"

    def fail(*_args, **_kwargs):
        raise AssertionError("optimizer must not start")

    import diffeoforge.modern_workflow as workflow

    monkeypatch.setattr(workflow, "optimize_atlas", fail)
    code = main(["modern-plan", str(config), "--output", str(destination)])
    output = capsys.readouterr()

    assert code == 0
    assert "Optimizer evaluation upper bound: 190" in output.out
    assert "not a peak-RAM estimate" in output.out
    assert (destination / REPORT_JSON_NAME).is_file()
    assert (destination / REPORT_HTML_NAME).is_file()

    assert main(["modern-plan", str(config), "--output", str(destination)]) == 2
    assert "already exists" in capsys.readouterr().err
    assert main(
        ["modern-plan", str(config), "--output", str(destination), "--force"]
    ) == 0

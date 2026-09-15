from __future__ import annotations

import ast
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools/benchmark_engine_pair.py"


@pytest.fixture
def benchmark(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("engine_pair_benchmark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reports(benchmark):
    return [
        {
            "protocol": benchmark.PROTOCOL,
            "engine": engine,
            "attachment": attachment,
            "subdivision": level,
            "repeat": repeat,
            "threads": 1,
            "device": "cpu",
            "dtype": "float64",
            "values": dict.fromkeys(benchmark.VALUE_NAMES, 1.0),
            "cpu_model": "test CPU",
            "platform": "test Linux",
            "host_kernel": ["Linux", "test kernel", "x86_64"],
            "worker_sha256": "a" * 64,
            "input_sha256": str(level) * 64,
            "timed_evaluations_seconds": [1.0, 2.0, 3.0],
            "median_seconds": 2.0,
            "process_peak_rss_bytes": 1024,
            "torch": "1.6.0+cpu" if engine == "reference-keops" else "2.13.0+cpu",
            "environment": {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
            "faces": 320 * 4**level,
            "vertices": (162, 642)[level],
        }
        for engine, attachment, level, repeat in itertools.product(
            benchmark.ENGINES, ("current", "varifold"), (0, 1), (1, 2, 3)
        )
    ]


def test_worker_accepts_python38_syntax():
    ast.parse(SCRIPT.read_text(), feature_version=(3, 8))


def test_complete_pair_passes_frozen_protocol(benchmark, reports):
    result = benchmark.compare_reports(reports)
    assert result["numerical_pass"] is True
    assert result["observation_count"] == 36
    assert (result["rtol"], result["atol"]) == (1e-8, 1e-10)
    assert len(result["cases"]) == 12


def test_runtime_libc_label_does_not_misidentify_the_host(benchmark, reports):
    for report in reports:
        report["platform"] = "Linux-same-kernel-runtime-label-" + report["torch"]
    assert benchmark.compare_reports(reports)["numerical_pass"] is True
    reports[0]["host_kernel"] = ["Linux", "different kernel", "x86_64"]
    with pytest.raises(ValueError, match="provenance"):
        benchmark.compare_reports(reports)


def test_numeric_difference_is_not_concealed(benchmark, reports):
    for report in reports:
        if report["engine"] == "modern-dense":
            report["values"]["total"] += 1e-4
    assert benchmark.compare_reports(reports)["numerical_pass"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "host",
        "hash",
        "shape",
        "nan",
        "repeatability",
        "thread",
        "runtime",
        "timing",
        "dimension",
        "override",
    ],
)
def test_incomplete_or_incompatible_evidence_fails(benchmark, reports, mutation):
    item = reports[0]
    if mutation == "missing":
        reports.pop()
    elif mutation == "duplicate":
        reports.append(item)
    elif mutation == "host":
        item["cpu_model"] = "other"
    elif mutation == "hash":
        item["input_sha256"] = "b" * 64
    elif mutation == "shape":
        item["values"]["endpoint"] = []
    elif mutation == "nan":
        item["values"]["total"] = float("nan")
    elif mutation == "repeatability":
        item["values"]["total"] += 1e-12
    elif mutation == "thread":
        item["threads"] = 2
    elif mutation == "runtime":
        item["torch"] = "0.0"
    elif mutation == "timing":
        item["timed_evaluations_seconds"] = [1.0, 0.0, 2.0]
    elif mutation == "dimension":
        item["faces"] = 4
    elif mutation == "override":
        item["environment"]["MKL_DEBUG_CPU_TYPE"] = "5"
    with pytest.raises(ValueError):
        benchmark.compare_reports(reports)


def test_evidence_hash_and_no_overwrite(benchmark, reports, tmp_path):
    path = tmp_path / "observation.json"
    benchmark.write_report(path, reports[0])
    assert json.loads(path.read_text()) == reports[0]
    with pytest.raises(FileExistsError):
        benchmark.write_report(path, reports[0])
    with path.open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        benchmark.compare_directory(tmp_path)


def test_midpoint_subdivision_preserves_surface_area(benchmark):
    np = pytest.importorskip("numpy")
    vertices, faces = benchmark.read_mesh(ROOT / "examples/synthetic/meshes/template.vtk")
    divided, cells = benchmark.subdivide(vertices, faces)
    assert divided.shape == (642, 3)
    assert cells.shape == (1280, 3)

    def area(points, triangles):
        a, b, c = (points[triangles[:, i]] for i in range(3))
        return np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2

    assert area(divided, cells) == pytest.approx(area(vertices, faces), rel=1e-14)


def test_canonical_momenta_preserve_reference_bits_across_numpy_versions(benchmark):
    pytest.importorskip("numpy")
    momenta = benchmark.frozen_momenta(ROOT)
    assert momenta.shape == (27, 3)
    assert hashlib.sha256(momenta.tobytes()).hexdigest() == (
        "9a45c19f00f52838a4dae7866ee1ce76c6c5ec56ce30567513122fc7b6a68f48"
    )


def test_retained_public_evidence_recomputes_exact_comparison(benchmark):
    directory = ROOT / "reference/public-engine-pair-v1"
    payload = (directory / "comparison.json").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == (
        directory / "comparison.sha256"
    ).read_text().strip()
    assert benchmark.compare_directory(directory / "observations") == json.loads(payload)

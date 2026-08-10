from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import read_vtk_polydata, write_vtk_polydata
from diffeoforge.reference_validation_synthetic import (
    evaluate_synthetic_correspondence_error,
    write_synthetic_validation_benchmark,
)

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "examples" / "synthetic" / "meshes" / "template.vtk"


def test_synthetic_benchmark_is_deterministic_and_has_known_correspondence(
    tmp_path: Path,
) -> None:
    first = write_synthetic_validation_benchmark(
        TEMPLATE, tmp_path / "first", subjects_per_family=3
    )
    second = write_synthetic_validation_benchmark(
        TEMPLATE, tmp_path / "second", subjects_per_family=3
    )
    first_value = json.loads(first.read_text(encoding="utf-8"))
    second_value = json.loads(second.read_text(encoding="utf-8"))

    assert first_value["fingerprint"] == second_value["fingerprint"]
    assert len(first_value["subjects"]) == 9
    assert {item["family"] for item in first_value["subjects"]} == {
        "local",
        "global",
        "mixed",
    }
    template = read_vtk_polydata(TEMPLATE)
    for record in first_value["subjects"]:
        subject = read_vtk_polydata(first.parent / record["filename"])
        assert subject.triangles == template.triangles
        assert len(subject.vertices) == len(template.vertices)


def test_synthetic_correspondence_error_is_zero_for_exact_truth(tmp_path: Path) -> None:
    manifest = write_synthetic_validation_benchmark(
        TEMPLATE, tmp_path / "benchmark", subjects_per_family=3
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    truth = manifest.parent / value["subjects"][0]["filename"]

    result = evaluate_synthetic_correspondence_error(truth, truth)

    assert result.vertex_rmse == pytest.approx(0.0)
    assert result.vertex_p95 == pytest.approx(0.0)
    assert result.vertex_maximum == pytest.approx(0.0)


def test_synthetic_correspondence_rejects_different_topology(tmp_path: Path) -> None:
    mesh = read_vtk_polydata(TEMPLATE)
    altered = tmp_path / "altered.vtk"
    write_vtk_polydata(altered, mesh.vertices, mesh.triangles[:-1])

    with pytest.raises(ConfigurationError, match="identical ordered topology"):
        evaluate_synthetic_correspondence_error(altered, TEMPLATE)


def test_synthetic_benchmark_never_overwrites(tmp_path: Path) -> None:
    destination = tmp_path / "benchmark"
    write_synthetic_validation_benchmark(TEMPLATE, destination, subjects_per_family=3)

    with pytest.raises(ConfigurationError, match="already exists"):
        write_synthetic_validation_benchmark(TEMPLATE, destination, subjects_per_family=3)

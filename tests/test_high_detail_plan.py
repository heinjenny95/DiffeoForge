from __future__ import annotations

import math
import shutil
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.mesh import write_vtk_polydata  # noqa: E402
from diffeoforge.modern_workflow import initialize_modern_workflow  # noqa: E402
from diffeoforge.modern_workload import collect_modern_workload  # noqa: E402

FIXED_HOST = {
    "platform": "high-detail-planning-test",
    "logical_cpus": 16,
    "physical_memory_bytes": 128 * 1024**3,
    "output_filesystem_free_bytes": 512 * 1024**3,
}


def _write_10k_face_sphere(path: Path) -> Path:
    latitude_steps = 51
    longitude_steps = 100
    vertices: list[tuple[float, float, float]] = [(0.0, 0.0, 1.0)]
    for latitude in range(1, latitude_steps):
        phi = math.pi * latitude / latitude_steps
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        for longitude in range(longitude_steps):
            theta = 2.0 * math.pi * longitude / longitude_steps
            vertices.append(
                (sin_phi * math.cos(theta), sin_phi * math.sin(theta), cos_phi)
            )
    south = len(vertices)
    vertices.append((0.0, 0.0, -1.0))

    triangles: list[tuple[int, int, int]] = []
    first_ring = 1
    for longitude in range(longitude_steps):
        next_longitude = (longitude + 1) % longitude_steps
        triangles.append((0, first_ring + longitude, first_ring + next_longitude))
    internal_rings = latitude_steps - 1
    for ring in range(internal_rings - 1):
        upper = 1 + ring * longitude_steps
        lower = upper + longitude_steps
        for longitude in range(longitude_steps):
            next_longitude = (longitude + 1) % longitude_steps
            triangles.append(
                (upper + longitude, lower + longitude, upper + next_longitude)
            )
            triangles.append(
                (upper + next_longitude, lower + longitude, lower + next_longitude)
            )
    last_ring = 1 + (internal_rings - 1) * longitude_steps
    for longitude in range(longitude_steps):
        next_longitude = (longitude + 1) % longitude_steps
        triangles.append((last_ring + longitude, south, last_ring + next_longitude))

    assert len(vertices) == 5_002
    assert len(triangles) == 10_000
    return write_vtk_polydata(path, vertices, triangles)


def test_10k_face_inputs_produce_an_exact_blockwise_precompute_contract(
    tmp_path: Path,
) -> None:
    meshes = tmp_path / "10k meshes"
    meshes.mkdir()
    template = _write_10k_face_sphere(meshes / "template.vtk")
    shutil.copyfile(template, meshes / "subject-01.vtk")
    shutil.copyfile(template, meshes / "subject-02.vtk")
    config = initialize_modern_workflow(
        meshes,
        units="unitless",
        config_path=tmp_path / "modern-atlas.yaml",
        pairwise_mode="blockwise",
        query_tile_size=256,
        source_tile_size=256,
    )

    report = collect_modern_workload(config, host_observations=FIXED_HOST)

    assert report["input"]["template"]["triangles"] == 10_000
    assert {subject["triangles"] for subject in report["input"]["subjects"]} == {
        10_000
    }
    assert report["engine"]["pairwise_evaluation"] == {
        "mode": "blockwise",
        "query_tile_size": 256,
        "source_tile_size": 256,
    }
    logical = report["operation_model"]["largest_logical_pair"]
    tile = report["operation_model"]["largest_execution_tile"]
    assert (logical["rows"], logical["columns"]) == (10_000, 10_000)
    assert logical["float64_xyz_difference_tensor_bytes"] == 2_400_000_000
    assert (tile["tile_rows"], tile["tile_columns"]) == (256, 256)
    assert tile["float64_xyz_difference_tensor_bytes"] == 1_572_864

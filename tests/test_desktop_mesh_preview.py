from __future__ import annotations

from pathlib import Path

import pytest

from diffeoforge.desktop.mesh_preview import (
    DEFAULT_EDGE_BUDGET,
    MeshPreviewError,
    MeshPreviewModel,
    load_mesh_preview,
)
from diffeoforge.mesh import write_vtk_polydata


def _tetrahedron(path: Path) -> Path:
    return write_vtk_polydata(
        path,
        (
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 3.0),
        ),
        ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    )


def test_mesh_preview_loads_exact_identity_and_unique_edges(tmp_path: Path) -> None:
    source = _tetrahedron(tmp_path / "template.vtk")
    before = source.read_bytes()

    model = load_mesh_preview(source)

    assert source.read_bytes() == before
    assert model.path == source.resolve()
    assert len(model.sha256) == 64
    assert model.point_count == 4
    assert model.triangle_count == 4
    assert model.edge_count == 6
    assert model.edges == ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    assert model.bounds == (0.0, 2.0, 0.0, 1.0, 0.0, 3.0)


def test_mesh_preview_projections_preserve_aspect_and_are_deterministic(
    tmp_path: Path,
) -> None:
    model = load_mesh_preview(_tetrahedron(tmp_path / "template.vtk"))

    first = model.project("xy")
    second = model.project("xy")
    xz = model.project("xz")

    assert first == second
    assert first.source_vertex_indices == (0, 1, 2, 3)
    assert first.points == (
        (-1.0, 0.5),
        (1.0, 0.5),
        (-1.0, -0.5),
        (-1.0, 0.5),
    )
    assert xz.points[1] == pytest.approx((2.0 / 3.0, 1.0))
    assert xz.points[3] == pytest.approx((-2.0 / 3.0, -1.0))
    assert first.sampled is False
    assert first.displayed_edge_count == first.total_edge_count == 6


def test_mesh_preview_edge_budget_is_deterministic_and_disclosed(tmp_path: Path) -> None:
    model = load_mesh_preview(_tetrahedron(tmp_path / "template.vtk"))

    projection = model.project("yz", edge_budget=3)

    assert projection.source_vertex_indices == (0, 1, 3)
    assert projection.edges == ((0, 1), (0, 2), (1, 2))
    assert projection.displayed_edge_count == 3
    assert projection.total_edge_count == 6
    assert projection.sampled is True
    assert len(projection.points) <= projection.displayed_edge_count * 2


def test_default_preview_budget_bounds_plane_switch_work() -> None:
    edge_count = DEFAULT_EDGE_BUDGET + 5
    model = MeshPreviewModel(
        path=Path("large-template.vtk").resolve(),
        sha256="b" * 64,
        vertices=tuple(
            (float(index), float(index % 2), 0.0)
            for index in range(edge_count + 1)
        ),
        triangles=((0, 1, 2),),
        edges=tuple((index, index + 1) for index in range(edge_count)),
        bounds=(0.0, float(edge_count), 0.0, 1.0, 0.0, 0.0),
    )

    projection = model.project("xy")

    assert projection.sampled is True
    assert projection.displayed_edge_count == DEFAULT_EDGE_BUDGET
    assert len(projection.points) <= 2 * DEFAULT_EDGE_BUDGET


@pytest.mark.parametrize("edge_budget", [0, -1])
def test_mesh_preview_rejects_invalid_edge_budget(tmp_path: Path, edge_budget: int) -> None:
    model = load_mesh_preview(_tetrahedron(tmp_path / "template.vtk"))

    with pytest.raises(ValueError, match="positive"):
        model.project("xy", edge_budget=edge_budget)


def test_mesh_preview_rejects_degenerate_selected_plane(tmp_path: Path) -> None:
    model = MeshPreviewModel(
        path=(tmp_path / "line.vtk").resolve(),
        sha256="a" * 64,
        vertices=((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 2.0)),
        triangles=((0, 1, 2),),
        edges=((0, 1), (0, 2), (1, 2)),
        bounds=(0.0, 0.0, 0.0, 0.0, 0.0, 2.0),
    )

    with pytest.raises(MeshPreviewError, match="XY"):
        model.project("xy")


def test_mesh_preview_discards_model_if_source_changes_during_load(
    monkeypatch, tmp_path: Path
) -> None:
    from diffeoforge.desktop import mesh_preview

    source = _tetrahedron(tmp_path / "template.vtk")
    real_read = mesh_preview.load_surface_mesh

    def changing_read(path):
        loaded = real_read(path)
        source.write_bytes(source.read_bytes() + b"\n")
        return loaded

    monkeypatch.setattr(mesh_preview, "load_surface_mesh", changing_read)

    with pytest.raises(MeshPreviewError, match="changed while"):
        load_mesh_preview(source)

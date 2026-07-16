from __future__ import annotations

import struct
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import inspect_vtk, read_vtk_points, write_vtk_polydata


def write_tetrahedron(path: Path) -> Path:
    path.write_text(
        """# vtk DataFile Version 3.0
tetrahedron
ASCII
DATASET POLYDATA
POINTS 4 float
0 0 0
1 0 0
0 1 0
0 0 1
POLYGONS 4 16
3 0 2 1
3 0 1 3
3 1 2 3
3 2 0 3
""",
        encoding="ascii",
    )
    return path


def test_ascii_vtk_geometry_is_inspected(tmp_path: Path) -> None:
    metadata = inspect_vtk(write_tetrahedron(tmp_path / "mesh.vtk"))

    assert metadata.encoding == "ASCII"
    assert metadata.points == 4
    assert metadata.cells == 4
    assert metadata.triangular is True
    assert metadata.bounds == (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
    assert metadata.bounding_box_diagonal == pytest.approx(3**0.5)


def test_non_triangular_polygons_are_rejected(tmp_path: Path) -> None:
    mesh = tmp_path / "quad.vtk"
    mesh.write_text(
        """# vtk DataFile Version 3.0
quad
ASCII
DATASET POLYDATA
POINTS 4 float
0 0 0  1 0 0  1 1 0  0 1 0
POLYGONS 1 5
4 0 1 2 3
""",
        encoding="ascii",
    )

    with pytest.raises(ConfigurationError, match="not exclusively triangular"):
        inspect_vtk(mesh)


def test_binary_vtk51_split_cell_arrays_are_inspected(tmp_path: Path) -> None:
    mesh = tmp_path / "vtk51.vtk"
    points = struct.pack(">12d", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1)
    offsets = struct.pack(">5q", 0, 3, 6, 9, 12)
    connectivity = struct.pack(">12q", 0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3)
    mesh.write_bytes(
        b"# vtk DataFile Version 5.1\n"
        b"tetrahedron\n"
        b"BINARY\n"
        b"DATASET POLYDATA\n"
        b"POINTS 4 double\n"
        + points
        + b"\nPOLYGONS 5 12\n"
        + b"OFFSETS vtktypeint64\n"
        + offsets
        + b"\nCONNECTIVITY vtktypeint64\n"
        + connectivity
        + b"\n"
    )

    metadata = inspect_vtk(mesh)

    assert metadata.vtk_version == "5.1"
    assert metadata.encoding == "BINARY"
    assert metadata.points == 4
    assert metadata.cells == 4
    assert metadata.triangular is True


def test_deterministic_vtk_writer_is_exclusive_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "written.vtk"
    vertices = ((0.0, -0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    triangles = ((0, 1, 2),)

    written = write_vtk_polydata(path, vertices, triangles, title="round trip")

    assert written == path.resolve()
    assert b"\r\n" not in path.read_bytes()
    assert "POINTS 3 double" in path.read_text(encoding="ascii")
    assert read_vtk_points(path) == vertices
    assert inspect_vtk(path).cells == 1
    with pytest.raises(FileExistsError):
        write_vtk_polydata(path, vertices, triangles)


@pytest.mark.parametrize(
    ("vertices", "triangles", "message"),
    [
        (((0.0, 0.0),), ((0, 1, 2),), "vertices"),
        (((0.0, 0.0, float("nan")),), ((0, 0, 0),), "finite"),
        (((0.0, 0.0, 0.0),), ((0, 0, 0),), "repeated"),
        (
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0, 1, 3),),
            "out-of-range",
        ),
    ],
)
def test_vtk_writer_rejects_invalid_geometry(
    tmp_path: Path,
    vertices: tuple,
    triangles: tuple,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        write_vtk_polydata(tmp_path / "invalid.vtk", vertices, triangles)


def test_vtk_writer_rejects_non_ascii_title_before_creating_file(tmp_path: Path) -> None:
    path = tmp_path / "invalid-title.vtk"

    with pytest.raises(ValueError, match="ASCII"):
        write_vtk_polydata(
            path,
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0, 1, 2),),
            title="Käfer",
        )

    assert not path.exists()
